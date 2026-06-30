from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, model_validator


class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: Annotated[str, Field(min_length=1, max_length=100_000)]


class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    @classmethod
    def from_openai(cls, u) -> "Usage":
        return cls(
            prompt_tokens=getattr(u, "prompt_tokens", 0),
            completion_tokens=getattr(u, "completion_tokens", 0),
            total_tokens=getattr(u, "total_tokens", 0),
        )


class ChatRequest(BaseModel):
    messages: Annotated[list[Message], Field(min_length=1, max_length=50)]
    temperature: Annotated[float, Field(ge=0.0, le=2.0)] = 0.2
    max_tokens: Annotated[int, Field(ge=1, le=16_000)] = 2024
    max_completion_tokens: Annotated[int, Field(ge=1, le=16_000)] = 2024
    model: str | None = None
    stream: bool = False
    user_id: str | None = None
    session_id: str | None = None
    extra_body: dict[str, Any] | None = Field(
        default_factory=lambda: {
            "thinking_budget_tokens": 0,  # лимит на "мысли"
            "chat_template_kwargs": {
                "enable_thinking": False  # Инструкция для JINJA-шаблона Qwen
            },
        },
        description="Кастомные параметры для движка llama.cpp, отключающие Thinking Mode",
    )
    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "messages": [
                        {
                            "role": "system",
                            "content": "Ты опытный ассистент",
                        },
                        {
                            "role": "user",
                            "content": "Какой порт у pve на ui?",
                        },
                    ],
                    "temperature": 0,
                    "max_tokens": 50,
                },
            ]
        }
    }

    @model_validator(mode="after")
    def _first_message_not_assistant(self) -> "ChatRequest":
        if self.messages[0].role == "assistant":
            raise ValueError("Первое сообщение не может быть от assistant")
        return self


class ChatResponse(BaseModel):
    content: str
    model: str
    usage: Usage
    finish_reason: str | None = None
    cached: bool = False
    request_id: str | None = None

    @classmethod
    def from_openai(cls, raw) -> "ChatResponse":
        # print(f"DEBUG RAW OBJECT: {raw}")
        choice = raw.choices[0]
        return cls(
            content=choice.message.content or "",
            model=raw.model,
            usage=Usage.from_openai(raw.usage),
            finish_reason=choice.finish_reason,
        )


class ChatDelta(BaseModel):
    content: str | None = None
    usage: Usage | None = None
