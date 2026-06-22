import logging
import time
import uuid
from collections.abc import Callable
from contextlib import asynccontextmanager

from app.core.config import get_settings
from app.core.exceptions import (
    LLMAuthError,
    LLMContentFilterError,
    LLMError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from app.routers import chat, health, models
from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from openai import AsyncOpenAI

try:
    from redis.asyncio import Redis
except ImportError:
    Redis = None


settings = get_settings()
logging.basicConfig(
    filename=settings.log_path,
    level=logging.INFO,
    encoding="utf-8",
    format=("%(asctime)s | %(levelname)s | %(name)s | %(message)s"),
)
logger = logging.getLogger(settings.service_name)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.llm = AsyncOpenAI(
        base_url=settings.llm.base_url,
        api_key=settings.llm.api_key.get_secret_value(),
        timeout=settings.llm.request_timeout,
        max_retries=settings.llm.max_retries,
    )

    app.state.redis = None
    if Redis is not None:
        try:
            redis_client = Redis.from_url(settings.redis_url, decode_responses=True)
            await redis_client.ping()
            app.state.redis = redis_client
        except Exception as e:
            logger.warning("Redis недоступен (%s) — сервис работает без кеша", e)

    yield

    try:
        await app.state.llm.close()
        if app.state.redis is not None:
            await app.state.redis.close()
    except Exception:  # noqa: S110
        pass


app = FastAPI(
    title=settings.service_name,
    version="1.0.0",
    description="FastAPI-сервис для LLM",
    lifespan=lifespan,
)


@app.middleware("http")
async def middleware(
    request: Request,
    call_next: Callable,
) -> Response:
    request.state.request_id = request.headers.get("X-Request-ID", uuid.uuid4().hex)

    t0 = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("unhandled", extra={"request_id": request.state.request_id})
        raise

    duration_ms = (time.perf_counter() - t0) * 1000
    response.headers["X-Request-ID"] = request.state.request_id

    logger.info(
        "request method=%s path=%s status=%s duration_ms=%.2f request_id=%s",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
        request.state.request_id,
    )
    return response


_STATUS_MAP: list[tuple[type[LLMError], int, str]] = [
    (LLMRateLimitError, 429, "llm_rate_limit"),
    (LLMAuthError, 502, "llm_auth"),
    (LLMTimeoutError, 504, "llm_timeout"),
    (LLMContentFilterError, 400, "content_filter"),
    (LLMError, 502, "llm_error"),
]


@app.exception_handler(LLMError)
async def handle_llm_error(request: Request, exc: LLMError):
    request_id = getattr(request.state, "request_id", "")
    for cls, status, code in _STATUS_MAP:
        if isinstance(exc, cls):
            return JSONResponse(
                status_code=status,
                content={"error": {"code": code, "message": str(exc)}},
                headers={"X-Request-ID": request_id},
            )
    return JSONResponse(
        status_code=502,
        content={"error": {"code": "llm_error", "message": str(exc)}},
        headers={"X-Request-ID": request_id},
    )


@app.exception_handler(RequestValidationError)
async def handle_validation(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "validation_error",
                "fields": [
                    {
                        "field": ".".join(str(p) for p in e["loc"][1:]),
                        "message": e["msg"],
                    }
                    for e in exc.errors()
                ],
            }
        },
        headers={"X-Request-ID": getattr(request.state, "request_id", "")},
    )


app.include_router(chat.router)
app.include_router(health.router)
app.include_router(models.router)
