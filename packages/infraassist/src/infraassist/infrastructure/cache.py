"""Redis-кеш FAQ-ответов.

Класс ``RedisCache`` хранит пары «вопрос → ответ» в Redis,
нормализует вопросы и использует SHA-256 для ключей.
"""

from __future__ import annotations

import hashlib

import redis


def _normalize(question: str) -> str:
    return " ".join(question.strip().lower().split())


class RedisCache:
    """Кеш ответов на базе Redis."""

    def __init__(
        self, host: str = "localhost", port: int = 6379, ttl: int = 3600
    ) -> None:
        self.client = redis.Redis(host=host, port=port, decode_responses=True)
        self.ttl = ttl

    def _make_key(self, question: str) -> str:
        normalized = _normalize(question)
        return f"support:{hashlib.sha256(normalized.encode()).hexdigest()}"

    def get(self, question: str) -> bytes | str | None:
        return self.client.get(self._make_key(question))

    def set(self, question: str, answer: str) -> None:
        self.client.setex(self._make_key(question), self.ttl, answer)

    def clear(self) -> int:
        """Удаляет все ключи support:* из Redis. Возвращает количество удалённых."""
        deleted = 0
        for key in self.client.scan_iter("support:*"):
            self.client.delete(key)
            deleted += 1
        return deleted

    def reset_stats(self) -> None:
        """Сбрасывает накопленную статистику Redis (hits/misses и др.)."""
        self.client.config_resetstat()

    def stats(self) -> dict[str, str | int]:
        info = self.client.info("stats")
        hits = info.get("keyspace_hits", 0)
        misses = info.get("keyspace_misses", 0)
        total = hits + misses
        return {
            "hits": hits,
            "misses": misses,
            "hit_rate": f"{hits / total * 100:.1f}%" if total else "N/A",
            "keys": self.client.dbsize(),
        }
