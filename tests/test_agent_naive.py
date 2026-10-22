"""Тесты наивного агента: happy path и три классических режима сбоя."""

from app.services import agent_naive
from app.services.agent_naive import run_agent
from tests.conftest import FakeClient, make_message, make_response, make_tool_call

_TRACE_FIELDS = {
    "step",
    "tool_name",
    "tool_args",
    "tool_result",
    "llm_input_tokens",
    "llm_output_tokens",
    "duration_ms",
}


def test_happy_path_tool_then_answer():
    client = FakeClient(
        [
            make_response(
                make_message(
                    tool_calls=[
                        make_tool_call("c1", "search_knowledge_base", '{"query": "возврат"}')
                    ]
                )
            ),
            make_response(make_message(content="Возврат возможен в течение 14 дней.")),
        ]
    )

    result = run_agent("Какие правила возврата?", client=client)

    assert result["answer"] == "Возврат возможен в течение 14 дней."
    assert result["steps"] == 2
    assert "error" not in result
    assert len(result["trace"]) == 2
    first, last = result["trace"]
    assert first["tool_name"] == "search_knowledge_base"
    assert "14 дней" in first["tool_result"]
    assert first["llm_input_tokens"] == 12 and first["llm_output_tokens"] == 7
    assert last["tool_name"] is None and last["tool_result"].startswith("Возврат")
    # каждый шаг логируется одним и тем же набором полей
    for entry in result["trace"]:
        assert set(entry) == _TRACE_FIELDS


def test_hallucinated_tool_is_reported_not_crashed():
    client = FakeClient(
        [
            make_response(
                make_message(
                    tool_calls=[make_tool_call("c1", "get_user_balance", '{"user_id": "42"}')]
                )
            ),
            make_response(make_message(content="Такого инструмента нет, помогу иначе.")),
        ]
    )

    result = run_agent("Проверь баланс пользователя 42", client=client)

    assert result["answer"] == "Такого инструмента нет, помогу иначе."
    hallucinated = result["trace"][0]
    assert hallucinated["tool_name"] == "get_user_balance"
    assert hallucinated["tool_result"].startswith(
        "Ошибка: инструмент 'get_user_balance' недоступен"
    )


def test_max_steps_guardrail_stops_runaway_loop():
    looping_call = make_tool_call("c1", "search_knowledge_base", '{"query": "нет данных"}')
    client = FakeClient([make_response(make_message(tool_calls=[looping_call])) for _ in range(3)])

    result = run_agent("Найди несуществующую политику", max_steps=3, client=client)

    assert result["answer"] is None
    assert result["error"] == "max_steps"
    assert result["steps"] == 3
    assert len(result["trace"]) == 3


def test_tool_exception_is_caught_and_returned():
    client = FakeClient(
        [
            make_response(
                make_message(
                    tool_calls=[
                        make_tool_call("c1", "get_current_time", '{"timezone": "Mars/Phobos"}')
                    ]
                )
            ),
            make_response(make_message(content="Не удалось определить время.")),
        ]
    )

    result = run_agent("Сколько времени на Фобосе?", client=client)

    assert result["trace"][0]["tool_result"].startswith("Ошибка инструмента:")
    assert result["answer"] == "Не удалось определить время."


def test_parallel_tool_calls_in_one_step_make_two_trace_entries():
    client = FakeClient(
        [
            make_response(
                make_message(
                    tool_calls=[
                        make_tool_call("c1", "search_knowledge_base", '{"query": "доставка"}'),
                        make_tool_call("c2", "get_current_time", "{}"),
                    ]
                )
            ),
            make_response(make_message(content="Готово.")),
        ]
    )

    result = run_agent("Сроки доставки и текущее время", client=client)

    step_zero = [e for e in result["trace"] if e["step"] == 0]
    assert len(step_zero) == 2
    assert {e["tool_name"] for e in step_zero} == {"search_knowledge_base", "get_current_time"}


def test_main_prints_answer_and_returns_zero(monkeypatch, capsys):
    monkeypatch.setattr(
        agent_naive,
        "run_agent",
        lambda task, max_steps, model: {"answer": "готовый ответ", "steps": 1, "trace": []},
    )

    code = agent_naive.main(["Привет"])

    assert code == 0
    assert "готовый ответ" in capsys.readouterr().out


def test_main_reports_error_and_prints_trace(monkeypatch, capsys):
    entry = {"step": 0, "tool_name": "search_knowledge_base"}
    monkeypatch.setattr(
        agent_naive,
        "run_agent",
        lambda task, max_steps, model: {
            "answer": None,
            "steps": 6,
            "trace": [entry],
            "error": "max_steps",
        },
    )

    code = agent_naive.main(["задача", "--trace"])

    out = capsys.readouterr().out
    assert code == 0
    assert "max_steps" in out
    assert "search_knowledge_base" in out
