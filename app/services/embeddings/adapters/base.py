"""
Базовый интерфейс embedding-моделей.

adapter отвечает только за взаимодействие с конкретным backend endpoint + model,
(OpenAI API, llama.cpp, SentenceTransformers и т.д.) и получение
векторных представлений для переданных текстов.

Логика батчинга, кеширования, retry, нормализации и особенностей
семейств моделей (например, E5) реализуется уровнем выше — в Vectorizer.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.core.ai.models import ModelConfig

__all__ = [
    "BaseEmbeddingAdapter",
]


class BaseEmbeddingAdapter(ABC):
    """Абстрактный интерфейс провайдера embedding-моделей."""

    def __init__(
        self,
        config: ModelConfig,
    ) -> None:
        self.config = config

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """
        Преобразовать список текстов в список embedding-векторов.

        Args:
            texts: Список текстов для векторизации.

        Returns:
            Список embedding-векторов в том же порядке,
            что и входные тексты.

        Raises:
            RuntimeError:
                Если backend недоступен или произошла ошибка
                получения embeddings.
        """
        raise NotImplementedError
