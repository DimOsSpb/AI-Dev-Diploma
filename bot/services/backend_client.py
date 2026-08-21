"""Тонкий async-клиент к chat-сервису.

Бот не хранит истории/контекста — всё это есть на стороне backend.
Здесь только операции: получить chat_id, отправить сообщение (SSE с
опциональным media через multipart/form-data), очистить историю,
оставить feedback, admin-команды (stats/handoff/alerts).

Заголовок `X-Owner-External-Id` передаётся в каждом POST/DELETE-вызове,
где есть владелец, — backend использует его для rate-limit.

Retry: tenacity — только на сетевых ошибках (ConnectError/ConnectTimeout).
4xx/5xx не ретраятся (чтобы не тратить токены LLM).
"""

import json
import logging
from collections.abc import AsyncIterator
from uuid import UUID

import httpx
import tenacity

log = logging.getLogger(__name__)


class BackendClient:
    def __init__(self, http: httpx.AsyncClient, admin_token: str = "") -> None:
        self.http = http
        self._admin_token = admin_token
        self._retry_counter = 0
        self._max_retries = 3

    @tenacity.retry(
        stop=tenacity.stop_after_attempt(3),
        wait=tenacity.wait_exponential(multiplier=1, min=2, max=10),
        retry=tenacity.retry_if_exception_type((
            httpx.ConnectError,
            httpx.ConnectTimeout,
        )),
        before_sleep=lambda retry_state: log.warning(
            f"Retry attempt {retry_state.attempt_number}: {retry_state.exception()}",  # pyright: ignore[reportAttributeAccessIssue]
        ),
    )
    async def _make_request(self, method: str, url: str, **kwargs) -> httpx.Response:
        """Обёртка с retry для сетевых ошибок."""
        return await self.http.request(method, url, **kwargs)

    def _format_error_message(self, error: Exception) -> str:
        """Формирует понятное сообщение для пользователя."""
        if isinstance(error, httpx.ConnectError):
            return "Сервис недоступен, попробуйте позже."
        if isinstance(error, httpx.ConnectTimeout):
            return "Соединение с сервером не удалось установить."
        if isinstance(error, httpx.ReadTimeout):
            return "Ответ занимает слишком долго. Попробуйте короче."
        if isinstance(error, httpx.HTTPStatusError):
            response = error.response
            if response.status_code == 429:
                return "Слишком много запросов, подождите минуту."
            if 500 <= response.status_code < 600:
                return "Внутренняя ошибка сервиса. Мы уже знаем."
            return "Не удалось обработать запрос."
        return "Что-то пошло не так. Попробуйте ещё раз."

    # --- chat operations -------------------------------------------------
    async def get_or_create_chat(
        self,
        owner_external_id: str,
        interface: str,
    ) -> UUID:
        """POST /chats; идемпотентно по (owner, interface)."""
        r = await self._make_request(
            "POST",
            "/chats",
            json={
                "owner_external_id": owner_external_id,
                "interface": interface,
            },
            headers={"X-Owner-External-Id": owner_external_id},
        )
        r.raise_for_status()
        return UUID(r.json()["chat_id"])  # type: ignore[return-value]

    async def get_chat_by_owner(
        self,
        owner_external_id: str,
        interface: str,
    ) -> UUID | None:
        """GET /chats/{id} — получить чат по owner_external_id + interface.

        Ищет существующий чат, не создаёт новый. Если нет — возвращает None.
        """
        # Ищем через пост (backend должен поддерживать поиск по owner)
        r = await self._make_request(
            "POST",
            "/chats",
            json={
                "owner_external_id": owner_external_id,
                "interface": interface,
                "only_existing": True,
            },
            headers={"X-Owner-External-Id": owner_external_id},
        )
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return UUID(r.json()["chat_id"])  # type: ignore[return-value]

    async def send_message(
        self,
        chat_id: UUID,
        content: str,
        media: bytes | None = None,
        mime: str | None = None,
        filename: str = "file.bin",
        owner_external_id: str | None = None,
    ) -> AsyncIterator[dict]:
        """POST /chats/{id}/messages multipart; парсит SSE, yields dict-события.

        Backend отдаёт поток вида:
            data: {"type":"token","delta":"..."}\\n\\n
            data: {"type":"message_saved","message_id":"..."}\\n\\n
            data: {"type":"done"}\\n\\n

        Этот метод yield-ит ровно то, что пришло (без преобразования), пока
        не встретит `done` — он завершает итерацию (не yield-ится).
        Неизвестные `type` молча игнорируются — для forward compat.

        SSE-запрос с частичной отдачей данных не ретраится (hw.txt требование).
        Retry происходит только при полном подключении к SSE-потоку.
        """
        data = {"content": content}
        files = {"media": (filename, media, mime)} if media is not None else None
        headers = (
            {"X-Owner-External-Id": owner_external_id} if owner_external_id else {}
        )

        # SSE-запрос: retry только на этапе подключения, не в середине стрима
        # Используем отдельную обёртку для stream запроса
        @tenacity.retry(
            stop=tenacity.stop_after_attempt(2),
            wait=tenacity.wait_fixed(3),
            retry=tenacity.retry_if_exception_type((
                httpx.ConnectError,
                httpx.ConnectTimeout,
            )),
        )
        async def _stream_request():
            async with self.http.stream(
                "POST",
                f"/chats/{chat_id}/messages",
                data=data,
                files=files,
                headers=headers,
                timeout=120.0,  # override read timeout для стрима
            ) as r:
                r.raise_for_status()
                async for line in r.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    payload = json.loads(line.removeprefix("data: "))
                    ptype = payload.get("type")
                    if ptype == "done":
                        return
                    if ptype in ("token", "message_saved"):
                        yield payload

        async for event in _stream_request():
            yield event

    async def clear_messages(
        self,
        chat_id: UUID,
        owner_external_id: str | None = None,
    ) -> None:
        headers = (
            {"X-Owner-External-Id": owner_external_id} if owner_external_id else {}
        )
        r = await self._make_request(
            "DELETE",
            f"/chats/{chat_id}/messages",
            headers=headers,
        )
        r.raise_for_status()

    # --- feedback --------------------------------------------------------
    async def post_feedback(
        self,
        chat_id: UUID,
        message_id: str,
        owner_external_id: str,
        value: str,
    ) -> None:
        r = await self._make_request(
            "POST",
            f"/chats/{chat_id}/messages/{message_id}/feedback",
            json={"owner_external_id": owner_external_id, "value": value},
            headers={"X-Owner-External-Id": owner_external_id},
        )
        r.raise_for_status()

    # --- handoff --------------------------------------------------------
    async def set_handoff_status(
        self,
        owner_external_id: str,
        interface: str,
        status: str,
    ) -> None:
        """POST /notify — уведомить backend о handoff статусе.

        Backend отправит подтверждение через POST /notify внутри handoff-route.
        """
        r = await self._make_request(
            "POST",
            "/notify",
            json={
                "owner_external_id": owner_external_id,
                "interface": interface,
                "status": status,
            },
            headers={"X-Owner-External-Id": owner_external_id},
        )
        r.raise_for_status()

    # --- lifecycle -------------------------------------------------------
    async def aclose(self) -> None:
        await self.http.aclose()
