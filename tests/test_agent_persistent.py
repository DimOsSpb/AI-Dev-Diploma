"""Тесты персистентного агента с HIL на фейковой модели и sqlite in-memory.

Без сети, без Postgres: `AsyncSqliteSaver.from_conn_string(":memory:")` достаточно.
"""

from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command

from app.agents.tools_proxmox import pve_create_snapshot
from app.services.agent_persistent import build_agent


class FakeChat:
    """Заглушка ChatModel: отдаёт заготовленную последовательность ответов."""

    def __init__(self, responses: list[AIMessage]) -> None:
        self._responses = responses
        self._i = 0

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        response = self._responses[min(self._i, len(self._responses) - 1)]
        self._i += 1
        return response


def _create_snapshot_call() -> AIMessage:
    return AIMessage(
        content="",
        id="ai-1",
        tool_calls=[
            {
                "name": "pve_create_snapshot",
                "args": {
                    "node": "pve-01",
                    "vmid": 100,
                    "snapshot_name": "demo-snap",
                },
                "id": "call-1",
                "type": "tool_call",
            }
        ],
    )


def _model() -> FakeChat:
    # 1) модель просит pve_create_snapshot → HIL-гейт; 2) после — финальный ответ.
    return FakeChat([_create_snapshot_call(), AIMessage(content="Готово.", id="ai-2")])


def _initial() -> dict:
    return {
        "messages": [HumanMessage("сделай снапшот тестовой VM")],
        "iteration_count": 0,
        "tool_results": [],
        "draft": None,
        "sent": False,
    }


@pytest.mark.asyncio
async def test_graph_reaches_interrupt_before_snapshot():
    create_fn = AsyncMock(return_value="снапшот создан")
    async with AsyncSqliteSaver.from_conn_string(":memory:") as saver:
        await saver.setup()
        graph = build_agent(saver, _model(), [], pve_create_snapshot, create_fn)  # pyright: ignore[reportArgumentType]
        config = {"configurable": {"thread_id": "t-interrupt"}}

        result = await graph.ainvoke(_initial(), config)  # pyright: ignore[reportArgumentType]

        assert "__interrupt__" in result  # граф встал на interrupt
        snapshot = await graph.aget_state(config)  # pyright: ignore[reportArgumentType]
        assert "confirm_and_create_snapshot" in snapshot.next  # ждём узел подтверждения
        create_fn.assert_not_called()  # side-effect ещё не выполнялся


@pytest.mark.asyncio
async def test_resume_true_creates_snapshot():
    create_fn = AsyncMock(return_value="снапшот создан")
    async with AsyncSqliteSaver.from_conn_string(":memory:") as saver:
        await saver.setup()
        graph = build_agent(saver, _model(), [], pve_create_snapshot, create_fn)  # pyright: ignore[reportArgumentType]
        config = {"configurable": {"thread_id": "t-approve"}}

        await graph.ainvoke(_initial(), config)  # pyright: ignore[reportArgumentType]
        final = await graph.ainvoke(Command(resume=True), config)  # pyright: ignore[reportArgumentType]

        assert final["sent"] is True
        create_fn.assert_awaited_once()
        assert create_fn.await_args.args[0]["snapshot_name"] == "demo-snap"  # pyright: ignore[reportOptionalMemberAccess]


@pytest.mark.asyncio
async def test_resume_false_does_not_create_snapshot():
    create_fn = AsyncMock(return_value="снапшот создан")
    async with AsyncSqliteSaver.from_conn_string(":memory:") as saver:
        await saver.setup()
        graph = build_agent(saver, _model(), [], pve_create_snapshot, create_fn)  # pyright: ignore[reportArgumentType]
        config = {"configurable": {"thread_id": "t-reject"}}

        await graph.ainvoke(_initial(), config)  # pyright: ignore[reportArgumentType]
        final = await graph.ainvoke(Command(resume=False), config)  # pyright: ignore[reportArgumentType]

        assert final["sent"] is False
        create_fn.assert_not_called()  # отказ — реального вызова API нет


@pytest.mark.asyncio
async def test_role_full_skips_interrupt():
    # Роль full: узел подтверждения не поднимает interrupt, снапшот создаётся сразу.
    create_fn = AsyncMock(return_value="снапшот создан")
    async with AsyncSqliteSaver.from_conn_string(":memory:") as saver:
        await saver.setup()
        graph = build_agent(saver, _model(), [], pve_create_snapshot, create_fn)  # pyright: ignore[reportArgumentType]
        config = {"configurable": {"thread_id": "t-full", "user_role": "full"}}

        result = await graph.ainvoke(_initial(), config)  # pyright: ignore[reportArgumentType]

        assert "__interrupt__" not in result
        assert result["sent"] is True
        create_fn.assert_awaited_once()
