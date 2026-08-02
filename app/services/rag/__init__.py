from functools import lru_cache

from .rag import RAGService


@lru_cache
def get_rag() -> RAGService:
    return RAGService()
