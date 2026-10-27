import asyncio
import secrets
import sys
import uuid
from collections.abc import Callable
from contextlib import AsyncExitStack, asynccontextmanager

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
from app.core.ai.catalog import get_catalog
from app.core.config import MissingEnvVarsError, get_settings
from app.core.exceptions import (
    LLMAuthError,
    LLMContentFilterError,
    LLMError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from app.observability.logging import logger
from app.routers import agent, chat, health, models, rag
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

    setup_tracing(settings)  # pyright: ignore[reportArgumentType]

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

    #     app.state.rag_service = None
    #     rag = get_rag()
    #
    #     # Ждём готовности Qdrant перед индексацией
    #     logger.app.info("Ожидание готовности Qdrant...")
    #     max_retries = 30
    #     for attempt in range(max_retries):
    #         try:
    #             from qdrant_client import QdrantClient
    #
    #             qdrant_client = QdrantClient(url=settings.qdrant_url)
    #             # count() — синхронный метод, не требует await
    #             qdrant_client.count(settings.rag_collection)
    #             logger.app.info("Qdrant готов")
    #             break
    #         except Exception as e:
    #             logger.app.warning(
    #                 "Qdrant недоступен (попытка %d/%d): %s", attempt + 1, max_retries, e
    #             )
    #             await asyncio.sleep(2)
    #     else:
    #         logger.app.error("Qdrant не стал доступен за %d секунд", max_retries * 2)
    #         raise RuntimeError("Qdrant не стал доступен")
    #
    #     await rag.build()
    #     app.state.rag_service = rag
    # Индексация + RAG (LlamaIndex) — опциональны: собираем один раз на старте.
    # Импорт ленивый: llama_index тяжёлый, не нужен тестам без lifespan.
    #
    app.state.ingestion_service = None
    app.state.rag_service = None
    try:
        from app.services.ingestion import IngestionService
        from app.services.rag import RAGService

        ingestion = IngestionService(settings)
        app.state.ingestion_service = ingestion
        # Первичная индексация корпуса только если коллекция пуста — на рестартах
        # UPSERTS по сохранённому docstore всё равно пропустит неизменённое.
        if ingestion.is_collection_empty():
            await asyncio.to_thread(ingestion.ingest_all)

        rag_service = RAGService()
        await rag_service.build()
        app.state.rag_service = rag_service
        logger.app.info("RAG-сервис готов (коллекция %s)", settings.rag_collection)
    except Exception as e:
        logger.app.warning(
            "RAG/индексация не инициализированы (%s) — /rag/query и /documents вернут 503",
            e,
        )

    # Агентный слой (LangGraph): персистентный ReAct-граф с HIL.
    # Чекпоинтер держит соединение всё время работы приложения — граф
    # поднимается через AsyncExitStack и закрывается на shutdown.
    app.state.agent_graph = None
    agent_stack = AsyncExitStack()
    try:
        from langchain_openai import ChatOpenAI

        from app.agents.tools import build_search_knowledge_base
        from app.agents.tools_proxmox import (
            create_snapshot,
            pve_create_snapshot,
            pve_list_vms,
            pve_status,
        )
        from app.services.agent_persistent import agent_lifespan

        catalog = get_catalog()

        config = catalog.get_client_config(
            model_name=settings.llm.model,
            endpoint_name=settings.llm.endpoint,
        )

        api_key = "None"
        if config.api_key:
            api_key = config.api_key.get_secret_value()

        agent_model = ChatOpenAI(
            base_url=config.url,
            model=config.model,
            temperature=0,
            max_completion_tokens=settings.llm.agent_max_tokens,
            timeout=settings.llm.request_timeout,
            api_key=api_key,  # pyright: ignore[reportArgumentType]
            # Отключаем Thinking Mode у Qwen3.5 на llama.cpp — без этого модель
            # уходит в неограниченные размышления и висит/генерирует без остановки.
            # extra_body передаётся как именной параметр в openai SDK, который сам
            # делает top-level merge в JSON-теле запроса — это подтверждено
            # экспериментально (scripts/tests/test_stream.py), работает как с tools,
            # так и без. model_kwargs здесь НЕ годится: эти ключи уходят в openai SDK
            # как отдельные именнованные kwargs .create(...), а не в тело JSON —
            # незнакомый kwarg ломает вызов (подтверждено в проде:
            # "AsyncCompletions.create() got an unexpected keyword argument 'chat_template_kwargs'").
            # repeat_penalty — при temperature=0 (greedy decoding) модель может
            # зациклиться и повторить уже сгенерированную фразу (например,
            # дважды подряд повторить подтверждение успеха создания снапшота).
            # Параметр специфичен для llama.cpp, но так же уходит через extra_body.
            extra_body={
                "chat_template_kwargs": {"enable_thinking": False},
                "repeat_penalty": 1.1,
            },
        )

        async def _search_kb(query: str) -> dict:
            if app.state.rag_service is None:
                return {
                    "answer": "База знаний недоступна.",
                    "sources": [],
                    "confident": False,
                }
            # answer() - SSE-генератор для /chats/.../messages, а для
            # вызова из агентного tool нужен один готовый ответ —
            # answer_sync() возвращает {answer, top_score, sources, confident}.
            return await app.state.rag_service.answer_sync(query)

        async def _create_snapshot(draft: dict) -> str:
            # Реальный вызов Proxmox API — только после подтверждения человеком.
            result = await create_snapshot(draft)
            logger.app.info(
                "pve_create_snapshot node=%s vmid=%s name=%s -> %s",
                draft.get("node"),
                draft.get("vmid"),
                draft.get("snapshot_name"),
                result,
            )
            return result

        agent_tools = [
            build_search_knowledge_base(_search_kb),
            pve_status,
            pve_list_vms,
        ]
        app.state.agent_graph = await agent_stack.enter_async_context(
            agent_lifespan(
                settings.agent_checkpointer,
                agent_model,
                agent_tools,
                pve_create_snapshot,
                _create_snapshot,
                sqlite_path=settings.agent_sqlite_path,
                postgres_url=settings.database_url,
            )
        )
        logger.app.info(
            "Персистентный агент собран (backend=%s)", settings.agent_checkpointer
        )
    except Exception as e:
        logger.app.warning("Агентный граф не собран (%s) — /agent/chat вернёт 503", e)

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
app.include_router(agent.router)
