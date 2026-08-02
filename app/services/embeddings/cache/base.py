from abc import ABC, abstractmethod

from app.core.config import get_settings


class BaseEmbeddingCache(ABC):
    """Persistent cache for embedding vectors."""

    def __init__(self) -> None:
        self.hits = 0
        self.misses = 0
        self.settings = get_settings()

    @abstractmethod
    def get(
        self,
        *,
        model: str,
        dimensions: int,
        normalize: bool,
        text: str,
    ) -> list[float] | None:
        """Return cached embedding or None."""

    @abstractmethod
    def set(
        self,
        *,
        model: str,
        dimensions: int,
        normalize: bool,
        text: str,
        embedding: list[float],
    ) -> None:
        """Store embedding."""

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses

        if total == 0:
            return 0.0

        return self.hits / total
