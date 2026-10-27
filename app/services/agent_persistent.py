"""Персистентный ReAct-агент: чекпоинтер + человек в цикле на опасном действии.

Инкремент к базовому ReAct-агенту: тот же цикл, но граф компилируется с
чекпоинтером (состояние переживает рестарт), а опасный инструмент
`pve_create_snapshot` (создание снапшота VM в Proxmox) проходит через
человека — два узла:

- `prepare_snapshot` — idempotent: рендерит payload снапшота из tool_call,
  без side-effect;
- `confirm_and_create_snapshot` — `interrupt()` перед вызовом Proxmox API,
  реальный вызов ТОЛЬКО после `Command(resume=...)`. При роли `full`
  interrupt пропускается (политика доступа).

Бэкенд чекпоинтера выбирается через `AGENT_CHECKPOINTER`: `memory` | `sqlite` |
`postgres`. Схему чекпоинтера ведёт `setup()`, доменную — Alembic (в `env.py`
таблицы `checkpoint*` исключены из autogenerate через `include_name`).
"""

import asyncio
import operator
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated, Any, Literal, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AnyMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import interrupt

MAX_ITERATIONS = 6
DANGEROUS_TOOL = "pve_create_snapshot"
# Поведение при сбоях LLM-эндпоинта: одна повторная попытка на сетевые/таймаут
# ошибки, затем дать упасть выше — там _consume_agent_stream превратит это в
# понятное пользователю сообщение (см. app/chat/service.py).
LLM_CALL_RETRIES = 1
LLM_RETRY_DELAY_SECONDS = 1.5

# Реальный side-effect создания снапшота: async-callable, инжектируется в
# фабрику, чтобы в тестах подменяться моком и вызываться ТОЛЬКО после
# одобрения человеком. Возвращает текст результата (успех/ошибка).
CreateSnapshotFn = Callable[[dict], Awaitable[str]]


class PersistentAgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    iteration_count: int
    tool_results: Annotated[list[dict], operator.add]
    draft: dict | None  # payload снапшота, подготовленный prepare_snapshot
    sent: bool  # выполнен ли side-effect (снапшот создан)


def _find_call(message: AnyMessage, name: str) -> dict:
    for call in message.tool_calls:  # pyright: ignore[reportAttributeAccessIssue]
        if call["name"] == name:
            return call  # pyright: ignore[reportReturnType]
    raise ValueError(f"в сообщении нет tool_call {name!r}")


