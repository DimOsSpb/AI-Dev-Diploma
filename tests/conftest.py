from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.deps.providers import get_cache, get_llm
from app.main import app

"""Фейковый клиент OpenAI для тестов без сети.

Повторяет ровно тот контракт, которым пользуется `run_agent`:
`client.chat.completions.create(...)` -> объект с `choices[0].message`
(`.content`, `.tool_calls`) и `.usage` (`.prompt_tokens`, `.completion_tokens`),
а каждый tool call — `.id` и `.function` (`.name`, `.arguments` как JSON-строка).
"""

from types import SimpleNamespace


def _make_openai_response(content: str = "мок-ответ", model: str = "gpt-4o-mini"):
    return MagicMock(
        choices=[
            MagicMock(
                message=MagicMock(content=content),
                finish_reason="stop",
            )
        ],
        model=model,
        usage=MagicMock(prompt_tokens=10, completion_tokens=5, total_tokens=15),
    )


@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    llm.chat.completions.create = AsyncMock(return_value=_make_openai_response())
    return llm


@pytest.fixture
def mock_cache():
    cache = AsyncMock()
    cache.get = AsyncMock(return_value=None)
    cache.setex = AsyncMock(return_value=True)
    cache.ping = AsyncMock(return_value=True)
    return cache


@pytest.fixture
async def client(mock_llm, mock_cache):
    # ASGITransport не запускает lifespan — выставляем app.state вручную,
    # чтобы health/ready, использующие request.app.state, тоже работали.
    app.state.llm = mock_llm
    app.state.redis = mock_cache

    app.dependency_overrides[get_llm] = lambda: mock_llm
    app.dependency_overrides[get_cache] = lambda: mock_cache

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


def make_message(
    content: str | None = None, tool_calls: list | None = None
) -> SimpleNamespace:
    return SimpleNamespace(content=content, tool_calls=tool_calls)


def make_tool_call(call_id: str, name: str, arguments: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=call_id, function=SimpleNamespace(name=name, arguments=arguments)
    )


def make_response(
    message: SimpleNamespace, prompt_tokens: int = 12, completion_tokens: int = 7
) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message)],
        usage=SimpleNamespace(
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens
        ),
    )


class _FakeCompletions:
    def __init__(self, responses: list[SimpleNamespace]) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    def create(self, **kwargs) -> SimpleNamespace:
        self.calls.append(kwargs)
        return self._responses.pop(0)


class FakeClient:
    """Подменяет OpenAI: отдаёт заранее заданные ответы по очереди."""

    def __init__(self, responses: list[SimpleNamespace]) -> None:
        self.chat = SimpleNamespace(completions=_FakeCompletions(responses))
