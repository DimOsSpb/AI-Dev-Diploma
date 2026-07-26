from __future__ import annotations

import json
from pathlib import Path
from time import perf_counter

from pydantic import BaseModel

from app.services.embeddings.models import EmbeddingModelConfig
from app.services.embeddings.vectorizer import Vectorizer

from .cost import calculate_cost, count_tokens


class BenchmarkResult(BaseModel):
    model: str
    endpoint: str
    dimensions: int
    latency_ms: float
    tokens: int
    cost: float
    accuracy: float
    margin: float
    cache_hits: int
    cache_misses: int
    cache_hit_rate: float


class RetrievalResult(BaseModel):
    samples: int
    accuracy: float
    average_margin: float


class EmbeddingBenchmark:
    def __init__(self, config: EmbeddingModelConfig):
        self.config = config
        self.vectorizer = Vectorizer(config)

    def smoke(
        self,
        texts: list[str],
    ) -> tuple[int, float]:

        start = perf_counter()

        vector = self.vectorizer.embed_texts(texts)[0]

        elapsed = (perf_counter() - start) * 1000

        return len(vector), elapsed

    def estimate_cost(
        self,
        texts: list[str],
    ) -> tuple[int, float]:

        tokens = count_tokens(texts, self.config.name)

        cost = calculate_cost(
            tokens,
            self.vectorizer.model.config.pricing.input_per_1m_tokens,
        )

        return tokens, cost

    def evaluate_retrieval(
        self,
        benchmark_path: Path,
    ) -> RetrievalResult:

        data = json.loads(benchmark_path.read_text(encoding="utf-8"))

        correct = 0
        margins: list[float] = []

        for sample in data:
            q, rel, irr = self.vectorizer.embed_texts([
                sample["query"],
                sample["relevant_chunk"],
                sample["irrelevant_chunk"],
            ])

            rel_score = sum(a * b for a, b in zip(q, rel))
            irr_score = sum(a * b for a, b in zip(q, irr))

            if rel_score > irr_score:
                correct += 1

            margins.append(rel_score - irr_score)

        return RetrievalResult(
            samples=len(data),
            accuracy=correct / len(data),
            average_margin=sum(margins) / len(margins),
        )

    def cache_stats(self):

        cache = self.vectorizer.cache

        return (
            cache.hits,
            cache.misses,
            cache.hit_rate,
        )
