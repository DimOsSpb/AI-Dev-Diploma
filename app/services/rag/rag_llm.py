from typing import Any

from llama_index.core.base.llms.types import (
    ChatMessage,
    ChatResponse,
    CompletionResponse,
    LLMMetadata,
    MessageRole,
)
from llama_index.core.llms import CustomLLM
from openai import OpenAI
from pydantic import PrivateAttr

from app.core.ai.catalog import get_catalog
from app.core.config import get_settings


class RagLLM(CustomLLM):
    """LlamaIndex adapter over existing OpenAI-compatible infrastructure."""

    _client: OpenAI = PrivateAttr()
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
                    "role": "system",
                    "content": (
                        "Отвечай только по предоставленному контексту. "
                        "Если ответа нет — скажи 'Релевантного ответа не нашлось'."
                    ),
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
        )

        text = response.choices[0].message.content or ""

        return CompletionResponse(text=text)

    def stream_complete(self, *args: Any, **kwargs: Any):
        raise NotImplementedError()

    def chat(self, messages, **kwargs):
        prompt = "\n".join(f"{m.role.value}: {m.content or ''}" for m in messages)

        resp = self.complete(prompt)

        return ChatResponse(
            message=ChatMessage(
                role=MessageRole.ASSISTANT,
                content=resp.text,
            )
        )

    def stream_chat(self, *args: Any, **kwargs: Any):
        raise NotImplementedError()
