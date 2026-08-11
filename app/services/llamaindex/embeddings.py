"""
LlamaIndex embedding adapter.

Создает Embedding модель LlamaIndex
на основе конфигурации AI Catalog.

LlamaIndex ничего не знает
о нашей инфраструктуре AI.
Вся конфигурация приходит из Catalog.
"""

import requests
from llama_index.core.embeddings import BaseEmbedding
from llama_index.embeddings.openai import OpenAIEmbedding

from app.core.ai.catalog import get_catalog
from app.core.config import get_settings


class LlamaCppEmbedding(BaseEmbedding):
    model: str
    api_base: str

    def _embed(self, text: str) -> list[float]:
        response = requests.post(
            f"{self.api_base}/embeddings",
            json={
                "model": self.model,
                "input": text,
            },
            timeout=120,
        )
        response.raise_for_status()
        return response.json()["data"][0]["embedding"]

    def _get_text_embedding(self, text: str) -> list[float]:
        return self._embed(text)

    def _get_query_embedding(self, query: str) -> list[float]:
        return self._embed(query)

    async def _aget_text_embedding(self, text: str) -> list[float]:
        return self._embed(text)

    async def _aget_query_embedding(self, query: str) -> list[float]:
        return self._embed(query)


def create_llamaindex_embedding() -> BaseEmbedding:
    """
    Создать Embedding модель LlamaIndex.

    Использует AI Catalog как единственный
    источник конфигурации модели.
    """

    settings = get_settings()

    catalog = get_catalog()

    config = catalog.get_client_config(
        model_name=settings.embedding_model,
        endpoint_name=settings.embedding_endpoint,
    )

    api_key = None
    if config.api_key:
        api_key = config.api_key.get_secret_value()

    if settings.embedding_endpoint.startswith("llama.cpp"):
        return LlamaCppEmbedding(
            model=config.model,
            api_base=config.url,
        )

    return OpenAIEmbedding(
        model=config.model,
        api_key=api_key or "EMPTY",
        api_base=config.url,
    )
