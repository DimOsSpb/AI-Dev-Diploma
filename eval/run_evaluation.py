import argparse
import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from openai import AsyncOpenAI

# --- Отключаем telemetry до импорта app ---
os.environ.setdefault("PHOENIX_COLLECTOR_ENDPOINT", "http://localhost:0")
os.environ.setdefault("OTEL_TRACES_EXPORTER", "none")
os.environ.setdefault("OTEL_METRICS_EXPORTER", "none")

from app.observability import tracing

tracing.setup_tracing = lambda *args, **kwargs: None

from app.core.config import get_settings
from app.main import app

settings = get_settings()

DEFAULT_JUDGE_MODEL = settings.llm.eval_default_model
MAX_PARALLEL_JUDGE = 1  # Для локальной Ollama строго 1, чтобы не зависала VRAM

judge_semaphore = asyncio.Semaphore(MAX_PARALLEL_JUDGE)

# Оптимизированный промпт: убраны лишние рассуждения, чтобы уложиться в лимиты локальной модели
JUDGE_SYSTEM_PROMPT = """You are a strict LLM evaluation system.
Твоя задача — оценить ответ ассистента, сравнив его с эталонным ответом (golden reference answer).

Ты ДОЛЖЕН вернуть ТОЛЬКО валидный JSON. Без markdown. Без лишнего текста.

Критерии оценки (оценка от 1 до 5):
1. relevance: Соответствует ли ответ вопросу пользователя?
2. correctness: Совпадает ли ответ фактически с эталонным ответом?
3. completeness: Содержит ли ответ всю ключевую информацию?

Формат вывода (СТРОГО):
Верни JSON-объект СТРОГО со следующей структурой:
{
  "reasoning": "disabled for performance",
  "scores": {
    "relevance": 5,
    "correctness": 5,
    "completeness": 5
  },
  "explanation": "one short sentence summary in Russian"
}
Ограничения: никаких блоков кода (code blocks), только валидный JSON."""


def create_openai_client() -> AsyncOpenAI:
    return AsyncOpenAI(
        base_url=settings.llm.eval_base_url,
        api_key=settings.llm.eval_api_key.get_secret_value(),
        timeout=60,
        max_retries=2,
    )


judge_client = create_openai_client()


def build_user_prompt(item: dict[str, Any], answer: str) -> str:
    expected_keywords = item.get("expected_keywords", [])
    forbidden = item.get("must_not_contain", [])

    return f"""
Question:
{item["question"]}

Golden answer:
{item["expected_answer"]}

Assistant answer:
{answer}

Expected keywords:
{", ".join(expected_keywords) if expected_keywords else "None"}

Forbidden keywords:
{", ".join(forbidden) if forbidden else "None"}
""".strip()


async def get_app_response(client: httpx.AsyncClient, question: str) -> str:
    payload = {
        "messages": [{"role": "user", "content": question}],
        "temperature": 0,
        # Прямое отключение бюджета на размышления (0 токенов на "мысли")
        "thinking_budget_tokens": 0,
        # Дополнительный хак, если сервер проигнорирует 0 (известный баг некоторых версий)
        # "thinking_budget_tokens": 1,
        # Инструкция для шаблона токенизатора Qwen3.5
        "chat_template_kwargs": {"enable_thinking": False},
    }
    try:
        # Пытаемся сделать запрос на эндпоинт вашего приложения
        response = await client.post("/chat", json=payload)
        response.raise_for_status()
        res = response.json()["content"]

        if not res or not res.strip():
            return "ERROR: Application returned a blank result."
        else:
            return res
    except Exception as exc:
        return f"ERROR: {exc}"


