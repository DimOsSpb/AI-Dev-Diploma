"""Загрузка и сборка промптов для LLM.

Читает шаблоны промптов и few-shot примеры из файлов пакета
(``system_prompt.txt``, ``classifier_system_prompt.txt``,
``classifier_few_shots.json``, ``service_facts.txt``) и предоставляет
функции для формирования готовых списков сообщений для классификатора
и основного ассистента.
"""

from __future__ import annotations

from openai.types.chat import ChatCompletionMessageParam

from app.core.config import get_settings
from app.core.context import get_current_app
from app.schemas.chat import Message

from .loader import (
    load_classifier_few_shots,
    load_classifier_system_prompt,
    load_service_facts,
    load_system_prompt_template,
)

SERVICE_FACTS = load_service_facts()
SYSTEM_PROMPT_TEMPLATE = load_system_prompt_template()
CLASSIFIER_SYSTEM_PROMPT = load_classifier_system_prompt()
CLASSIFIER_FEW_SHOTS = load_classifier_few_shots()


def build_system_prompt() -> str:
    settings = get_settings()
    app = get_current_app()
    canary = getattr(app.state, "canary", "CANARY_DEFAULT_TEST")
    return SYSTEM_PROMPT_TEMPLATE.format(
        service_name=settings.service_name,
        service_facts=SERVICE_FACTS,
        canary=canary,
    )


def build_messages(
    user_message: str,
    history: list[Message] | None = None,
) -> list[Message]:

    # Сразу создаем объекты Pydantic-модели вместо сырых словарей
    messages: list[Message] = [Message(role="system", content=build_system_prompt())]

    if history:
        messages.extend(history)

    messages.append(Message(role="user", content=user_message))
    return messages


def build_classifier_messages(user_message: str) -> list[ChatCompletionMessageParam]:
    messages: list[ChatCompletionMessageParam] = [
        {"role": "system", "content": CLASSIFIER_SYSTEM_PROMPT}
    ]
    messages.extend(CLASSIFIER_FEW_SHOTS)
    messages.append({"role": "user", "content": user_message})
    return messages
