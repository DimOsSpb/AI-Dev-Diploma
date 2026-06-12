"""Клиент LLM с retry (tenacity) и fallback.

Все провайдеры работают через OpenAI-совместимый API.
Цепочка: primary → fallback → эскалация на оператора.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

from infraassist.core.classification import heuristic_classify
from infraassist.core.models import Category, LLMResult
from infraassist.infrastructure.config import Settings
from infraassist.tools.handlers import PVEExeption, handle_pve_status
from infraassist.tools.schemas import tools
from loguru import logger
from openai import APIStatusError, OpenAI, RateLimitError
from openai._types import Omit, omit
from openai.types.chat import (
    ChatCompletionFunctionToolParam,
    ChatCompletionMessage,
    ChatCompletionMessageParam,
)
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

# Ответ-заглушка, когда ни один провайдер не дал полезный ответ
FALLBACK_ANSWER = "Передаю вопрос специалисту."


def _build_client(api_key: str | None, base_url: str | None) -> OpenAI | None:
    """Создаёт OpenAI-совместимый клиент, если есть ключ."""
    if not api_key:
        return None
    return OpenAI(api_key=api_key, base_url=base_url)


class RobustLLMClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.primary = _build_client(settings.api_key, settings.base_url)
        self.fallback = _build_client(
            settings.fallback_api_key, settings.fallback_base_url
        )

    # ── Цепочка провайдеров ───────────────────────────────────────────

    def _provider_chain(self) -> Iterator[tuple[OpenAI, str, bool]]:
        """Отдаёт (client, model, used_fallback) для каждого доступного провайдера."""
        if self.primary is not None:
            yield self.primary, self.settings.primary_model, False
        if self.fallback is not None and self.settings.fallback_model:
            yield self.fallback, self.settings.fallback_model, True

    # ── Публичные методы ──────────────────────────────────────────────

    def classify(self, messages: list[ChatCompletionMessageParam]) -> Category:
        """Классифицирует запрос: primary → fallback → эвристика."""
        for client, model, _ in self._provider_chain():
            try:
                mess = self._call(client, model, messages, temperature=0, max_tokens=64)
                raw = mess.content or ""
                return Category(raw.strip().lower())
            except Exception as e:
                logger.warning("[classify] - Провайдер {} недоступен: {}", model, e)  # noqa: S112
                continue

        # Безопасно извлекаем контент последнего сообщения
        last_content = messages[-1].get("content") if messages else ""
        text_content = ""

        if isinstance(last_content, str):
            text_content = last_content
        elif isinstance(last_content, list):
            # Если это мультимодальный контент (список), собираем все текстовые части
            text_parts = []
            for part in last_content:
                if isinstance(part, dict) and part.get("type") == "text":
                    text_parts.append(part.get("text", ""))
                elif isinstance(part, str):
                    text_parts.append(part)
            text_content = " ".join(text_parts)

        # Теперь text_content гарантированно имеет тип str
        return heuristic_classify(text_content)

    def answer(self, messages: list[ChatCompletionMessageParam]) -> LLMResult:
        """Получает ответ: primary → fallback → эскалация."""
        for client, model, used_fallback in self._provider_chain():
            try:
                if used_fallback:
                    logger.info("Переключаюсь на fallback: {}", model)
                mes = self._call(client, model, messages, tools=tools)

                # Проверяем, хочет ли модель вызвать функцию (tool)
                if mes.tool_calls:
                    messages.append(mes)  # pyright: ignore[reportArgumentType]
                    for tool_call in mes.tool_calls:
                        func_obj = getattr(tool_call, "function", None)

                        if func_obj:
                            function_name = func_obj.name
                            function_args = func_obj.arguments

                            # Модель возвращает аргументы в виде строки JSON, парсим их в dict  # noqa: E501
                            function_args = json.loads(function_args)
                            logger.info(
                                "Модель вызвала инструмент: '{}' Аргументы: {}",
                                function_name,
                                function_args,
                            )

                        tool_output = handle_pve_status(**function_args)

                        # Отправляем результат работы функции обратно модели
                        messages.append(
                            {  # pyright: ignore[reportArgumentType]
                                "tool_call_id": tool_call.id,
                                "role": "tool",
                                "name": function_name,
                                "content": tool_output,  # Текст который вернул handler
                            }
                        )

                    # Делаем повторный запрос к модели, передавая ей результат работы функции  # noqa: E501
                    mes = self._call(client, model, messages)

                # Извлекаем объект с информацией о токенах
                usage = getattr(mes, "usage", None)
                total_tokens = None
                if usage:
                    total_tokens = usage.total_tokens

                # ? text or FALLBACK_ANSWER
                text = mes.content or FALLBACK_ANSWER
                return LLMResult(
                    text,
                    total_tokens,
                    "fallback" if used_fallback else "primary",
                    model,
                    used_fallback,
                )
            except PVEExeption as e:
                logger.warning("PVEExeption - {}", e)
            except Exception as e:
                logger.warning("[answer] Провайдер {} недоступен: {}", model, e)

        # Все провайдеры недоступны — переводим на оператора
        return LLMResult(FALLBACK_ANSWER, None, "escalation", "none", True)

    def transcribe(self, audio_path: str, stt_model: str) -> str:
        """STT: аудиофайл → текст через audio.transcriptions."""
        client = self.primary or self.fallback
        if client is None:
            return ""
        with open(audio_path, "rb") as f:
            transcript = client.audio.transcriptions.create(
                model=stt_model,
                file=f,
                language="ru",
                response_format="text",
            )
        return transcript

    # ── Внутренние методы ─────────────────────────────────────────────

    def _call(
        self,
        client: OpenAI,
        model: str,
        messages: list[ChatCompletionMessageParam],
        temperature: float = 0.2,
        max_tokens: int = 250,
        tools: list[ChatCompletionFunctionToolParam] | Omit = omit,
    ) -> ChatCompletionMessage:
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
        def _do() -> ChatCompletionMessage:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=self.settings.request_timeout_seconds,
                tools=tools,
            )
            return response.choices[0].message

        return _do()