async def evaluate_with_judge(
    judge_model: str, item: dict[str, Any], answer: str
) -> dict[str, Any]:
    if answer.startswith("ERROR:"):
        return {
            "reasoning": "Application returned an error.",
            "scores": {"relevance": 1, "correctness": 1, "completeness": 1},
            "explanation": "Application error.",
        }

    user_prompt = build_user_prompt(item, answer)

    kwargs = {
        "model": judge_model,
        "temperature": 0,
        "max_tokens": 300,  # ИСПРАВЛЕНО: Увеличено до 300, чтобы JSON не обрезался
        "messages": [
            {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "response_format": {"type": "json_object"},
    }

    async with judge_semaphore:
        try:
            response = await judge_client.chat.completions.create(**kwargs)
            content = response.choices[0].message.content

            if content is None or not content.strip():
                raise ValueError("Judge returned empty response.")

            result = json.loads(content)
            scores = result.get("scores", {})

            return {
                "reasoning": result.get("reasoning", "Ollama mode activation."),
                "scores": {
                    "relevance": int(scores.get("relevance", 1)),
                    "correctness": int(scores.get("correctness", 1)),
                    "completeness": int(scores.get("completeness", 1)),
                },
                "explanation": result.get("explanation", "Evaluation completed."),
            }

        except json.JSONDecodeError as exc:
            return {
                "reasoning": f"Judge JSON parse failed: {exc}. Raw content: {locals().get('content', 'Empty')}",
                "scores": {"relevance": 1, "correctness": 1, "completeness": 1},
                "explanation": "Judge returned invalid JSON.",
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "reasoning": str(exc),
                "scores": {"relevance": 1, "correctness": 1, "completeness": 1},
                "explanation": "Judge request failed.",
            }


async def evaluate_single_item(
    client: httpx.AsyncClient, judge_model: str, item: dict[str, Any]
) -> dict[str, Any]:
    # answer = await get_app_response(client, item["question"])
    # judge = await evaluate_with_judge(judge_model, item, answer)
    async with judge_semaphore:
        answer = await get_app_response(
            client,
            item["question"],
        )

    judge = await evaluate_with_judge(
        judge_model,
        item,
        answer,
    )
    print(f"[{item['id']}] correctness={judge['scores']['correctness']}")

    return {
        "id": item["id"],
        "question": item["question"],
        "answer": answer,
        "scores": judge["scores"],
        "reasoning": judge["reasoning"],
        "explanation": judge["explanation"],
    }


def calculate_aggregates(items: list[dict[str, Any]]) -> dict[str, float]:
    relevance = [item["scores"]["relevance"] for item in items]
    correctness = [item["scores"]["correctness"] for item in items]
    completeness = [item["scores"]["completeness"] for item in items]

    return {
        "relevance_avg": round(sum(relevance) / len(relevance), 2),
        "correctness_avg": round(sum(correctness) / len(correctness), 2),
        "completeness_avg": round(sum(completeness) / len(completeness), 2),
        "min_correctness": min(correctness) if correctness else 0,
    }


async def main_async():
    parser = argparse.ArgumentParser(description="Запуск ИИ-оценки датасета.")
    parser.add_argument(
        "--golden", required=True, help="Путь к файлу golden_dataset.json"
    )
    parser.add_argument("--judge", default=DEFAULT_JUDGE_MODEL, help="Модель-судья")
    parser.add_argument("--out", required=True, help="Путь для сохранения артефакта")
    parser.add_argument(
        "--limit", type=int, default=None, help="Ограничить количество кейсов для теста"
    )

    args = parser.parse_args()

    golden_path = Path(args.golden)
    if not golden_path.exists():
        print(f"❌ Файл не найден: {golden_path}")
        return

    with golden_path.open(encoding="utf-8") as fp:
        golden = json.load(fp)

    golden_version = golden["version"]
    if args.limit is not None and len(golden["items"]) > args.limit:
        items = golden["items"][: args.limit]
    else:
        items = golden["items"]

    print(
        f"Loaded {len(items)} evaluation items. Model Under Test: {settings.llm.default_model}"
    )

    transport = httpx.ASGITransport(app=app)
    async with (
        httpx.AsyncClient(transport=transport, base_url="http://test") as client,
        app.router.lifespan_context(app),
    ):
        # ИСПРАВЛЕНО: Безопасный последовательный запуск для разгрузки VRAM локальной Ollama
        evaluated_items = []
        for item in items:
            res = await evaluate_single_item(client, args.judge, item)
            evaluated_items.append(res)
            await asyncio.sleep(0.5)

    # Расчет финальных агрегатов
    aggregates = calculate_aggregates(evaluated_items)

    run_output = {
        "run_id": f"run_{int(datetime.now(UTC).timestamp())}",
        "timestamp": datetime.now(UTC).isoformat(),
        "model_under_test": settings.llm.default_model,
        "judge_model": args.judge,
        "golden_version": golden_version,
        "items": evaluated_items,
        "aggregates": aggregates,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(run_output, f, indent=2, ensure_ascii=False)

    print(f"\n✅ Оценка успешно завершена! Файл сохранен в: {args.out}")
    print(f"📊 Средняя точность (correctness_avg): {aggregates['correctness_avg']}")


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
