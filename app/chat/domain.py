"""Доменные модели чата.

Чистые Pydantic v2-модели — никаких импортов из SQLAlchemy / FastAPI / aiofiles.
Граница между доменом и инфраструктурой проходит через ORM-границу
(`ChatMessage.model_validate(row, from_attributes=True)`).
"""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

Role = Literal["user", "assistant", "system"]


class ChatMessage(BaseModel):
    """Сообщение внутри чата (доменная модель)."""

    id: UUID = Field(default_factory=uuid4)
    chat_id: UUID
    role: Role
    content: str
    media_refs: dict | None = None
    tokens: int | None = None
    prompt_id: UUID | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Chat(BaseModel):
    """Чат — один диалог одного пользователя с ассистентом."""

    id: UUID = Field(default_factory=uuid4)
    owner_external_id: str
    interface: str
    system_prompt: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
