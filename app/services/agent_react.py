"""Управляемый ReAct-агент с self-reflection и лимитами.

Реализует паттерн ReAct (Reasoning + Acting) с нативным tool calling OpenAI.
Добавляет self-reflection (critic) для предотвращения галлюцинаций и runaway-циклов.
"""

import argparse
import json
import logging
import time
from collections.abc import Callable
from typing import Any

import structlog
from openai import OpenAI

from app.core.ai.catalog import get_catalog
from app.core.config import get_settings
from app.tools.naive_tools import DISPATCH, TOOLS

log = structlog.get_logger(__name__)

_RESULT_PREVIEW_LEN = 200


def run_react_with_reflection(
    question: str,
    tools: list[dict] | None = None,
    tool_dispatch: dict[str, Callable[..., Any]] | None = None,
    max_iterations: int = 10,
    timeout_per_iteration_sec: float = 10.0,
    max_revisions: int = 2,
) -> dict:
    """Запускает ReAct-агент с self-reflection.

    Args:
        question: Запрос пользователя.
        tools: Список tool-описаний для OpenAI Chat Completions.
        tool_dispatch: Словарь dispatch-функций по именам инструментов.
        max_iterations: Максимальное число итераций (по умолчанию 10).
        timeout_per_iteration_sec: Таймаут на одну итерацию (по умолчанию 10 сек).
        max_revisions: Максимальное число ревизий через critic (по умолчанию 2).
        model_main: Модель для основного цикла (по умолчанию gpt-5.4-mini).
        model_critic: Модель для critic (по умолчанию gpt-5.4-mini).

    Returns:
        dict с ответом, трассой и статистикой токенов.
    """
    if tools is None:
        tools = TOOLS
    if tool_dispatch is None:
        tool_dispatch = DISPATCH

    settings = get_settings()
    catalog = get_catalog()

    config = catalog.get_client_config(
        model_name=settings.rag_llm_model,
        endpoint_name=settings.rag_llm_endpoint,
    )

    # Используем llama.cpp сервер
    api_key = "ollama"  # llama.cpp не требует API key

    client = OpenAI(base_url=config.url, api_key=api_key)

    system_prompt = (
        "Действовать как агент: самостоятельно выбирать инструменты и их порядок, "
        "при необходимости разбивая задачу на подзадачи. "
        "На каждом шаге сначала одним предложением пояснять, что и зачем делается, "
        "затем вызывать ровно один инструмент и опираться на его результат. "
        "Как только данных достаточно — дать финальный ответ без вызова инструментов. "
        "Не выдумывать данные: использовать только то, что вернули инструменты; "
        "если доступными инструментами задачу решить нельзя — прямо сообщить об этом."
    )

    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": question},
    ]

    trace: list[dict] = []
    revisions_used = 0
    revision_feedback: str | None = None
    usage_total = {"prompt": 0, "completion": 0, "total": 0}

    for step in range(max_iterations):
        step_start = time.monotonic()

        # Проверка лимита ревизий перед итерацией
        if revisions_used > max_revisions:
            log.warning("превышен лимит ревизий", revisions_used=revisions_used)
            return {
                "answer": "Превышен лимит ревизий",
                "usage": usage_total,
                "steps": step + 1,
                "trace": trace,
                "error": "max_revisions",
            }

        # Проверка, есть ли feedback от предыдущей ревизии
        current_system_prompt = system_prompt
        if revision_feedback:
            current_system_prompt = f"{system_prompt}\n\n{revision_feedback}"

        t0 = time.monotonic()

        try:
            response = client.chat.completions.create(
                model=config.model,
                messages=messages,  # pyright: ignore[reportArgumentType]
                tools=tools,  # pyright: ignore[reportArgumentType]
                tool_choice="auto",
            )
            iteration_latency = time.monotonic() - t0

            if iteration_latency > timeout_per_iteration_sec:
                log.warning("timeout на итерации", step=step, latency=iteration_latency)
                return {
                    "answer": "Timeout",
                    "usage": usage_total,
                    "steps": step + 1,
                    "trace": trace,
                    "error": "timeout",
                }

            usage = response.usage
            if usage:
                usage_total["prompt"] += usage.prompt_tokens
                usage_total["completion"] += usage.completion_tokens
                usage_total["total"] += usage.total_tokens

            message = response.choices[0].message
            messages.append(message)  # pyright: ignore[reportArgumentType]

            # Логирование шага
            step_info = {
                "step": step,
                "iteration_latency_sec": round(iteration_latency, 3),
                "model": config.model,
            }

            if usage:
                step_info["prompt_tokens"] = usage.prompt_tokens
                step_info["completion_tokens"] = usage.completion_tokens
                step_info["total_tokens"] = usage.total_tokens

            log.info("react.step", **step_info)

            # Если нет tool_calls — это финальный ответ
            if not message.tool_calls:
                trace.append(
                    _trace_entry(
                        step,
                        None,
                        None,
                        message.content,
                        usage.prompt_tokens if usage else None,
                        usage.completion_tokens if usage else None,
                        iteration_latency,
                    )
                )
                log.info("react.step.final", step=step, content=message.content[:100])  # pyright: ignore[reportOptionalSubscript]
                return {
                    "answer": message.content,
                    "usage": usage_total,
                    "steps": step + 1,
                    "trace": trace,
                }

            # Выполнение tool_calls
            for call in message.tool_calls:
                name = call.function.name  # pyright: ignore[reportAttributeAccessIssue]
                raw_args = call.function.arguments  # pyright: ignore[reportAttributeAccessIssue]

                try:
                    arguments = json.loads(raw_args) if raw_args else {}
                    result = tool_dispatch[name](**arguments)
                except KeyError:
                    result = f"Ошибка: инструмент '{name}' недоступен"
                except Exception as exc:
                    log.exception("инструмент %s завершился ошибкой", name)
                    result = f"Ошибка инструмента: {exc}"

                observation = str(result)

                trace.append(
                    _trace_entry(
                        step,
                        name,
                        json.dumps(arguments, ensure_ascii=False),
                        observation[:_RESULT_PREVIEW_LEN],
                        usage.prompt_tokens if usage else None,
                        usage.completion_tokens if usage else None,
                        iteration_latency,
                    )
                )

                messages.append({
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": observation,
                })
                log.info(
                    "react.step.tool", step=step, tool=name, latency=iteration_latency
                )

            # Self-reflection после tool observation
            if message.tool_calls:
                revision = _critic_check(
                    messages,
                    observation,
                    question,
                    config.model,
                    max_revisions,
                    revisions_used,
                    client,
                )

                if revision == "REVISE":
                    revisions_used += 1
                    revision_feedback = (
                        f"Критика: {revision_feedback if revision_feedback else 'Необходима ревизия'}.\n"
                        "Пересмотри подход и попробуй другой инструмент или уточни запрос."
                    )
                    log.info(
                        "react.revision",
                        revision=revisions_used,
                        feedback=revision_feedback[:100],
                    )

                    # Добавляем feedback в messages
                    messages.append({
                        "role": "system",
                        "content": revision_feedback,
                    })

                else:
                    revision_feedback = None

        except Exception as exc:
            log.exception("ошибка на итерации", step=step, error=str(exc))
            return {
                "answer": f"Ошибка: {exc}",
                "usage": usage_total,
                "steps": step + 1,
                "trace": trace,
                "error": str(exc),
            }

        log.info("react.step.completed", step=step, iterations=step + 1)

    log.warning("max_iterations reached", max_iterations=max_iterations)
    return {
        "answer": "Превышен лимит итераций",
        "usage": usage_total,
        "steps": max_iterations,
        "trace": trace,
        "error": "max_iterations",
    }


