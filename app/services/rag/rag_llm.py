from collections.abc import AsyncGenerator
from typing import Any

from llama_index.core.base.llms.types import (
    CompletionResponse,
    LLMMetadata,
)
from llama_index.core.llms import CustomLLM
from openai import AsyncOpenAI, OpenAI
from pydantic import PrivateAttr

from app.core.ai.catalog import get_catalog
from app.core.config import get_settings


class RagLLM(CustomLLM):
    """LlamaIndex adapter over existing OpenAI-compatible infrastructure."""

    _client: OpenAI = PrivateAttr()
    _aclient: AsyncOpenAI = PrivateAttr()
    _model: str = PrivateAttr()

    def __init__(self) -> None:
        super().__init__()

        settings = get_settings()
        catalog = get_catalog()

        cfg = catalog.get_client_config(
            model_name=settings.rag_llm_model,
            endpoint_name=settings.rag_llm_endpoint,
        )

        api_key = cfg.api_key.get_secret_value() if cfg.api_key is not None else "EMPTY"

        self._client = OpenAI(
            base_url=cfg.url,
            api_key=api_key,
        )

        self._aclient = AsyncOpenAI(
            base_url=cfg.url,
            api_key=api_key,
        )

        self._model = cfg.model

    @property
    def metadata(self) -> LLMMetadata:
        return LLMMetadata(
            context_window=32768,
            num_output=4096,
            is_chat_model=True,
            model_name=self._model,
        )

    def complete(
        self,
        prompt: str,
        formatted: bool = False,
        **kwargs: Any,
    ) -> CompletionResponse:

        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            **kwargs,
        )

        text = response.choices[0].message.content or ""

        return CompletionResponse(text=text)

    async def acomplete(
        self,
        prompt: str,
        formatted: bool = False,
        **kwargs: Any,
    ) -> CompletionResponse:

        response = await self._aclient.chat.completions.create(
            model=self._model,
            messages=[
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            **kwargs,
        )

        text = response.choices[0].message.content or ""

        return CompletionResponse(text=text)

    def stream_complete(
        self,
        prompt: str,
        formatted: bool = False,
        **kwargs: Any,
    ):
        stream = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            stream=True,
            **kwargs,
        )

        for chunk in stream:
            if not chunk.choices:
                continue

            delta = chunk.choices[0].delta.content or ""

            if delta:
                yield CompletionResponse(
                    text=delta,
                    delta=delta,
                )

    async def astream_complete(
        self,
        prompt: str,
        formatted: bool = False,
        **kwargs: Any,
    ) -> AsyncGenerator[CompletionResponse]:
        """
        Альтернативная версия с генератором внутри контекста.
        Работает так же правильно, как и основной вариант.
        """

        async def generator() -> AsyncGenerator[CompletionResponse]:

            # Добавляем chat_template_kwargs через extra_body
            extra_body = {"chat_template_kwargs": {"enable_thinking": False}}

            stream = await self._aclient.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                stream=True,
                extra_body=extra_body,  # ← Правильный способ для OpenAI SDK
                **kwargs,
            )

            chunk_count = 0
            async for chunk in stream:
                chunk_count += 1

                if not chunk.choices:
                    continue

                delta = chunk.choices[0].delta.content or ""

                if delta:
                    yield CompletionResponse(
                        text=delta,
                        delta=delta,
                    )

        return generator()
