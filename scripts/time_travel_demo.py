"""Персистентность и путешествие во времени на одном сценарии.

Офлайн: фейковая модель и sqlite in-memory, без сети и без Postgres. Показывает:
1) остановку графа на interrupt перед опасным действием;
2) историю чек-пойнтов (`aget_state_history`);
3) чтение состояния на прошлом чек-пойнте (time-travel read);
4) две ветки из одинакового входа — отказ и одобрение создания снапшота.

    uv run python -m scripts.time_travel_demo
"""

import asyncio
import sys
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agents.tools_proxmox import pve_create_snapshot
from app.services.agent_persistent import build_agent


class FakeChat:
    """Content-aware заглушка: пока нет результата инструмента — просит
    pve_create_snapshot, после — финализирует. Устойчива к перезапуску узла
    при resume."""

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        if any(getattr(m, "type", "") == "tool" for m in messages):
            return AIMessage(content="Готово, снапшот обработан.", id="ai-final")
        return AIMessage(
            content="",
            id="ai-snapshot",
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


def _initial() -> dict:
    return {
        "messages": [HumanMessage("сделай снапшот тестовой VM")],
        "iteration_count": 0,
        "tool_results": [],
        "draft": None,
        "sent": False,
    }


async def main() -> None:
    created_log: list[dict] = []

    async def create_fn(draft: dict) -> str:
        created_log.append(draft)
        return f"снапшот '{draft['snapshot_name']}' создан"

    async with AsyncSqliteSaver.from_conn_string(":memory:") as saver:
        await saver.setup()
        graph = build_agent(saver, FakeChat(), [], pve_create_snapshot, create_fn)  # pyright: ignore[reportArgumentType]
        role = "write-with-approve"
        config = {"configurable": {"thread_id": "demo", "user_role": role}}

        result = await graph.ainvoke(_initial(), config)  # pyright: ignore[reportArgumentType]
        print("1) INTERRUPT payload:", result["__interrupt__"][0].value)

        print("2) история чек-пойнтов (checkpoint_id / next / ключи state):")
        pre_interrupt_id: str | None = None
        async for snap in graph.aget_state_history(config):  # pyright: ignore[reportArgumentType]
            cid = snap.config["configurable"]["checkpoint_id"]  # pyright: ignore[reportTypedDictNotRequiredAccess]
            print(f"   {cid}  next={snap.next}")
            if (
                snap.next == ("confirm_and_create_snapshot",)
                and pre_interrupt_id is None
            ):
                pre_interrupt_id = cid

        past = await graph.aget_state({
            "configurable": {"thread_id": "demo", "checkpoint_id": pre_interrupt_id}
        })
        print(
            "3) чтение прошлого чек-пойнта: "
            f"sent={past.values['sent']}, draft_готов={past.values['draft'] is not None}, "
            f"next={past.next}"
        )

        # 4) две ветки из ОДИНАКОВОГО входа: отказ на основном треде, одобрение — на
        # альтернативном (resume хранится в чек-пойнтере детерминированно на тред).
        rejected = await graph.ainvoke(Command(resume=False), config)  # pyright: ignore[reportArgumentType]
        alt = {"configurable": {"thread_id": "demo-alt", "user_role": role}}
        await graph.ainvoke(_initial(), alt)  # pyright: ignore[reportArgumentType]
        approved = await graph.ainvoke(Command(resume=True), alt)  # pyright: ignore[reportArgumentType]
        print(
            f"4) две ветки: отказ → sent={rejected['sent']}, "
            f"одобрение → sent={approved['sent']}, снапшотов_создано={len(created_log)}"
        )
        print(
            "Итог: один и тот же вход дал две ветки — отказ (sent=False) и одобрение (sent=True)."
        )


if __name__ == "__main__":
    asyncio.run(main())
