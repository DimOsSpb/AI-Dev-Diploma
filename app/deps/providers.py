from typing import Annotated

from app.core.config import Settings, get_settings
from app.services.llm import LLMService
from fastapi import Depends, Request

SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_llm(request: Request):
    return request.app.state.llm


def get_cache(request: Request):
    return request.app.state.redis


LLMDep = Annotated[object, Depends(get_llm)]
CacheDep = Annotated[object, Depends(get_cache)]


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
