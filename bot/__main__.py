"""Точка входа: long polling + Dispatcher."""

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from bot.config import get_bot_settings
from bot.handlers import register_routers
from bot.services.backend_client import BackendClient
from bot.services.http import build_http_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("bot")


async def main() -> None:
    settings = get_bot_settings()
    if settings.proxy:
        session = AiohttpSession(proxy=settings.proxy)
    else:
        session = None
    bot = Bot(
        token=settings.bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        session=session,
    )
    dp = Dispatcher(storage=MemoryStorage())

    http = build_http_client(settings)
    backend = BackendClient(http)
    dp["backend"] = backend

    register_routers(dp)

    log.info("Bot starting (backend=%s)", settings.backend_url)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
