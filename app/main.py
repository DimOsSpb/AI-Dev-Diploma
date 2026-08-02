import secrets
import sys
import uuid
from collections.abc import Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from structlog.contextvars import (
    bind_contextvars,
    clear_contextvars,
)

from app.chat.routes import router as chat_router
from app.core.config import MissingEnvVarsError, get_settings
from app.core.exceptions import (
    LLMAuthError,
    LLMContentFilterError,
    LLMError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from app.observability.logging import logger
from app.routers import chat, health, models, rag
from app.services.rag import get_rag
from app.services.security.exceptions import (
    SecurityInputViolation,
    SecurityOutputViolation,
)

try:
    from redis.asyncio import Redis
except ImportError:
    Redis = None

from app.core.context import set_current_app
from app.observability.tracing import setup_tracing

try:
    settings = get_settings()
except MissingEnvVarsError as e:
    logger.app.critical("Не удалось получить настройки (%s)", e)
    sys.exit(1)


@asynccontextmanager
async def lifespan(app: FastAPI):

    setup_tracing(settings.service_name)

    app.state.llm = AsyncOpenAI(
        base_url=settings.llm.url,
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
        except Exception as e:  # noqa: BLE001
            logger.app.warning("Redis недоступен (%s) — сервис работает без кеша", e)

    set_current_app(app)
    app.state.canary = f"CANARY_{secrets.token_hex(4)}"

    # Postgres: ленивый engine — не падаем, если БД недоступна на старте.
    app.state.async_engine = None
    app.state.session_factory = None
    try:
        engine = create_async_engine(settings.database_url, pool_pre_ping=True)
        app.state.async_engine = engine
        app.state.session_factory = async_sessionmaker(engine, expire_on_commit=False)
    except Exception as e:  # noqa: BLE001
        logger.app.warning(
            "Postgres engine не создан (%s) — postgres-репозиторий недоступен",
            e,
        )

    rag = get_rag()

    await rag.build()

    yield

    try:
        await app.state.llm.close()
        if app.state.redis is not None:
            await app.state.redis.close()
    except Exception:  # noqa: BLE001, S110
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
    bind_contextvars(
        request_id=request.state.request_id,
        path=request.url.path,
        method=request.method,
    )

    try:
        response = await call_next(request)

    except Exception:
        logger.app.exception(
            "unhandled", extra={"request_id": request.state.request_id}
        )
        raise

    finally:
        clear_contextvars()

    response.headers["X-Request-ID"] = request.state.request_id
    logger.app.info(
        "request request_id=%s method=%s path=%s status=%s",
        request.state.request_id,
        request.method,
        request.url.path,
        response.status_code,
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


@app.exception_handler(SecurityInputViolation)
async def handle_security_input_violation(
    request: Request, exc: SecurityInputViolation
):

    request_id = getattr(request.state, "request_id", "")
    logger.app.warning(
        f"Input security attack blocked. request_id: {request_id}, Rule triggered: {exc.rule}"
    )
    return JSONResponse(
        status_code=200,
        content={"content": f"Blocked by guardrail: {exc.rule}"},
    )


@app.exception_handler(SecurityOutputViolation)
async def handle_security_output_violation(
    request: Request, exc: SecurityOutputViolation
):
    request_id = getattr(request.state, "request_id", "")
    logger.app.warning(
        f"Output filter blocked a response. request_id: {request_id}, Rule triggered: {exc.rule}"
    )

    return JSONResponse(
        status_code=200,
        content={"content": f"Blocked by guardrail: {exc.rule}"},
    )


app.include_router(chat.router)
app.include_router(health.router)
app.include_router(models.router)
app.include_router(chat_router)
app.include_router(rag.router)
