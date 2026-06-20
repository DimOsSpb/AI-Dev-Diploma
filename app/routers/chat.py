import app.prompts.loader as loader
from app.core.config import Settings
from app.schemas.chat import ChatRequest
from app.services.llm import LLMClient
from fastapi import APIRouter
from sse_starlette import EventSourceResponse

router = APIRouter(prefix="/chat", tags=["chat"])

settings = Settings()

client = LLMClient(settings)


@router.post("")
async def chat(req: ChatRequest):

    messages = loader.build_answer_messages(
        loader.build_system_prompt("InfraAssist"),
        [],
        req.prompt,
    )

    result = await client.complete(messages)

    return {
        "answer": result.text,
    }


@router.post("/stream")
async def chat_stream(req: ChatRequest):

    messages = loader.build_answer_messages(
        loader.build_system_prompt("InfraAssist"),
        [],
        req.prompt,
    )

    async def event_generator():

        async for token in client.stream_chat(messages):
            yield token

    return EventSourceResponse(event_generator())
