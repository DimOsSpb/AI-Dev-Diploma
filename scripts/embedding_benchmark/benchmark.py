from pathlib import Path

from app.services.embeddings.loader import load_models

from .runner import BenchmarkResult, EmbeddingBenchmark

LATENCY_SAMPLE = [
    """
    This is a sample document for embedding benchmark.
    It 1 represents a document chunk from RAG index.
    """
]

BENCHMARK = Path(__file__).with_name("mini_benchmark.json")


def print_summary(results: list[BenchmarkResult]) -> None:

    best_accuracy = max(
        results,
        key=lambda x: x.accuracy,
    )

    best_margin = max(
        results,
        key=lambda x: x.margin,
    )

    fastest = min(
        results,
        key=lambda x: x.latency_ms,
    )

    cheapest = min(
        results,
        key=lambda x: x.cost,
    )

    best_cache = max(
        results,
        key=lambda x: x.cache_hit_rate,
    )

    print()
    print("Итоговая оценка моделей")
    print("=" * 80)

    print(
        f"{'Лучшая точность поиска':60}"
        f"{best_accuracy.model} "
        f"({best_accuracy.accuracy:.2%})"
    )

    print(
        f"{'Лучшая разделимость результатов':60}"
        f"{best_margin.model} "
        f"({best_margin.margin:.3f})"
    )

    print(
        f"{'Минимальное время векторизации':60}"
        f"{fastest.model} "
        f"({fastest.latency_ms:.1f} мс)"
    )

    print(
        f"{'Минимальная стоимость индексации':60}"
        f"{cheapest.model} "
        f"({cheapest.cost:.8f} $)"
    )

    print(
        f"{'Эффективность кеширования':60}"
        f"{best_cache.model} "
        f"({best_cache.cache_hit_rate:.2%})"
    )


def main() -> None:

    configs = load_models(Path(__file__).with_name("embedding_models.yaml"))

    results: list[BenchmarkResult] = []

    header = (
        f"{'Модель':32}"
        f"{'Endpoint ID':15}"
        f"{'Размерность':>11}"
        f"{'Embedding (мс)':>17}"
        f"{'Токены':>10}"
        f"{'Стоимость ($)':>16}"
        f"{'Точность':>10}"
        f"{'Retrieval margin':>20}"
    )

    print()
    print("Embedding Benchmark")
    print("=" * len(header))
    print(header)
    print("-" * len(header))

    total = len(configs)

    for index, (name, embedding_cfg) in enumerate(configs.items(), start=1):
        print(f"[{index}/{total}] Testing {name}...", end="\r", flush=True)

        benchmark = EmbeddingBenchmark(embedding_cfg)

        dim, elapsed = benchmark.smoke(LATENCY_SAMPLE)

        tokens, cost = benchmark.estimate_cost(LATENCY_SAMPLE)

        retrieval = benchmark.evaluate_retrieval(BENCHMARK)

        cache_hits, cache_misses, cache_rate = benchmark.cache_stats()

        result = BenchmarkResult(
            model=name,
            endpoint=embedding_cfg.endpoint,
            dimensions=dim,
            latency_ms=elapsed,
            tokens=tokens,
            cost=cost,
            accuracy=retrieval.accuracy,
            margin=retrieval.average_margin,
            cache_hits=cache_hits,
            cache_misses=cache_misses,
            cache_hit_rate=cache_rate,
        )
        results.append(result)

        print(" " * 100, end="\r")

        print(
            f"{result.model:32}"
            f"{result.endpoint:15}"
            f"{result.dimensions:11}"
            f"{result.latency_ms:17.1f}"
            f"{result.tokens:10}"
            f"{result.cost:15.8f}"
            f"{result.accuracy:11.2%}"
            f"{result.margin:20.3f}"
        )

    print_summary(results)


if __name__ == "__main__":
    main()
