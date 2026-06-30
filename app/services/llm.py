from __future__ import annotations

import hashlib
import json
import time
from collections.abc import AsyncIterator, Iterable
from typing import Never, cast

from openai import (
    APIConnectionError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    BadRequestError,
    RateLimitError,
)
from openai.types.chat import ChatCompletionMessageParam
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.exceptions import (
    LLMAuthError,
    LLMContentFilterError,
    LLMError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from app.observability.logging import logger
from app.observability.pii import (
    prompt_hash,
    redact_pii,
)
from app.prompts.builder import build_messages
from app.schemas.chat import ChatDelta, ChatRequest, ChatResponse, Message, Usage


class LLMService:
    def __init__(self, llm: AsyncOpenAI, model: str, cache, ttl: int = 3600):
        self.llm = llm
        self.default_model = model
        self.cache = cache
        self.ttl = ttl

    def _key(self, req: ChatRequest) -> str:
        payload = req.model_dump(exclude={"user_id", "session_id", "stream"})
        blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return "chat:" + hashlib.sha256(blob.encode()).hexdigest()

    def _raise_domain_error(self, e: Exception) -> Never:
        if isinstance(e, RateLimitError):
            raise LLMRateLimitError(str(e)) from e

        if isinstance(e, AuthenticationError):
            raise LLMAuthError(str(e)) from e

        if isinstance(e, APITimeoutError):
            raise LLMTimeoutError(str(e)) from e

        if isinstance(e, BadRequestError):
            msg = str(e).lower()

            if "content" in msg and ("filter" in msg or "policy" in msg):
                raise LLMContentFilterError(str(e)) from e

            raise LLMError(str(e)) from e

        if isinstance(e, APIConnectionError):
            raise LLMError(f"connection error: {e}") from e

        raise LLMError(str(e)) from e

    @retry(
        retry=retry_if_exception_type((
            RateLimitError,
            APITimeoutError,
            APIConnectionError,
        )),
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=1, max=10),
    )
    async def _call(self, req: ChatRequest) -> ChatResponse:
        started = time.perf_counter()

        raw_prompt = "\n".join(
            msg.content for msg in req.messages if isinstance(msg.content, str)
        )

        try:
            mes = cast(
                Iterable[ChatCompletionMessageParam],
                [m.model_dump() for m in req.messages],
            )

            raw = await self.llm.chat.completions.create(
                model=req.model or self.default_model,
                messages=mes,
                temperature=req.temperature,
                max_tokens=req.max_tokens,
                max_completion_tokens=req.max_completion_tokens,
                # Добавляем эту строчку: она заберет словарь из Pydantic и передаст его в OpenAI клиент
                extra_body=getattr(req, "extra_body", None),
            )

            latency_ms = round((time.perf_counter() - started) * 1000, 2)

            logger.obs.info(
                "llm_request_completed",
                model=raw.model,
                input_tokens=raw.usage.prompt_tokens if raw.usage else 0,
                output_tokens=raw.usage.completion_tokens if raw.usage else 0,
                latency_ms=latency_ms,
                finish_reason=raw.choices[0].finish_reason,
                prompt_hash=prompt_hash(raw_prompt),
                prompt_preview=redact_pii(raw_prompt)[:120],
            )

            return ChatResponse.from_openai(raw)

        except Exception as e:  # noqa: BLE001
            self._raise_domain_error(e)

    async def complete(self, req: ChatRequest) -> ChatResponse:

        key = self._key(req)

        if req.temperature == 0 and self.cache:
            blob = await self.cache.get(key)
            if blob:
                resp = ChatResponse.model_validate_json(blob)
                resp.cached = True
                return resp

        # Извлекаем и перестраиваем сообщения
        req.messages = cast(list[Message], build_messages(req.messages[0].content))
        resp = await self._call(req)
        resp.cached = False

        if self.cache:
            await self.cache.setex(key, self.ttl, resp.model_dump_json())

        return resp

    async def stream(self, req: ChatRequest) -> AsyncIterator[ChatDelta]:
        try:
            stream = await self.llm.chat.completions.create(
                model=req.model or self.default_model,
                messages=cast(
                    Iterable[ChatCompletionMessageParam],
                    [m.model_dump() for m in req.messages],
                ),
                temperature=req.temperature,
                max_tokens=req.max_tokens,
                stream=True,
                stream_options={"include_usage": True},
            )
            async for chunk in stream:
                if getattr(chunk, "choices", None):
                    delta = chunk.choices[0].delta
                    if getattr(delta, "content", None):
                        yield ChatDelta(content=delta.content)
                if getattr(chunk, "usage", None):
                    yield ChatDelta(usage=Usage.from_openai(chunk.usage))
        except Exception as e:  # noqa: BLE001
            self._raise_domain_error(e)
