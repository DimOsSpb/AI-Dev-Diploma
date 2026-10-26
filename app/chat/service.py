"""ChatService — оркестратор: прогон сообщения через агентный LangGraph-граф.

`send_message` принимает опциональное `media: UploadFile`. История чата
хранится в `ChatRepository` (для UI/фидбека), а контекст для LLM и
промежуточное состояние (interrupt/draft) — в чекпоинтере графа, ключ
треда — `str(chat_id)`.

Примечание: модерация (ModerationService) существует отдельным сервисом
(`app/moderation/`), но сейчас НЕ подключена ни в `send_message`, ни в
роуте `app/chat/routes.py::post_message` — это предсуществующий пробел,
не связанный с агентным рефакторингом; при необходимости подключить —
вызывать `check_input(...)` в route handler ДО старта `StreamingResponse`
(после старта SSE 403 уже не отдать).

SSE-контракт (расширенный агентным слоем, см. `app/chat/routes.py`):
    {"type":"token","delta":"..."}          — токен ответа модели
    {"type":"tool_call","name":...,"args":...}     — агент вызвал инструмент
    {"type":"tool_result","name":...,"result":...} — результат инструмента
    {"type":"interrupt","payload":{...}}    — опасное действие ждёт подтверждения
    {"type":"error","message":"..."}        — сбой агентного стрима (граф упал)
    {"type":"message_saved","message_id":"<uuid>"}
    {"type":"done"}
"""

import logging
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

from fastapi import UploadFile
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command

from app.chat.domain import Chat, ChatMessage
from app.chat.media import media_to_part
from app.chat.repository import ChatRepository
from app.prompts.builder import build_agent_system_prompt

logger = logging.getLogger("llm-service.chat")


def _agent_config(thread_id: str, user_role: str = "write-with-approve") -> dict:
    return {"configurable": {"thread_id": thread_id, "user_role": user_role}}


def _agent_initial_state(message: str) -> dict:
    # Chat-шаблон модели на llama.cpp не генерирует парсер для tool-calling,
    # если в истории присутствует отдельное SystemMessage (ошибка 400:
    # "System message must be at the beginning" даже когда оно и так первое
    # и единственное — проблема в Jinja-шаблоне конкретной сборки, не в
    # порядке сообщений). Поэтому системная инструкция склеивается с первым
    # HumanMessage вместо отдельного SystemMessage.
    combined = f"{build_agent_system_prompt()}\n\n---\n\n{message}"
    return {
        "messages": [HumanMessage(combined)],
        "iteration_count": 0,
        "tool_results": [],
        "draft": None,
        "sent": False,
    }


