from .base import BaseEmbeddingCache
from .disk import DiskEmbeddingCache


def create_cache() -> BaseEmbeddingCache:
    return DiskEmbeddingCache()
