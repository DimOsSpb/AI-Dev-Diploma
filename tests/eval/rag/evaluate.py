"""
Полный benchmark Retrieval.

Этапы:

1. Сравнение Chunking стратегий.
2. Подбор параметров лучшей стратегии.
3. Один прогон лучшей конфигурации с Re-ranker.
4. Формирование markdown отчета.
"""

from tests.eval.rag.pipeline import EvaluationPipeline
from tests.eval.rag.report import save_report
from tests.eval.rag.report_models import (
    EvaluationReport,
    EvaluationResult,
    RerankerConfig,
    RetrievalConfig,
)

# ---------------------------------------------------------------------
# Эксперименты
# ---------------------------------------------------------------------

CHUNKING_EXPERIMENTS = [
    "fixed_size",
    "recursive",
    "semantic",
]


TUNING_EXPERIMENTS = [
    RetrievalConfig(
        chunk_size=512,
        overlap=64,
        top_k=10,
    ),
    RetrievalConfig(
        chunk_size=256,
        overlap=32,
        top_k=10,
    ),
    RetrievalConfig(
        chunk_size=256,
        overlap=64,
        top_k=10,
    ),
    RetrievalConfig(
        chunk_size=512,
        overlap=32,
        top_k=20,
    ),
    RetrievalConfig(
        chunk_size=512,
        overlap=64,
        top_k=20,
    ),
]


DEFAULT_TUNING = TUNING_EXPERIMENTS[0]

RERANKER_CONFIG = RerankerConfig(
    model="BAAI/bge-reranker-v2-m3",
    candidate_k=20,
    top_n=10,
)

# ---------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------


def evaluate_chunking(
    report: EvaluationReport,
) -> str:
    """
    Сравнить chunking strategies
    на одной базовой конфигурации.
    """

    best_strategy = ""
    best_hit_rate = -1.0

    for strategy in CHUNKING_EXPERIMENTS:
        pipeline = EvaluationPipeline(
            strategy=strategy,
            config=DEFAULT_TUNING,
        )

        result = pipeline.run()

        report.add_chunking_result(
            strategy=strategy,
            config=DEFAULT_TUNING,
            result=result,
        )

        if result.metrics.hit_rate > best_hit_rate:
            best_hit_rate = result.metrics.hit_rate
            best_strategy = strategy

    report.best_strategy = best_strategy
    report.documents = result.total_docs

    return best_strategy


# ---------------------------------------------------------------------
# Tuning
# ---------------------------------------------------------------------


def evaluate_tuning(
    report: EvaluationReport,
    strategy: str,
) -> RetrievalConfig:
    """
    Подобрать лучшую RetrievalConfig
    для выбранной chunking strategy.
    """

    best_config: RetrievalConfig | None = None
    best_result: EvaluationResult | None = None
    best_hit_rate = -1.0

    for config in TUNING_EXPERIMENTS:
        pipeline = EvaluationPipeline(
            strategy=strategy,
            config=config,
        )

        result = pipeline.run()

        report.add_tuning_result(
            config=config,
            result=result,
        )

        if result.metrics.hit_rate > best_hit_rate:
            best_hit_rate = result.metrics.hit_rate
            best_config = config
            best_result = result

    if best_config is None:
        raise RuntimeError("Не удалось выбрать лучшую tuning configuration.")

    report.best_config = best_config
    report.best_result = best_result

    return best_config


# ---------------------------------------------------------------------
# Re-ranker
# ---------------------------------------------------------------------


def evaluate_reranker(
    report: EvaluationReport,
    strategy: str,
    config: RetrievalConfig,
) -> None:
    """
    Выполнить один прогон лучшей конфигурации
    с включенным Re-ranker.
    """
    if report.best_config is None:
        raise RuntimeError(
            "Не удалось использовать Reranker - лучшая tuning configuration не определена."
        )

    pipeline = EvaluationPipeline(
        strategy=report.best_strategy,
        config=report.best_config,
        reranker_config=RERANKER_CONFIG,
    )

    result = pipeline.run()

    report.set_reranker(
        result=result,
    )


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------


def main() -> None:
    report = EvaluationReport()

    best_strategy = evaluate_chunking(
        report,
    )

    best_config = evaluate_tuning(
        report,
        best_strategy,
    )

    evaluate_reranker(
        report,
        best_strategy,
        best_config,
    )

    save_report(report)


if __name__ == "__main__":
    main()
