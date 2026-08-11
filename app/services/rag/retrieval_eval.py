"""
Модуль метрик retrieval для оценки качества RAG.

Метрики:
1. Hit Rate@K — есть ли хотя бы один релевантный документ в top-K.
2. MRR@K — обратный ранг первого релевантного документа.
3. Recall@K — доля найденных релевантных документов в top-K.

Оценка выполняется по golden dataset.
"""

import json
import os
from pathlib import Path
from typing import Any

Prediction = dict[str, Any]


def load_golden_dataset(
    path: str = "tests/eval/rag/retrieval_dataset.json",
) -> dict[str, Any]:
    """Загрузить golden dataset."""

    candidates = [
        Path(__file__).resolve().parents[4] / path,
        Path(os.getcwd()) / path,
    ]

    for file_path in candidates:
        if file_path.exists():
            with open(file_path, encoding="utf-8") as file:
                return json.load(file)

    raise FileNotFoundError(f"Golden dataset не найден. Проверены: {candidates}")


def extract_doc_id(document: dict[str, Any]) -> str | None:
    """
    Извлечение document-level ID.

    В RAG:
    node.id != document.id

    Нам нужен именно исходный документ.
    """

    metadata = document.get("metadata", {})

    # 1. Самый надежный вариант
    if metadata.get("doc_id"):
        return str(metadata["doc_id"])

    # 2. Другие возможные названия
    if metadata.get("source_file"):
        return str(metadata["source_file"])

    if document.get("doc_id"):
        return str(document["doc_id"])

    # 3. Последний fallback
    # НЕ идеально для RAG evaluation,
    # но лучше чем ничего
    if document.get("id"):
        return str(document["id"])

    return None


def get_retrieved_ids(
    prediction: Prediction,
    k: int,
) -> set[str]:
    """Получить ID документов из top-K результатов."""

    results = prediction.get(
        "results",
        prediction.get("retrieved_docs", []),
    )

    retrieved = set()

    for document in results[:k]:
        doc_id = extract_doc_id(document)

        if doc_id:
            retrieved.add(doc_id)

    return retrieved


def get_relevant_ids(
    prediction: Prediction,
) -> set[str]:
    """Получить golden relevant document IDs."""

    question_data = prediction.get(
        "question_data",
        prediction.get("question_info", {}),
    )

    return set(
        question_data.get(
            "relevant_doc_ids",
            [],
        )
    )


def calculate_hit_rate_at_k(
    predictions: list[Prediction],
    k: int = 5,
) -> float:
    """
    Hit Rate@K.

    Доля вопросов, где хотя бы один
    релевантный документ найден в top-K.
    """

    if not predictions or k <= 0:
        return 0.0

    hits = 0

    for prediction in predictions:
        retrieved = get_retrieved_ids(prediction, k)
        relevant = get_relevant_ids(prediction)

        if retrieved & relevant:
            hits += 1

    return hits / len(predictions)


def calculate_mrr_at_k(
    predictions: list[Prediction],
    k: int = 10,
) -> float:
    """
    Mean Reciprocal Rank@K.

    Учитывает позицию первого найденного
    релевантного документа.
    """

    if not predictions or k <= 0:
        return 0.0

    reciprocal_ranks = []

    for prediction in predictions:
        relevant = get_relevant_ids(prediction)

        if not relevant:
            continue

        results = prediction.get(
            "results",
            prediction.get("retrieved_docs", []),
        )

        rank = None

        for index, document in enumerate(results[:k], start=1):
            doc_id = extract_doc_id(document)

            if doc_id in relevant:
                rank = index
                break

        reciprocal_ranks.append(1 / rank if rank else 0.0)

    return sum(reciprocal_ranks) / len(reciprocal_ranks) if reciprocal_ranks else 0.0


def calculate_recall_at_k(
    predictions: list[Prediction],
    k: int = 10,
) -> float:
    """
    Recall@K.

    Средняя доля найденных релевантных документов.
    """

    if not predictions or k <= 0:
        return 0.0

    recalls = []

    for prediction in predictions:
        relevant = get_relevant_ids(prediction)

        if not relevant:
            continue

        retrieved = get_retrieved_ids(prediction, k)

        found = len(retrieved & relevant)

        recalls.append(found / len(relevant))

    return sum(recalls) / len(recalls) if recalls else 0.0


def calculate_all_metrics(
    predictions: list[Prediction],
) -> dict[str, float]:
    """Рассчитать полный набор retrieval метрик."""

    return {
        "hit_rate@5": calculate_hit_rate_at_k(
            predictions,
            5,
        ),
        "mrr@10": calculate_mrr_at_k(
            predictions,
            10,
        ),
        "recall@10": calculate_recall_at_k(
            predictions,
            10,
        ),
    }


def attach_ground_truth(
    predictions: list[Prediction],
    golden_data: dict[str, Any],
) -> list[Prediction]:
    """
    Добавить relevant_doc_ids из golden dataset.

    Не изменяет исходные predictions.
    """

    questions = golden_data.get(
        "questions",
        [],
    )

    question_map = {
        q.get("id"): {
            "relevant_doc_ids": q.get(
                "relevant_doc_ids",
                [],
            )
        }
        for q in questions
    }

    enriched = []

    for prediction in predictions:
        metadata = prediction.get("metadata", {})

        question_id = prediction.get("question_id") or metadata.get("question_id")

        enriched.append({
            **prediction,
            "question_data": question_map.get(question_id, {}),
        })

    return enriched


def run_retrieval_evaluation(
    predictions: list[Prediction],
    golden_dataset_path: str = ("tests/eval/rag/retrieval_dataset.json"),
    include_timing: bool = False,
) -> dict[str, Any]:
    """
    Полный pipeline оценки retrieval.
    """

    try:
        golden = load_golden_dataset(golden_dataset_path)

        predictions = attach_ground_truth(
            predictions,
            golden,
        )

    except FileNotFoundError:
        predictions = [
            {
                **prediction,
                "question_data": {},
            }
            for prediction in predictions
        ]

    result = {
        "metrics": calculate_all_metrics(predictions),
        "total_questions": len(predictions),
        "avg_retrieved_docs_per_question": (
            sum(
                len(
                    p.get(
                        "results",
                        p.get(
                            "retrieved_docs",
                            [],
                        ),
                    )
                )
                for p in predictions
            )
            / max(len(predictions), 1)
        ),
    }

    if include_timing:
        result["avg_retrieval_time_ms"] = sum(
            p.get(
                "retrieval_time_ms",
                p.get(
                    "time_ms",
                    0,
                ),
            )
            for p in predictions
        ) / max(len(predictions), 1)

    return result
