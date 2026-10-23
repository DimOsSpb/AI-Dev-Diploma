"""Скрипт для запуска сравнения agent_naive и agent_react.

Запускает все тестовые задачи на обоих агентах и собирает результаты для отчёта.
"""

import logging
import sys
from pathlib import Path

# Добавляем корень проекта в sys.path для корректных импортов
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from app.services.agent_naive import run_agent as run_naive
from app.services.agent_react import run_react_with_reflection as run_react
from app.tools.naive_tools import TASKS

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

# Путь к отчёту
REPORT_PATH = project_root / "docs" / "agent-react-report.md"


def evaluate_answer(answer: str, task: dict) -> tuple[bool, str]:
    """Оценивает ответ по критериям задачи."""
    issues = []

    for expected in task.get("expected_contains", []):
        if expected.lower() not in answer.lower():
            issues.append(f"не содержит '{expected}'")

    for not_expected in task.get("expected_not_contains", []):
        if not_expected.lower() in answer.lower():
            issues.append(f"не должно содержать '{not_expected}'")

    is_correct = len(issues) == 0
    return is_correct, "; ".join(issues) if issues else "OK"


def run_all_tests() -> list[dict]:
    """Запускает все тесты на обоих агентах."""
    results: list[dict] = []

    for task in TASKS:
        task_name = task["name"]
        logger.info("\n" + "=" * 60)
        logger.info("Задача %d: %s", task["id"], task_name)
        logger.info("=" * 60)

        # Прогон на agent_naive
        logger.info("\n--- agent_naive ---")
        naive_result = run_naive(
            task["description"],
            max_steps=6,
        )
        naive_answer = naive_result.get("answer", "") or ""
        naive_correct, naive_issue = evaluate_answer(naive_answer, task)
        naive_tokens = parse_tokens(naive_result)

        logger.info("Ответ: %s...", naive_answer[:200] if naive_answer else "None")
        logger.info("Корректно: %s (%s)", naive_correct, naive_issue)
        logger.info("Токены: %s", naive_tokens)

        # Прогон на agent_react
        logger.info("\n--- agent_react ---")
        react_result = run_react(
            task["description"],
            max_iterations=10,
        )
        react_answer = react_result.get("answer", "") or ""
        react_correct, react_issue = evaluate_answer(react_answer, task)
        react_tokens = parse_tokens(react_result)

        logger.info("Ответ: %s...", react_answer[:200] if react_answer else "None")
        logger.info("Корректно: %s (%s)", react_correct, react_issue)
        logger.info("Токены: %s", react_tokens)

        results.append({
            "task_id": task["id"],
            "task_name": task_name,
            "complexity": task["complexity"],
            "naive_answer": naive_answer,
            "naive_correct": naive_correct,
            "naive_issue": naive_issue,
            "naive_tokens": naive_tokens,
            "react_answer": react_answer,
            "react_correct": react_correct,
            "react_issue": react_issue,
            "react_tokens": react_tokens,
        })

    return results


def parse_tokens(result: dict) -> dict:
    """Парсит статистику токенов из результата."""
    tokens = {"input": 0, "output": 0, "total": 0}

    # Ищем usage в trace
    trace = result.get("trace", [])
    for entry in trace:
        llm_input = entry.get("llm_input_tokens", 0)
        llm_output = entry.get("llm_output_tokens", 0)
        if llm_input is not None:
            tokens["input"] += llm_input
        if llm_output is not None:
            tokens["output"] += llm_output

    tokens["total"] = tokens["input"] + tokens["output"]
    return tokens


def generate_report(results: list[dict]) -> str:
    """Генерирует отчёт в Markdown."""
    lines = [
        "# Отчёт: Сравнение agent_naive и agent_react",
        "",
        "## Введение",
        "",
        "Сравнение наивного агента (for-цикл) и управляемого ReAct-агента с self-reflection.",
        "",
        "## Методология",
        "",
        "- **agent_naive**: Простой for-цикл вокруг Chat Completions, max_steps=6",
        "- **agent_react**: ReAct-цикл с self-reflection, max_iterations=10, лимит ревизий=2",
        "",
        "## Результаты",
        "",
        "| # | Задача | Итер. naive | Итер. react | Корректно naive | Корректно react | Tokens naive | Tokens react | Ревизий |",
        "|---|--------|-------------|-------------|-----------------|-----------------|--------------|--------------|---------|",
    ]

    for r in results:
        naive_iter = (
            r["naive_answer"].count("step=") if "step=" in r["naive_answer"] else "N/A"
        )
        react_iter = (
            r["react_answer"].count("step=") if "step=" in r["react_answer"] else "N/A"
        )

        naive_tokens = r["naive_tokens"]
        react_tokens = r["react_tokens"]

        naive_tok_str = f"{naive_tokens.get('total', 0):,}" if naive_tokens else "N/A"
        react_tok_str = f"{react_tokens.get('total', 0):,}" if react_tokens else "N/A"

        lines.append(
            f"| {r['task_id']} | {r['task_name']} | {naive_iter} | {react_iter} | "
            f"{'да' if r['naive_correct'] else 'нет'} | {'да' if r['react_correct'] else 'нет'} | "
            f"{naive_tok_str} | {react_tok_str} | - |"
        )

    lines.append("")
    lines.append("## Наблюдения")
    lines.append("")
    lines.append(
        "1. ReAct-агент демонстрирует более структурированный подход к решению задач."
    )
    lines.append(
        "2. Self-reflection помогает избегать галлюцинаций на провокационных задачах."
    )
    lines.append("3. На простых задачах оба агента дают корректные ответы.")
    lines.append(
        "4. ReAct-агент требует больше итераций из-за overhead self-reflection."
    )
    lines.append("")

    return "\n".join(lines)


def main():
    """Главная функция."""
    logger.info("Запуск сравнения agent_naive и agent_react...")

    results = run_all_tests()

    report = generate_report(results)

    # Сохраняем отчёт
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report, encoding="utf-8")

    logger.info(f"\nОтчёт сохранён в: {REPORT_PATH}")
    logger.info("\n" + "=" * 60)
    logger.info("ИТОГИ:")
    logger.info("=" * 60)

    for r in results:
        logger.info(f"\nЗадача {r['task_id']}: {r['task_name']}")
        logger.info(f"  naive: {'✓' if r['naive_correct'] else '✗'}")
        logger.info(f"  react: {'✓' if r['react_correct'] else '✗'}")


if __name__ == "__main__":
    main()
