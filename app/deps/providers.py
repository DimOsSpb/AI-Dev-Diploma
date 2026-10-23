from typing import Annotated, Any

from fastapi import Depends, Request

from app.core.config import Settings, get_settings
from app.services.llm import LLMService

SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_llm(request: Request):
    return request.app.state.llm


def get_cache(request: Request):
    return request.app.state.redis


def get_session_factory(request: Request) -> Any:
    """Возвращает async_sessionmaker, выставленный в lifespan, либо None,
    если Postgres недоступен. Роуты, которым PG обязателен, должны явно
    проверять на None и отдавать 503/собственный fallback."""
    return request.app.state.session_factory


def get_rag_service(request: Request) -> Any:
    """RAG-сервис на LlamaIndex, собранный один раз в lifespan. None — если
    Qdrant/индекс был недоступен на старте: роут отдаёт 503."""
    return request.app.state.rag_service


def get_agent_graph(request: Request) -> Any:
    """Скомпилированный ReAct-граф агента, собранный в lifespan. None — если
    сборка не удалась (нет ключа/модели): /agent/chat отдаёт 503."""
    return request.app.state.agent_graph


LLMDep = Annotated[Any, Depends(get_llm)]
CacheDep = Annotated[object, Depends(get_cache)]
SessionFactoryDep = Annotated[Any, Depends(get_session_factory)]
RAGServiceDep = Annotated[Any, Depends(get_rag_service)]
AgentGraphDep = Annotated[Any, Depends(get_agent_graph)]


def get_llm_service(
    llm: LLMDep,
    cache: CacheDep,
    settings: SettingsDep,
) -> LLMService:
    return LLMService(
        llm=llm,
        model=settings.llm.default_model,
        cache=cache,
        ttl=settings.cache_ttl,
    )


LLMServiceDep = Annotated[
    LLMService,
    Depends(get_llm_service),
]
