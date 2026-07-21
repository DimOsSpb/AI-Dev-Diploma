from hashlib import sha256
from pathlib import Path
from typing import cast

from diskcache import Cache

from .base import BaseEmbeddingCache


class DiskEmbeddingCache(BaseEmbeddingCache):
    """Persistent disk cache for embeddings."""

    def __init__(
        self,
        path: Path = Path("./var/cache/embeddings"),
    ):
        super().__init__()
        self.cache = Cache(path)

    @staticmethod
    def _key(
        *,
        model: str,
        dimensions: int,
        normalize: bool,
        text: str,
    ) -> str:

        source = f"{model}|{dimensions}|{normalize}|{text}"

        return sha256(source.encode("utf-8")).hexdigest()

    def get(
        self,
        *,
        model: str,
        dimensions: int,
        normalize: bool,
        text: str,
    ) -> list[float] | None:

        value = self.cache.get(
            self._key(
                model=model,
                dimensions=dimensions,
                normalize=normalize,
                text=text,
            )
        )
        if value is None:
            self.misses += 1
        else:
            self.hits += 1

        return cast(
            list[float] | None,
            self.cache.get(value),
        )

    def set(
        self,
        *,
        model: str,
        dimensions: int,
        normalize: bool,
        text: str,
        embedding: list[float],
    ) -> None:

        self.cache.set(
            self._key(
                model=model,
                dimensions=dimensions,
                normalize=normalize,
                text=text,
            ),
            embedding,
        )
