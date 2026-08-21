"""HTTP-API бота — обратный канал для push'ей от backend.

Endpoints:
- `GET /ready` — проверка доступности backend
- `POST /notify` — защищён общим секретом `X-Internal-Token`
Backend (или внутренний admin-flow) может попросить бота отправить
сообщение конкретному пользователю Telegram.
"""

import urllib.request

from aiogram import Bot
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from app.core.config import get_settings


class NotifyRequest(BaseModel):
    chat_id: int
    text: str


def build_api(bot: Bot, internal_token: str) -> FastAPI:
    """Строит FastAPI-приложение, шлющее сообщения через переданный Bot."""
    api = FastAPI(title="bot-notify-api")

    @api.get("/ready")
    async def ready() -> dict:
        """Проверка доступности backend."""
        _setting = get_settings()
        try:
            resp = urllib.request.urlopen(f"{_setting.backend_url}/ready", timeout=3)
            if resp.status == 200:
                return {"status": "ok", "backend": "up"}
            return {"status": "degraded", "backend": "unavailable"}
        except Exception:
            return {"status": "degraded", "backend": "unavailable"}

    @api.post("/notify")
    async def notify(
        req: NotifyRequest,
        x_internal_token: str = Header(...),
    ) -> dict:
        if x_internal_token != internal_token:
            raise HTTPException(status_code=401, detail="invalid token")
        await bot.send_message(chat_id=req.chat_id, text=req.text)
        return {"ok": True}

    @api.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    return api


settings = get_settings()
bot = Bot(token=settings.bot_token)
api = build_api(bot, settings.internal_token)
app = api
