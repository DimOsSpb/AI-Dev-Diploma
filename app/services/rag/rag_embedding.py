from typing import Any

from llama_index.core.base.embeddings.base import BaseEmbedding
from pydantic import PrivateAttr

from app.core.config import get_settings
from app.services.embeddings.models import EmbeddingModelConfig
from app.services.embeddings.vectorizer import Vectorizer


class DiplomaEmbedding(BaseEmbedding):
    """
    Адаптер Vectorizer -> LlamaIndex BaseEmbedding.
    Использует существующую инфраструктуру эмбеддингов проекта.
    """

    _vectorizer: Vectorizer = PrivateAttr()

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        settings = get_settings()

        config = EmbeddingModelConfig(
            endpoint=settings.embedding_endpoint,
            name=settings.embedding_model,
            dimensions=settings.embedding_dim,
            normalize=True,
            batch_size=32,
        )

        self._vectorizer = Vectorizer(config)

    #
    # Query embedding
    #

    def _get_query_embedding(self, query: str) -> list[float]:
        return self._vectorizer.embed_texts([query])[0]

    async def _aget_query_embedding(self, query: str) -> list[float]:
        return self._get_query_embedding(query)

    #
    # Text embedding
    #

    def _get_text_embedding(self, text: str) -> list[float]:
        return self._vectorizer.embed_texts([text])[0]

    def _get_text_embeddings(self, texts: list[str]) -> list[list[float]]:
        return self._vectorizer.embed_texts(texts)

    async def _aget_text_embedding(self, text: str) -> list[float]:
        return self._get_text_embedding(text)

    async def _aget_text_embeddings(
        self,
        texts: list[str],
    ) -> list[list[float]]:
        return self._get_text_embeddings(texts)
