"""Регистрация роутеров в Dispatcher.

ORDER MATTERS: commands → handoff → fsm → callbacks → media → text.

- commands — /start, /help, /clear, /cancel.
- handoff содержит /operator (доступна всем юзерам — это их зарррос).
- fsm — /ask (выбор темы) и callback_query для feedback-кнопок (👍/👎).
- callbacks отвечает за HIL-подтверждение опасных действий агента (pve_hil:*).
- media — фото/голос/аудио/документы (PDF/DOCX).
- text — catch-all для свободного текста, должен стоять последним.

Примечание: файлы handoff.py и media.py раньше существовали, но не были
зарегистрированы здесь — исправлено. /stats и BOT_ADMIN_IDS упоминались в
старой версии этого docstring, но отдельного admin.py в проекте нет — не
реализовано, не в скоупе диплома.
"""

from aiogram import Dispatcher

from . import callbacks, commands, fsm, handoff, media, text

__all__ = ["register_routers"]


def register_routers(dp: Dispatcher) -> None:
    dp.include_router(commands.router)
    dp.include_router(handoff.router)
    dp.include_router(fsm.router)
    dp.include_router(callbacks.router)
    dp.include_router(media.router)
    dp.include_router(text.router)
