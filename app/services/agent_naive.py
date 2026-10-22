"""Наивный агент на Chat Completions: цикл, диспетчер инструментов, трасса.

Вся "магия агента" умещается в один `for`-цикл вокруг одного вызова LLM:
модель либо возвращает финальный ответ, либо просит вызвать инструмент.
Никакого фреймворка — только `openai` и stdlib. Это учебная база, которую
дальше в модуле заменит управляемая обвязка на графе.
"""

import argparse
import json
import logging
import time

from openai import OpenAI

from app.core.ai.catalog import get_catalog
from app.core.config import get_settings
from app.tools.naive_tools import DISPATCH, TOOLS

logger = logging.getLogger(__name__)

_RESULT_PREVIEW_LEN = 200


def run_agent(
    task: str,
    max_steps: int = 6,
) -> dict:
    """Прогоняет наивный agent loop и возвращает ответ, число шагов и трассу."""
    settings = get_settings()

    catalog = get_catalog()

    config = catalog.get_client_config(
        model_name=settings.rag_llm_model,
        endpoint_name=settings.rag_llm_endpoint,
    )

    api_key = "None"
    if config.api_key:
        api_key = config.api_key.get_secret_value()

    client = OpenAI(base_url=config.url, api_key=api_key)
    messages: list = [{"role": "user", "content": task}]
    trace: list[dict] = []

    for step in range(max_steps):
        started = time.perf_counter()
        response = client.chat.completions.create(
            model=config.model,
            messages=messages,
            tools=TOOLS,  # pyright: ignore[reportArgumentType]
        )
        duration_ms = round((time.perf_counter() - started) * 1000, 1)

        message = response.choices[0].message
        messages.append(message)

        usage = response.usage
        input_tokens = usage.prompt_tokens if usage else None
        output_tokens = usage.completion_tokens if usage else None

        if not message.tool_calls:
            trace.append(
                _trace_entry(
                    step,
                    None,
                    None,
                    message.content,
                    input_tokens,
                    output_tokens,
                    duration_ms,
                )
            )
            logger.info("step=%d финальный ответ", step)
            return {"answer": message.content, "steps": step + 1, "trace": trace}

        for call in message.tool_calls:
            name = call.function.name  # pyright: ignore[reportAttributeAccessIssue]
            raw_args = call.function.arguments  # pyright: ignore[reportAttributeAccessIssue]
            result = _dispatch(name, raw_args)
            trace.append(
                _trace_entry(
                    step,
                    name,
                    raw_args,
                    result,
                    input_tokens,
                    output_tokens,
                    duration_ms,
                )
            )
            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": result,
            })
            logger.info("step=%d инструмент=%s -> %s", step, name, result[:80])

    logger.warning("исчерпан лимит шагов max_steps=%d", max_steps)
    return {"answer": None, "steps": max_steps, "trace": trace, "error": "max_steps"}


def _dispatch(name: str, raw_args: str) -> str:
    """Вызывает инструмент из allowlist; любую проблему возвращает строкой модели."""
    if name not in DISPATCH:
        return f"Ошибка: инструмент '{name}' недоступен. Доступные: {sorted(DISPATCH)}"
    try:
        arguments = json.loads(raw_args) if raw_args else {}
    except json.JSONDecodeError as exc:
        return f"Ошибка: не удалось разобрать аргументы ({exc})"
    try:
        return str(DISPATCH[name](**arguments))
    except Exception as exc:
        logger.exception("инструмент %s завершился ошибкой", name)
        return f"Ошибка инструмента: {exc}"


def _trace_entry(
    step: int,
    tool_name: str | None,
    tool_args: str | None,
    tool_result: str | None,
    input_tokens: int | None,
    output_tokens: int | None,
    duration_ms: float,
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
        "duration_ms": duration_ms,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Наивный агент на Chat Completions")
    parser.add_argument("task", help="Задача для агента")
    parser.add_argument(
        "--max-steps", type=int, default=6, help="Лимит шагов (guardrail)"
    )
    parser.add_argument(
        "--trace", action="store_true", help="Печатать пошаговую трассу"
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    result = run_agent(args.task, max_steps=args.max_steps)

    if result.get("error"):
        print(f"Остановка: {result['error']} (шагов: {result['steps']})")
    else:
        print(result["answer"])

    if args.trace:
        print("\n--- trace ---")
        for entry in result["trace"]:
            print(json.dumps(entry, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
