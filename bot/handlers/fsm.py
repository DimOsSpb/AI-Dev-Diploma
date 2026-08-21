"""FSM-сценарий /ask: выбор темы → текст вопроса → отправка с topic-префиксом."""

import asyncio
import logging
from uuid import UUID

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards.inline import topics_kb
from bot.services.backend_client import BackendClient
from bot.services.error_handling import handle_backend_error
from bot.services.streaming import stream_to_chat
from bot.services.typing import typing_until
from bot.states import AskFlow

router = Router(name="fsm")
log = logging.getLogger(__name__)

# Константы для feedback кнопок
FEEDBACK_CB_PREFIX = "fb"
FEEDBACK_UP = "up"
FEEDBACK_DOWN = "down"


@router.message(Command("ask"))
async def cmd_ask(message: Message, state: FSMContext) -> None:
    await state.set_state(AskFlow.waiting_for_topic)
    await message.answer("Выберите тему:", reply_markup=topics_kb())


@router.callback_query(F.data.startswith("topic:"), AskFlow.waiting_for_topic)
async def on_topic_selected(cb: CallbackQuery, state: FSMContext) -> None:
    _, slug = cb.data.split(":", 1)  # pyright: ignore[reportOptionalMemberAccess]
    if slug == "cancel":
        await state.clear()
        if cb.message is not None:
            await cb.message.edit_text("Отменено.")  # pyright: ignore[reportAttributeAccessIssue]
        await cb.answer()
        return
    await state.update_data(topic=slug)
    await state.set_state(AskFlow.waiting_for_question)
    if cb.message is not None:
        await cb.message.edit_text(  # pyright: ignore[reportAttributeAccessIssue]
            f"Тема: {slug}\nЗадайте ваш вопрос текстом."
        )
    await cb.answer()


@router.message(AskFlow.waiting_for_question, F.text)
async def on_question_received(
    message: Message,
    backend: BackendClient,
    state: FSMContext,
) -> None:
    data = await state.get_data()
    topic = data.get("topic", "general")
    prompt = f"Тема: {topic}. Вопрос: {message.text}"

    chat_id = await backend.get_or_create_chat(
        owner_external_id=str(message.chat.id),
        interface="telegram",
    )
    stop = asyncio.Event()
    typing_task = asyncio.create_task(
        typing_until(message.bot, message.chat.id, stop)  # pyright: ignore[reportArgumentType]
    )
    try:
        events = backend.send_message(
            chat_id, prompt, owner_external_id=str(message.chat.id)
        )
        await stream_to_chat(message, events, chat_id=chat_id)
    except Exception as exc:  # noqa: BLE001
        await handle_backend_error(message, exc)
    finally:
        stop.set()
        await typing_task
        await state.clear()


@router.callback_query(
    F.data.startswith(f"{FEEDBACK_CB_PREFIX}:{FEEDBACK_UP}:")
    | F.data.startswith(f"{FEEDBACK_CB_PREFIX}:{FEEDBACK_DOWN}:")
)
async def on_feedback(cb: CallbackQuery, backend: BackendClient) -> None:
    """Обработчик кнопок оценки ответа 👍/👎.

    callback_data: fb:up:<message_id> или fb:down:<message_id>
    """
    # Парсим callback_data: fb:<value>:<message_id>
    try:
        if cb.data is None or cb.message is None:
            raise ValueError("cb.data or cb.message is None")

        log.debug("Received feedback callback_data: %s", cb.data)

        # callback_data имеет формат: fb:up:<uuid>
        # UUID содержит дефисы, поэтому нужно разделить только первые 2 части
        if not cb.data.startswith(f"{FEEDBACK_CB_PREFIX}:"):
            log.warning("Invalid callback_data prefix: %s", cb.data)
            raise ValueError(f"Invalid callback_data prefix: {cb.data}")

        # Разделяем на prefix и остальное
        rest = cb.data[len(f"{FEEDBACK_CB_PREFIX}:") :]  # "up:<uuid>"
        parts = rest.split(":", 1)  # [value, uuid]
        log.debug("Parsed parts: %s", parts)
        if len(parts) < 2:
            log.warning("Invalid feedback callback_data: %s", cb.data)
            await cb.answer("Ошибка обработки оценки 1.")
            return

        value = parts[0]  # "up" или "down"
        message_id = parts[1]  # UUID сообщения
        log.debug("Extracted value=%s, message_id=%s", value, message_id)

        # Проверка что message_id похоже на UUID
        if len(message_id) < 8:
            log.warning("Invalid message_id length: %s", message_id)
            raise ValueError(f"Invalid message_id: {message_id}")

        # owner_external_id берём из chat_id пользователя
        owner_external_id = str(cb.message.chat.id)

        # message_id в callback_data — это строка UUID
        chat_id = UUID(message_id)

        await backend.post_feedback(
            chat_id=chat_id,
            message_id=message_id,
            value=value,
            owner_external_id=owner_external_id,
        )

        await cb.answer(
            f"Спасибо за оценку: {'Отлично!' if value == 'up' else 'Поняли!'}"
        )

        # Убираем inline-клавиатуру после успешной отправки фидбека
        try:
            # Проверяем, что bot доступен
            bot = getattr(cb, "bot", None)
            if bot is None:
                log.warning("cb.bot is None, cannot remove keyboard")
            else:
                await bot.edit_message_reply_markup(
                    chat_id=cb.message.chat.id,
                    message_id=cb.message.message_id,
                    reply_markup=None,
                )
        except Exception as e:  # noqa: BLE001
            log.debug("Could not remove reply_markup: %s", e)

    except ValueError:
        log.warning("Invalid callback_data: %s", cb.data)
        await cb.answer("Ошибка обработки оценки 2.")
    except Exception:
        log.exception("Failed to post feedback")
        await cb.answer("Ошибка отправки оценки 3.")
