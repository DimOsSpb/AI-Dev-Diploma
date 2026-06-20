from __future__ import annotations

from collections.abc import Iterator

from app.core.config import Settings
from app.schemas.models import LLMResult
from app.services.cache import RedisCache
from loguru import logger
from openai import APIStatusError, OpenAI, RateLimitError
from openai.types.chat import ChatCompletionMessageParam
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

# Ответ-заглушка, когда ни один провайдер не дал полезный ответ
FALLBACK_ANSWER = "Передаю вопрос специалисту."


def _build_client(api_key: str | None, base_url: str | None) -> OpenAI | None:
    if not api_key:
        return None
    return OpenAI(api_key=api_key, base_url=base_url)


class SyncLLMClient:
    def __init__(
        self,
        settings: Settings,
        cache: RedisCache | None = None,
    ) -> None:
        self.settings = settings
        self.primary = _build_client(settings.api_key, settings.base_url)
        self.fallback = _build_client(
            settings.fallback_api_key, settings.fallback_base_url
        )
        self.cache = cache

    def _provider_chain(self) -> Iterator[tuple[OpenAI, str, bool]]:
        """Отдаёт (client, model, used_fallback) для каждого доступного провайдера."""
        if self.primary is not None:
            yield self.primary, self.settings.primary_model, False
        if self.fallback is not None and self.settings.fallback_model:
            yield self.fallback, self.settings.fallback_model, True

    def _extract_user_message(
        self,
        messages: list[ChatCompletionMessageParam],
    ) -> str:
        for msg in reversed(messages):
            if msg["role"] == "user":
                return str(msg["content"])
        return ""

    def complete(self, messages: list[ChatCompletionMessageParam]) -> LLMResult:
        """Получает ответ: primary → fallback → эскалация."""
        cache_key: str | None = None
        if self.cache:
            cache_key = self.cache._make_key(self._extract_user_message(messages))
            cached = self.cache.get(cache_key)

            if cached is not None:
                return LLMResult(
                    text=str(cached),
                    tokens=0,
                    provider="cache",
                    model="cache",
                    used_fallback=False,
                )

        for client, model, used_fallback in self._provider_chain():
            try:
                if used_fallback:
                    logger.info("Переключаюсь на fallback: {}", model)
                text, tokens = self._answer_from(client, model, messages)

                if self.cache and cache_key:
                    self.cache.set(cache_key, text)

                return LLMResult(
                    text,
                    tokens,
                    "fallback" if used_fallback else "primary",
                    model,
                    used_fallback,
                )
            except Exception as e:
                logger.warning("Провайдер {} недоступен: {}", model, e)

        # Все провайдеры недоступны — переводим на оператора
        return LLMResult(FALLBACK_ANSWER, 0, "escalation", "none", True)

    # ── Внутренние методы ─────────────────────────────────────────────

    def _answer_from(
        self,
        client: OpenAI,
        model: str,
        messages: list[ChatCompletionMessageParam],
    ) -> tuple[str, int]:
        """Один ответ от провайдера. Возвращает (текст, токены)."""
        text = self._call(client, model, messages)
        return (text or FALLBACK_ANSWER), 0

    def _call(
        self,
        client: OpenAI,
        model: str,
        messages: list[ChatCompletionMessageParam],
        temperature: float = 0.2,
        max_tokens: int = 250,
    ) -> str:
        """Вызов LLM с retry через tenacity (экспоненциальная задержка)."""

        def should_retry(error: BaseException) -> bool:
            if isinstance(error, RateLimitError):
                return True
            if isinstance(error, APIStatusError) and error.status_code >= 500:
                return True
            return False

        @retry(
            wait=wait_exponential(multiplier=1, min=1, max=60),
            stop=stop_after_attempt(5),
            retry=retry_if_exception(should_retry),
            reraise=True,
        )
        def _do() -> str:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=self.settings.request_timeout,
            )
            return (response.choices[0].message.content or "").strip()

        return _do()