class ChatService:
    def __init__(
        self,
        repository: ChatRepository,
        llm_client,
        rag_service=None,
        agent_graph: Any = None,
        context_window: int = 10,
        default_model: str = "gpt-4o-mini",
    ):
        self.repository = repository
        self.llm_client = llm_client
        self.rag_service = rag_service
        self.agent_graph = agent_graph
        self.context_window = context_window
        self.default_model = default_model

    async def create_chat(
        self,
        owner_external_id: str,
        interface: str,
        system_prompt: str | None = None,
    ) -> Chat:
        return await self.repository.create_chat(
            owner_external_id=owner_external_id,
            interface=interface,
            system_prompt=system_prompt,
        )

    async def get_or_create_chat(
        self,
        owner_external_id: str,
        interface: str,
        system_prompt: str | None = None,
    ) -> Chat:
        """Идемпотентная фабрика чата. system_prompt применяется только при
        создании; если чат уже существует — параметр игнорируется."""
        return await self.repository.get_or_create_chat(
            owner_external_id=owner_external_id,
            interface=interface,
        )

    async def get_chat(self, chat_id: UUID) -> Chat | None:
        return await self.repository.get_chat(chat_id)

    async def list_messages(self, chat_id: UUID, limit: int = 50) -> list[ChatMessage]:
        return await self.repository.list_messages(chat_id, limit=limit)

    async def clear_history(self, chat_id: UUID) -> None:
        """Soft delete истории чата (для UI) + сброс состояния агентного треда.

        Без второго шага у агента в чекпоинтере LangGraph оставалась бы вся
        прежняя история `messages` (включая, например, устаревший системный
        контекст или зацикленные tool-call) — команда `/clear` в боте выглядела
        бы работающей, но следующий запрос всё равно падал бы с той же ошибкой.
        """
        await self.repository.soft_delete_messages(chat_id)
        if self.agent_graph is not None:
            checkpointer = getattr(self.agent_graph, "checkpointer", None)
            if checkpointer is not None:
                try:
                    await checkpointer.adelete_thread(str(chat_id))
                except Exception:
                    logger.exception(
                        "не удалось сбросить состояние агента chat_id=%s", chat_id
                    )

    @staticmethod
    def _message_content_for_llm(m: ChatMessage) -> str | list[dict]:
        """Возвращает content в формате OpenAI Chat Completions.

        Если у сообщения есть `media_refs.part`, content становится
        `[text-part, media-part]` (text-part только если content не пустой).
        Иначе — обычная строка.
        """
        media_part = None
        if m.media_refs and isinstance(m.media_refs, dict):
            media_part = m.media_refs.get("part")
        if media_part is None:
            return m.content
        parts: list[dict] = []
        if m.content:
            parts.append({"type": "text", "text": m.content})
        parts.append(media_part)
        return parts

    def _build_context(
        self,
        chat: Chat,
        history: list[ChatMessage],
        system_prompt_body: str | None = None,
    ) -> list[dict]:
        """Sliding window: system_prompt + последние N сообщений.

        system_prompt берётся в порядке приоритета:
        1) явный параметр (A/B выбранный вариант), либо
        2) chat.system_prompt (исторический per-chat), либо
        3) нет system-сообщения вовсе.
        """
        messages: list[dict] = []
        effective_prompt = system_prompt_body or chat.system_prompt
        if effective_prompt:
            messages.append({"role": "system", "content": effective_prompt})
        for m in history:
            messages.append({
                "role": m.role,
                "content": self._message_content_for_llm(m),
            })
        return messages

    @staticmethod
    def _format_agent_events(stream_type: str, payload: Any) -> list[dict]:
        """Мапит событие `agent_graph.astream(..., stream_mode=["updates","messages"])`
        в список SSE-кадров чата (один update-кадр может нести несколько
        tool_calls/tool_results одновременно — поэтому возвращаем список, а
        не одно событие). См. `app/routers/agent.py::_format_event` — тот же
        принцип, здесь дополнительно разворачиваем tool_call/tool_result."""
        if stream_type == "updates":
            if not isinstance(payload, dict):
                return []
            if "__interrupt__" in payload:
                interrupts = payload["__interrupt__"]
                value = interrupts[0].value if interrupts else {}
                return [{"type": "interrupt", "payload": value}]
            # payload: {node_name: node_output_dict}
            events: list[dict] = []
            for node_output in payload.values():
                if not isinstance(node_output, dict):
                    continue
                for msg in node_output.get("messages", []):
                    if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
                        for call in msg.tool_calls:
                            events.append({
                                "type": "tool_call",
                                "name": call["name"],
                                "args": call.get("args", {}),
                            })
                for result in node_output.get("tool_results", []):
                    events.append({
                        "type": "tool_result",
                        "name": result.get("name", ""),
                        "result": result.get("result", ""),
                    })
            return events
        if stream_type == "messages":
            chunk, _meta = payload
            text = getattr(chunk, "content", "")
            return [{"type": "token", "delta": text}] if text else []
        return []

    async def send_message(
        self,
        chat_id: UUID,
        user_content: str,
        media: UploadFile | None = None,
        user_role: str = "write-with-approve",
    ) -> AsyncIterator[dict]:
        """Прогоняет сообщение пользователя через агентный граф (`thread_id` =
        `str(chat_id)`), стримит токены ответа и события инструментов.

        Yields структурированные события — см. docstring модуля. Финальный
        `{"type":"done"}` добавляется в route handler.

        Шаги:
        1. Если media передан — собрать content-part через media_to_part.
        2. Сохранить user-сообщение в ChatRepository (для истории/UI).
        3. Если agent_graph не инициализирован — fallback на RAG/голый LLM
           (на случай локальной разработки без агентного слоя).
        4. Прогнать agent_graph.astream с input={"messages": [HumanMessage]},
           thread_id=chat_id. Проксировать token/tool_call/tool_result/interrupt.
        5. Накопленный текст финального ответа — сохранить как assistant-сообщение.
        """
        media_refs: dict | None = None
        if media is not None:
            mime = media.content_type or ""
            filename = media.filename
            size = getattr(media, "size", None)
            part = await media_to_part(media, self.llm_client)
            media_refs = {
                "mime": mime,
                "size": size,
                "filename": filename,
                "part": part,
            }

        chat = await self.repository.get_chat(chat_id)
        if chat is None:
            raise ValueError(f"chat {chat_id} not found")

        user_message = ChatMessage(
            chat_id=chat_id,
            role="user",
            content=user_content,
            media_refs=media_refs,
        )
        await self.repository.append_message(chat_id, user_message)

        if self.agent_graph is not None:
            async for event in self._run_agent(chat_id, user_content, user_role):
                yield event
            return

        # --- Fallback: агентный граф не поднят (нет ключа/модели) -----------
        history = await self.repository.list_messages(
            chat_id, limit=self.context_window
        )
        messages = self._build_context(chat, history)
        buffer = ""
        if self.rag_service is not None:
            async for event in self.rag_service.answer(user_content):
                if event["type"] == "token":
                    buffer += event["delta"]
                    yield {"type": "token", "delta": event["delta"]}
                elif event["type"] in ("message_saved", "sources"):
                    yield event
                elif event["type"] == "done":
                    yield {"type": "done"}
                    break
            if buffer:
                await self.repository.append_message(
                    chat_id,
                    ChatMessage(chat_id=chat_id, role="assistant", content=buffer),
                )
            return

        stream = await self.llm_client.chat.completions.create(
            model=self.default_model,
            messages=messages,
            stream=True,
            stream_options={"include_usage": True},
        )
        try:
            async for chunk in stream:
                if not getattr(chunk, "choices", None):
                    continue
                delta = chunk.choices[0].delta
                content = getattr(delta, "content", None)
                if content:
                    buffer += content
                    yield {"type": "token", "delta": content}
        except Exception as exc:
            logger.warning(
                "stream interrupted chat_id=%s err=%s saved_chars=%d",
                chat_id,
                exc,
                len(buffer),
            )
            if buffer:
                saved = await self.repository.append_message(
                    chat_id,
                    ChatMessage(chat_id=chat_id, role="assistant", content=buffer),
                )
                yield {"type": "message_saved", "message_id": str(saved.id)}
            yield {"type": "done"}
            raise

        if buffer:
            saved = await self.repository.append_message(
                chat_id,
                ChatMessage(chat_id=chat_id, role="assistant", content=buffer),
            )
            yield {"type": "message_saved", "message_id": str(saved.id)}

    async def _consume_agent_stream(
        self, chat_id: UUID, graph_input: Any, config: dict
    ) -> AsyncIterator[dict]:
        """Общая часть прогона графа для `_run_agent` и `resume`.

        При ошибке внутри `astream` (например, инструмент упал с
        исключением) накопленный буфер (если был) сохраняется как
        assistant-сообщение, и клиенту отдаётся `error`-кадр вместо разрыва
        SSE-соединения.
        """
        buffer = ""
        interrupted = False
        try:
            async for stream_type, payload in self.agent_graph.astream(
                graph_input, config, stream_mode=["updates", "messages"]
            ):
                for event in self._format_agent_events(stream_type, payload):
                    if event["type"] == "token":
                        buffer += event["delta"]
                    if event["type"] == "interrupt":
                        interrupted = True
                    yield event
        except Exception as exc:
            logger.exception("agent stream failed chat_id=%s err=%s", chat_id, exc)
            if buffer:
                saved = await self.repository.append_message(
                    chat_id,
                    ChatMessage(chat_id=chat_id, role="assistant", content=buffer),
                )
                yield {"type": "message_saved", "message_id": str(saved.id)}
            yield {
                "type": "error",
                "message": (
                    "сервис модели временно недоступен (после повторной попытки). "
                    "Попробуйте повторить запрос через минуту — диалог сохранён."
                ),
            }
            return

        if interrupted:
            # Ждём подтверждения через resume() — ответ ещё не финален,
            # assistant-сообщение сохранится после resume.
            return

        if buffer:
            saved = await self.repository.append_message(
                chat_id,
                ChatMessage(chat_id=chat_id, role="assistant", content=buffer),
            )
            yield {"type": "message_saved", "message_id": str(saved.id)}

    async def _run_agent(
        self, chat_id: UUID, user_content: str, user_role: str
    ) -> AsyncIterator[dict]:
        """Запуск графа с новым сообщением пользователя."""
        config = _agent_config(str(chat_id), user_role)
        async for event in self._consume_agent_stream(
            chat_id, _agent_initial_state(user_content), config
        ):
            yield event

    async def resume(
        self,
        chat_id: UUID,
        decision: bool | str,
        user_role: str = "write-with-approve",
    ) -> AsyncIterator[dict]:
        """Возобновляет граф после HIL-подтверждения (кнопка в боте).

        `thread_id` = `str(chat_id)` — тот же тред, что и в `send_message`.
        """
        if self.agent_graph is None:
            raise ValueError("agent_graph не инициализирован")

        config = _agent_config(str(chat_id), user_role)
        async for event in self._consume_agent_stream(
            chat_id, Command(resume=decision), config
        ):
            yield event
