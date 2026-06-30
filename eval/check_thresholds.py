import glob
import json
import os
import sys
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

# Константы путей
RUNS_DIR = Path("eval/runs")
THRESHOLDS_PATH = Path("eval/thresholds.yaml")

# Дефолтные пороги на случай, если yaml пустой или отсутствует
DEFAULT_THRESHOLDS = {
    "correctness_avg": 4.0,
    "min_correctness": 2.0,
    "relevance_avg": 0.0,
    "completeness_avg": 0.0,
}


class Thresholds(BaseModel):
    correctness_avg: float = Field(default=4.0, ge=1.0, le=5.0)
    min_correctness: float = Field(default=2.0, ge=1.0, le=5.0)
    relevance_avg: float = Field(default=0.0, ge=0.0, le=5.0)
    completeness_avg: float = Field(default=0.0, ge=0.0, le=5.0)


def load_thresholds() -> Thresholds:
    """Загружает пороги из YAML-файла или возвращает дефолтные."""
    if not THRESHOLDS_PATH.exists():
        print(f"Файл {THRESHOLDS_PATH} не найден. Используются дефолтные пороги.")
        return Thresholds(**DEFAULT_THRESHOLDS)

    try:
        with open(THRESHOLDS_PATH, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
            # Заполняем дефолтами отсутствующие ключи
            merged = {**DEFAULT_THRESHOLDS, **data}
            return Thresholds(**merged)
    except Exception as e:
        print(f"Ошибка при чтении {THRESHOLDS_PATH}: {e}")
        sys.exit(1)


def get_latest_run_path() -> Path:
    """Находит самый свежий по дате изменения JSON-файл в папке runs."""
    if not RUNS_DIR.exists():
        print(
            f"Директория {RUNS_DIR} не существует. Сначала запустите run_evaluation.py."
        )
        sys.exit(1)

    json_files = glob.glob(str(RUNS_DIR / "*.json"))
    if not json_files:
        print(f"❌ В папке {RUNS_DIR} не найдено JSON-отчетов.")
        sys.exit(1)

    # Сортируем по времени модификации файла (последний измененный — в конце)
    latest_file = max(json_files, key=os.path.getmtime)
    return Path(latest_file)


def check_metrics(run_data: dict[str, Any], thresholds: Thresholds) -> bool:
    """Проверяет агрегаты из run на соответствие порогам."""
    aggregates = run_data.get("aggregates", {})
    is_failed = False

    print("\nПроверка метрик последнего прогона:")
    print("-" * 50)

    # Список проверяемых метрик
    metrics_to_check = {
        "correctness_avg": thresholds.correctness_avg,
        "min_correctness": thresholds.min_correctness,
        "relevance_avg": thresholds.relevance_avg,
        "completeness_avg": thresholds.completeness_avg,
    }

    for metric, threshold_value in metrics_to_check.items():
        if threshold_value == 0.0:
            continue  # Пропускаем метрики, для которых порог не задан

        actual_value = aggregates.get(metric)

        if actual_value is None:
            print(f"Ошибка: Метрика '{metric}' отсутствует в отчете прогона!")
            is_failed = True
            continue

        if actual_value < threshold_value:
            print(
                f"АДЕНИЕ: {metric} = {actual_value:.2f} (Ожидалось >= {threshold_value:.2f})"
            )
            is_failed = True
        else:
            print(
                f"УСПЕХ:   {metric} = {actual_value:.2f} (Ожидалось >= {threshold_value:.2f})"
            )

    print("-" * 50)
    return not is_failed


def main():
    thresholds = load_thresholds()
    latest_run_path = get_latest_run_path()

    print(f"Анализирую последний прогон: {latest_run_path.name}")

    try:
        with open(latest_run_path, "r", encoding="utf-8") as f:
            run_data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"❌ Ошибка: Файл {latest_run_path} содержит невалидный JSON: {e}")
        sys.exit(1)

    success = check_metrics(run_data, thresholds)

    if not success:
        print("Релиз отклонен: не все метрики соответствуют минимальным порогам.")
        sys.exit(1)

    print("елиз разрешен: все пороги успешно пройдены!")
    sys.exit(0)


if __name__ == "__main__":
    main()
