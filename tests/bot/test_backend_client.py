"""Контрактные тесты BackendClient через httpx.MockTransport.

Не дёргают реальный backend — проверяют, что бот правильно сериализует
запросы и парсит SSE-ответ chat-сервиса.
"""

import json
from uuid import uuid4

import httpx
import pytest

from bot.services.backend_client import BackendClient


@pytest.mark.asyncio
async def test_get_or_create_chat():
    chat_id = uuid4()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/chats"
        assert request.method == "POST"
        body = json.loads(request.content.decode())
        assert body["owner_external_id"] == "tg-123"
        assert body["interface"] == "telegram"
        return httpx.Response(200, json={"chat_id": str(chat_id)})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://x") as c:
        client = BackendClient(c)
        result = await client.get_or_create_chat("tg-123", "telegram")
        assert result == chat_id


@pytest.mark.asyncio
async def test_send_message_parses_sse():
    sse_body = (
        b'data: {"type":"token","delta":"\xd0\x9f\xd1\x80\xd0\xb8"}\n\n'
        b'data: {"type":"token","delta":"\xd0\xb2\xd0\xb5\xd1\x82"}\n\n'
        b'data: {"type":"done"}\n\n'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        # Тело — form-encoded (без media) или multipart (с media);
        # JSON-body здесь точно не должно быть.
        ct = request.headers["content-type"]
        assert ct.startswith("application/x-www-form-urlencoded") or ct.startswith(
            "multipart/form-data"
        )
        # Поле content передано в form-теле
        assert b"content=hi" in request.content or b"hi" in request.content
        return httpx.Response(
            200,
            content=sse_body,
            headers={"Content-Type": "text/event-stream"},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://x") as c:
        client = BackendClient(c)
        events = [d async for d in client.send_message(uuid4(), "hi")]
    # Все events — dict-кадры (token), done выкинул из цикла
    assert all(isinstance(e, dict) for e in events)
    deltas = [e["delta"] for e in events if e.get("type") == "token"]
    assert "".join(deltas) == "Привет"


@pytest.mark.asyncio
async def test_send_message_yields_message_saved_event():
    """Backend сообщает id сохранённого ответа отдельным SSE-кадром."""
    sse_body = (
        b'data: {"type":"token","delta":"hi"}\n\n'
        b'data: {"type":"message_saved","message_id":"00000000-0000-0000-0000-000000000abc"}\n\n'
        b'data: {"type":"done"}\n\n'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=sse_body,
            headers={"Content-Type": "text/event-stream"},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://x") as c:
        client = BackendClient(c)
        events = [d async for d in client.send_message(uuid4(), "hi")]
    saved = [e for e in events if e.get("type") == "message_saved"]
    assert len(saved) == 1
    assert saved[0]["message_id"] == "00000000-0000-0000-0000-000000000abc"
