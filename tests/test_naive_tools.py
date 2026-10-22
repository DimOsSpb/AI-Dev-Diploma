"""Тесты инструментов и согласованности TOOLS/DISPATCH."""

from datetime import datetime
from zoneinfo import ZoneInfoNotFoundError

import pytest

from app.tools.naive_tools import (
    DISPATCH,
    TOOLS,
    get_current_time,
    search_knowledge_base,
    send_telegram_message,
)


def test_search_knowledge_base_hit():
    assert "14 дней" in search_knowledge_base("Какие правила ВОЗВРАТА?")


def test_search_knowledge_base_miss():
    assert search_knowledge_base("курс доллара") == "По запросу ничего не найдено."


def test_get_current_time_returns_iso_with_timezone():
    value = get_current_time("Europe/Moscow")
    parsed = datetime.fromisoformat(value)
    assert parsed.tzinfo is not None


def test_get_current_time_invalid_timezone_raises():
    with pytest.raises(ZoneInfoNotFoundError):
        get_current_time("Mars/Phobos")


def test_send_telegram_message_prints_and_confirms(capsys):
    result = send_telegram_message("12345", "Здравствуйте!")
    captured = capsys.readouterr()
    assert "[TELEGRAM → 12345]" in captured.out
    assert result == "Сообщение отправлено в 12345"


def test_dispatch_matches_tools_schema():
    schema_names = {tool["function"]["name"] for tool in TOOLS}
    assert schema_names == set(DISPATCH)


def test_every_tool_description_has_at_least_two_sentences():
    for tool in TOOLS:
        description = tool["function"]["description"]
        assert description.count(".") >= 2, tool["function"]["name"]
