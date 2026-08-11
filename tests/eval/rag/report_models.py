from dataclasses import dataclass, field


@dataclass(slots=True)
class MetricResult:
    hit_rate: float = 0.0
    mrr: float = 0.0
    recall: float = 0.0


@dataclass(slots=True)
class RetrievalConfig:
    chunk_size: int
    overlap: int
    top_k: int


@dataclass(slots=True)
class RerankerConfig:
    model: str
    candidate_k: int
    top_n: int


@dataclass(slots=True)
class TuningResult:
    config: RetrievalConfig
    metrics: MetricResult


@dataclass(slots=True)
class ChunkingResult:
    strategy: str
    config: RetrievalConfig
    metrics: MetricResult


@dataclass(slots=True)
class EvaluationResult:
    metrics: MetricResult
    total_questions: int
    avg_retrieved_docs_per_question: float
    avg_retrieval_time_ms: float | None = None
    total_docs: int = 0


@dataclass(slots=True)
class EvaluationReport:
    documents: int = 0
    questions: int = 0

    best_strategy: str = ""
    best_config: RetrievalConfig | None = None
    best_result: EvaluationResult | None = None

    chunking: list[ChunkingResult] = field(
        default_factory=list,
    )

    tuning: list[TuningResult] = field(
        default_factory=list,
    )

    reranker: MetricResult | None = None

    def add_chunking_result(
        self,
        *,
        strategy: str,
        config: RetrievalConfig,
        result: EvaluationResult,
    ) -> None:
        self.questions = result.total_questions

        self.chunking.append(
            ChunkingResult(
                strategy=strategy,
                config=config,
                metrics=result.metrics,
            )
        )

    def add_tuning_result(
        self,
        *,
        config: RetrievalConfig,
        result: EvaluationResult,
    ) -> None:
        self.questions = result.total_questions

        self.tuning.append(
            TuningResult(
                config=config,
                metrics=result.metrics,
            )
        )

    def set_reranker(
        self,
        *,
        result: EvaluationResult,
    ) -> None:
        self.reranker = result.metrics