def _critic_check(
    messages: list[dict],
    last_observation: str,
    question: str,
    model: str,
    max_revisions: int,
    revisions_used: int,
    client: OpenAI,
) -> str:
    """Выполняет self-reflection (critic) на последнюю observation.

    Возвращает "OK" или "REVISE: <причина>".
    """
    critic_prompt = (
        "Ты критик агента. Твоя задача — оценить последнюю observation и решить, "
        "достаточно ли данных для финального ответа.\n\n"
        "Возможные ответы:\n"
        "- OK: данных достаточно, можно формировать финальный ответ.\n"
        "- REVISE: данных недостаточно, нужно ещё один инструмент или уточнение.\n\n"
        f"Вопрос пользователя: {question}\n\n"
        f"Последняя observation: {last_observation}\n\n"
        f"Количество уже использованных ревизий: {revisions_used}/{max_revisions}\n\n"
        "Верни ТОЛЬКО один из двух вариантов: OK или REVISE: <короткая причина>."
    )

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": "Ты критик агента. Оцени observation и верни OK или REVISE.",
                },
                {"role": "user", "content": critic_prompt},
            ],
        )

        critic_result = response.choices[0].message.content.strip()  # pyright: ignore[reportOptionalMemberAccess]

        if critic_result.startswith("REVISE"):
            return critic_result
        else:
            return "OK"

    except Exception:
        log.exception("ошибка в critic")
        return "OK"


def _trace_entry(
    step: int,
    tool_name: str | None,
    tool_args: str | None,
    tool_result: str | None,
    input_tokens: int | None,
    output_tokens: int | None,
    duration_sec: float,
) -> dict:
    """Одна запись трассы — единый формат для шага с инструментом и без него."""
    preview = None if tool_result is None else str(tool_result)[:_RESULT_PREVIEW_LEN]
    return {
        "step": step,
        "tool_name": tool_name,
        "tool_args": tool_args,
        "tool_result": preview,
        "llm_input_tokens": input_tokens,
        "llm_output_tokens": output_tokens,
        "duration_sec": round(duration_sec, 3),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ReAct-агент с self-reflection")
    parser.add_argument("task", help="Задача для агента")
    parser.add_argument(
        "--max-iterations", type=int, default=10, help="Лимит итераций (8–20)"
    )
    parser.add_argument(
        "--timeout", type=float, default=10.0, help="Таймаут на итерацию (5–15 сек)"
    )
    parser.add_argument(
        "--max-revisions", type=int, default=2, help="Лимит ревизий (1–3)"
    )
    parser.add_argument(
        "--trace", action="store_true", help="Печатать пошаговую трассу"
    )
    args = parser.parse_args(argv)

    log.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    result = run_react_with_reflection(
        question=args.task,
        max_iterations=args.max_iterations,
        timeout_per_iteration_sec=args.timeout,
        max_revisions=args.max_revisions,
    )

    if result.get("error"):
        print(f"Остановка: {result['error']} (шагов: {result['steps']})")
    else:
        print(result["answer"])

    if args.trace:
        print("\n--- trace ---")
        for entry in result["trace"]:
            print(json.dumps(entry, ensure_ascii=False))

    print("\n--- usage ---")
    print(json.dumps(result["usage"], ensure_ascii=False))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
