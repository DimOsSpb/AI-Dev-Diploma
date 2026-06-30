import json
from typing import Any

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.deps.providers import LLMServiceDep
from app.schemas.chat import ChatRequest, ChatResponse

router = APIRouter(prefix="/chat", tags=["chat"])

RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {"description": "Успешный ответ"},
    422: {"description": "Ошибка валидации"},
    429: {"description": "Rate limit"},
    502: {"description": "Ошибка провайдера"},
    504: {"description": "Таймаут провайдера"},
}


@router.post(
    "",
    response_model=ChatResponse,
    summary="Синхронный чат",
    description="Отправляет сообщения в LLM и возвращает полный ответ.",
    responses=RESPONSES,
    name="chat_completions",
)
async def chat_completions(req: ChatRequest, service: LLMServiceDep) -> ChatResponse:
    return await service.complete(req)


@router.post("/stream", summary="Streaming чат через SSE", responses=RESPONSES)
async def chat_stream(req: ChatRequest, service: LLMServiceDep):
    async def event_source():
        async for delta in service.stream(req):
            if delta.content:
                yield f"data: {delta.content}\n\n"

            elif delta.usage:
                payload = {"usage": json.dumps(delta.usage.model_dump())}
                yield f"data: {payload}\n\n"

        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )
