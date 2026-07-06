"""Регистрация роутеров в Dispatcher.

ORDER MATTERS: commands → admin → handoff → fsm → media → feedback → text.

- admin содержит /stats (только для BOT_ADMIN_IDS).
- handoff содержит /operator (доступна всем юзерам — это их запрос).
- feedback отвечает за callback_query, поэтому не конкурирует с text по
  сообщениям; но логически вешаем выше text для предсказуемости порядка.
"""

from aiogram import Dispatcher

from . import commands, fsm, text

__all__ = ["register_routers"]


def register_routers(dp: Dispatcher) -> None:
    dp.include_router(commands.router)
    dp.include_router(fsm.router)
    dp.include_router(text.router)