def build_agent(
    checkpointer: Any,
    model: BaseChatModel,
    tools: list[BaseTool],
    dangerous_tool: BaseTool,
    create_snapshot_fn: CreateSnapshotFn,
):
    """Компилирует персистентный ReAct-граф с HIL-гейтом на `pve_create_snapshot`.

    `tools` — безопасные инструменты (search_knowledge_base, pve_status).
    `dangerous_tool` (`pve_create_snapshot`) добавляется здесь и исполняется
    не в `execute_tool`, а через отдельную ветку с `interrupt`.
    """
    bound_model = model.bind_tools([*tools, dangerous_tool])
    tool_by_name = {t.name: t for t in tools}

    async def call_model(state: PersistentAgentState) -> dict:
        last_exc: Exception | None = None
        for attempt in range(LLM_CALL_RETRIES + 1):
            try:
                response = await bound_model.ainvoke(state["messages"])
                break
            except Exception as exc:  # сетевые/таймаут-сбои LLM-эндпоинта
                last_exc = exc
                if attempt < LLM_CALL_RETRIES:
                    await asyncio.sleep(LLM_RETRY_DELAY_SECONDS)
                    continue
                raise
        else:  # pragma: no cover - недостижимо, цикл либо break, либо raise
            raise last_exc  # type: ignore[misc]
        return {
            "messages": [response],
            "iteration_count": state["iteration_count"] + 1,
        }

    async def execute_tool(state: PersistentAgentState) -> dict:
        last = state["messages"][-1]
        messages: list = []
        results: list[dict] = []
        for call in last.tool_calls:  # pyright: ignore[reportAttributeAccessIssue]
            if call["name"] == DANGEROUS_TOOL:
                continue  # опасный инструмент идёт через HIL-ветку, не здесь
            if call["name"] not in tool_by_name:
                content = f"error: unknown tool '{call['name']}'"
            else:
                content = str(await tool_by_name[call["name"]].ainvoke(call["args"]))
            messages.append(ToolMessage(content=content, tool_call_id=call["id"]))
            results.append({
                "name": call["name"],
                "args": call["args"],
                "result": content,
            })
        return {"messages": messages, "tool_results": results}

    async def prepare_snapshot(state: PersistentAgentState) -> dict:
        """Idempotent: собирает payload снапшота из tool_call. Без side-effect.

        Имя снапшота придумывает LLM и часто повторяет одно и то же имя между
        запросами пользователя. Proxmox API отклоняет создание снапшота с
        именем, которое уже существует на VM, и модель может принять этот
        отказ за успех ("снапшот уже создан"). Чтобы каждый подтверждённый
        запрос гарантированно создавал новый снапшот, сюда добавляется
        временная метка — независимо от того, что предложила модель.
        """
        call = _find_call(state["messages"][-1], DANGEROUS_TOOL)
        args = call["args"]
        base_name = args.get("snapshot_name") or "snap"
        unique_name = f"{base_name}-{datetime.now(UTC):%Y%m%d-%H%M%S}"
        draft = {
            "node": args.get("node", ""),
            "vmid": args.get("vmid", ""),
            "snapshot_name": unique_name,
            "tool_call_id": call["id"],
        }
        return {"draft": draft}

    async def confirm_and_create_snapshot(
        state: PersistentAgentState, config: RunnableConfig
    ) -> dict:
        """interrupt перед вызовом Proxmox API; реальный вызов — ПОСЛЕ resume."""
        draft = state["draft"] or {}
        role = (config.get("configurable") or {}).get("user_role", "write-with-approve")
        if role == "full":
            decision: Any = True  # полный доступ — без подтверждения человека
        else:
            decision = interrupt({"type": "approve_pve_snapshot", "preview": draft})
        approved = decision is True or decision == "approve"
        if approved:
            content = await create_snapshot_fn(draft)  # SIDE-EFFECT после resume
        else:
            content = "создание снапшота отменено пользователем"
        return {
            "sent": approved,
            "messages": [
                ToolMessage(content=content, tool_call_id=draft.get("tool_call_id", ""))
            ],
            "tool_results": [
                {"name": DANGEROUS_TOOL, "args": draft, "result": content}
            ],
        }

    async def force_finish(state: PersistentAgentState) -> dict:
        return {}

    def route_after_model(
        state: PersistentAgentState,
    ) -> Literal["execute_tool", "prepare_snapshot", "force_finish"]:
        if state["iteration_count"] >= MAX_ITERATIONS:
            return "force_finish"
        last = state["messages"][-1]
        calls = getattr(last, "tool_calls", None)
        if not calls:
            return "force_finish"
        if any(call["name"] == DANGEROUS_TOOL for call in calls):
            return "prepare_snapshot"
        return "execute_tool"

    builder = StateGraph(PersistentAgentState)
    builder.add_node("call_model", call_model)
    builder.add_node("execute_tool", execute_tool)
    builder.add_node("prepare_snapshot", prepare_snapshot)
    builder.add_node("confirm_and_create_snapshot", confirm_and_create_snapshot)
    builder.add_node("force_finish", force_finish)
    builder.add_edge(START, "call_model")
    builder.add_conditional_edges(
        "call_model",
        route_after_model,
        {
            "execute_tool": "execute_tool",
            "prepare_snapshot": "prepare_snapshot",
            "force_finish": "force_finish",
        },
    )
    builder.add_edge("execute_tool", "call_model")
    builder.add_edge("prepare_snapshot", "confirm_and_create_snapshot")
    builder.add_edge("confirm_and_create_snapshot", "call_model")
    builder.add_edge("force_finish", END)
    return builder.compile(checkpointer=checkpointer)


def _psycopg_uri(database_url: str) -> str:
    """AsyncPostgresSaver работает на psycopg (v3): `postgresql://`, без `+asyncpg`."""
    return database_url.replace("postgresql+asyncpg://", "postgresql://")


@asynccontextmanager
async def agent_lifespan(
    backend: Literal["memory", "sqlite", "postgres"],
    model: BaseChatModel,
    tools: list[BaseTool],
    dangerous_tool: BaseTool,
    create_snapshot_fn: CreateSnapshotFn,
    *,
    sqlite_path: str = "var/agent_checkpoints.sqlite",
    postgres_url: str = "",
) -> AsyncIterator[Any]:
    """Поднимает нужный чекпоинтер и отдаёт скомпилированный граф.

    `setup()` вызывается ровно один раз здесь — не на каждый запрос.
    """
    if backend == "memory":
        # InMemorySaver не требует setup() и живёт в памяти процесса.
        yield build_agent(
            InMemorySaver(), model, tools, dangerous_tool, create_snapshot_fn
        )
    elif backend == "sqlite":
        from pathlib import Path

        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        Path(sqlite_path).parent.mkdir(parents=True, exist_ok=True)
        async with AsyncSqliteSaver.from_conn_string(sqlite_path) as saver:
            await saver.setup()
            yield build_agent(saver, model, tools, dangerous_tool, create_snapshot_fn)
    elif backend == "postgres":
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        async with AsyncPostgresSaver.from_conn_string(
            _psycopg_uri(postgres_url)
        ) as saver:
            await saver.setup()
            yield build_agent(saver, model, tools, dangerous_tool, create_snapshot_fn)
    else:
        raise ValueError(f"неизвестный AGENT_CHECKPOINTER: {backend!r}")
