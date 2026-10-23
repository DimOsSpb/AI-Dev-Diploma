"""Ручка агентного слоя: прогон ReAct-графа по одному сообщению."""

from fastapi import APIRouter, HTTPException
from langchain_core.messages import HumanMessage
from pydantic import BaseModel

from app.deps.providers import AgentGraphDep

router = APIRouter(prefix="/agent", tags=["agent"])


class AgentChatRequest(BaseModel):
    message: str


class AgentChatResponse(BaseModel):
    answer: str
    tool_results: list[dict]


@router.post("/chat", response_model=AgentChatResponse)
async def agent_chat(req: AgentChatRequest, graph: AgentGraphDep) -> AgentChatResponse:
    if graph is None:
        raise HTTPException(status_code=503, detail="агентный граф не инициализирован")
    result = await graph.ainvoke({
        "messages": [HumanMessage(req.message)],
        "iteration_count": 0,
        "tool_results": [],
    })
    final = result["messages"][-1]
    return AgentChatResponse(
        answer=final.content or "",
        tool_results=result.get("tool_results", []),
    )
