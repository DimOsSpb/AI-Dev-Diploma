"""HIL-подтверждение опасного действия агента (например, снапшот Proxmox).

Кнопки из `bot.keyboards.inline.pve_confirm_kb` шлют callback_data вида
`pve_hil:<approve|reject>:<chat_id>`. Обработчик вызывает
`POST /chats/{id}/messages/resume` и стримит результат так же, как обычное
сообщение (agent продолжает граф с места interrupt).
"""

import asyncio
import logging
from uuid import UUID

from aiogram import F, Router
from aiogram.types import CallbackQuery

from bot.keyboards.inline import PVE_HIL_APPROVE, PVE_HIL_CB_PREFIX
from bot.services.backend_client import BackendClient
from bot.services.error_handling import handle_backend_error
from bot.services.streaming import stream_to_chat
from bot.services.typing import typing_until

router = Router(name="callbacks")
log = logging.getLogger(__name__)


@router.callback_query(F.data.startswith(f"{PVE_HIL_CB_PREFIX}:"))
async def on_pve_hil_decision(cb: CallbackQuery, backend: BackendClient) -> None:
    """callback_data: pve_hil:<approve|reject>:<chat_id>."""
    if cb.data is None or cb.message is None:
        await cb.answer("Ошибка обработки подтверждения.")
        return

    try:
        _, action, chat_id_str = cb.data.split(":", 2)
        chat_id = UUID(chat_id_str)
    except ValueError:
        log.warning("Invalid pve_hil callback_data: %s", cb.data)
        await cb.answer("Ошибка обработки подтверждения.")
        return

    decision = action == PVE_HIL_APPROVE

    # Убираем клавиатуру сразу — чтобы нельзя было нажать повторно.
    try:
        await cb.message.edit_reply_markup(reply_markup=None)  # pyright: ignore[reportAttributeAccessIssue]
    except Exception:  # noqa: BLE001
        log.debug("Could not remove pve_hil reply_markup")

    await cb.answer("Подтверждено" if decision else "Отклонено")

    owner_external_id = str(cb.message.chat.id)
    stop = asyncio.Event()
    typing_task = asyncio.create_task(
        typing_until(cb.message.bot, cb.message.chat.id, stop)  # pyright: ignore[reportArgumentType]
    )
    try:
        events = backend.resume_message(
            chat_id,
            decision,
            owner_external_id=owner_external_id,
        )
        await stream_to_chat(cb.message, events, chat_id=chat_id)  # pyright: ignore[reportArgumentType]
    except Exception as exc:  # noqa: BLE001
        await handle_backend_error(cb.message, exc)  # pyright: ignore[reportArgumentType]
    finally:
        stop.set()
        await typing_task
