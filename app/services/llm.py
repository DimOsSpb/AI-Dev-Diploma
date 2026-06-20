from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Iterator

from app.core.config import Settings
from app.schemas.models import LLMResult
from app.services.cache import RedisCache
from loguru import logger
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam

FALLBACK_ANSWER = "Передаю вопрос специалисту."


def _build_client(
    api_key: str | None, base_url: str | None, timeout: int = 30, max_retries: int = 3
) -> AsyncOpenAI | None:
    if not api_key:
        return None

    return AsyncOpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=timeout,
        max_retries=max_retries,
    )


class LLMClient:
    def __init__(
        self,
        settings: Settings,
        cache: RedisCache | None = None,
        concurrency: int = 5,
    ) -> None:
        self.settings = settings
        self.cache = cache

        self.primary = _build_client(
            settings.api_key,
            settings.base_url,
            settings.request_timeout,
            settings.max_retries,
        )

        self.fallback = _build_client(
            settings.fallback_api_key,
            settings.fallback_base_url,
            settings.request_timeout,
            settings.max_retries,
        )

        self._sem = asyncio.Semaphore(concurrency)

    def _provider_chain(
        self,
    ) -> Iterator[tuple[AsyncOpenAI, str, bool]]:
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

    async def stream_chat(
        self,
        messages: list[ChatCompletionMessageParam],
    ) -> AsyncIterator[str]:

        stream = None
        model_used = None
        usage = None

        for client, model, used_fallback in self._provider_chain():
            try:
                stream = await client.chat.completions.create(
                    model=model,
                    messages=messages,
                    stream=True,
                    stream_options={"include_usage": True},
                )

                model_used = model
                break

            except Exception as e:
                logger.warning(
                    "Не удалось открыть stream через {}: {}",
                    model,
                    e,
                )

        if stream is None:
            raise RuntimeError("Все провайдеры недоступны")

        async for chunk in stream:
            if chunk.usage:
                usage = chunk.usage
            if not chunk.choices:
                continue

            delta = chunk.choices[0].delta.content
            if delta:
                yield delta

        if usage:
            logger.info(
                "stream.finished model={} total_tokens={}",
                model_used,
                usage.total_tokens,
            )

    async def batch_chat(
        self,
        messages_list: list[list[ChatCompletionMessageParam]],
        concurrency: int = 5,
    ) -> list[LLMResult | BaseException]:

        self._sem = asyncio.Semaphore(concurrency)

        tasks = [self.complete(messages) for messages in messages_list]

        return await asyncio.gather(
            *tasks,
            return_exceptions=True,
        )

    async def complete(
        self,
        messages: list[ChatCompletionMessageParam],
    ) -> LLMResult:
        started = time.perf_counter()
        status = "unknown"
        cache_key: str | None = None
        model_used = "none"
        try:
            async with self._sem:
                async with asyncio.timeout(15):
                    if self.cache:
                        cache_key = self.cache._make_key(
                            self._extract_user_message(messages)
                        )

                        cached = self.cache.get(cache_key)

                        if cached is not None:
                            status = "cache"
                            model_used = status
                            return LLMResult(
                                text=str(cached),
                                tokens=0,
                                provider=model_used,
                                model=model_used,
                                used_fallback=False,
                            )

                    for client, model, used_fallback in self._provider_chain():
                        try:
                            model_used = model
                            if used_fallback:
                                logger.info(
                                    "Переключаюсь на fallback: {}",
                                    model,
                                )

                            text, tokens = await self._answer_from(
                                client,
                                model,
                                messages,
                            )

                            if self.cache and cache_key:
                                self.cache.set(cache_key, text)

                            status = "success"
                            return LLMResult(
                                text=text,
                                tokens=tokens,
                                provider=("fallback" if used_fallback else "primary"),
                                model=model,
                                used_fallback=used_fallback,
                            )

                        except Exception as e:
                            status = "providers_error"
                            logger.warning(
                                "Провайдер {} недоступен: {}",
                                model,
                                e,
                            )
                            raise Exception(e)
        except TimeoutError:
            status = "timeout"
            raise TimeoutError
        finally:
            duration_ms = (time.perf_counter() - started) * 1000

            logger.info(
                "async.llm.call duration_ms={:.2f} model={} prompt_chars={} status={}",
                duration_ms,
                model_used,
                len(self._extract_user_message(messages)),
                status,
            )

        return LLMResult(
            text=FALLBACK_ANSWER,
            tokens=0,
            provider="escalation",
            model="none",
            used_fallback=True,
        )

    async def _answer_from(
        self,
        client: AsyncOpenAI,
        model: str,
        messages: list[ChatCompletionMessageParam],
    ) -> tuple[str, int]:

        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.2,
            max_tokens=250,
        )

        text = (response.choices[0].message.content or "").strip()

        tokens = response.usage.total_tokens if response.usage else 0

        return text or FALLBACK_ANSWER, tokens
