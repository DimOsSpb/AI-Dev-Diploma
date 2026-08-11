"""
Один эксперимент Retrieval.

Document
    ↓
Chunker
    ↓
Embedding
    ↓
Qdrant
    ↓
Retriever
    ↓
Reranker (optional)
    ↓
Metrics
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from llama_index.core import (
    Document,
    Settings,
    VectorStoreIndex,
)
from llama_index.core.postprocessor import SentenceTransformerRerank
from llama_index.vector_stores.qdrant import QdrantVectorStore
from qdrant_client import QdrantClient

from app.core.config import get_settings
from app.services.llamaindex.embeddings import (
    create_llamaindex_embedding,
)
from app.services.rag.chunking import get_chunker
from app.services.rag.retrieval_eval import (
    load_golden_dataset,
    run_retrieval_evaluation,
)
from tests.eval.rag.report_models import (
    EvaluationResult,
    MetricResult,
    RerankerConfig,
    RetrievalConfig,
)


class EvaluationPipeline:
    """Выполняет один retrieval evaluation experiment."""

    def __init__(
        self,
        *,
        strategy: str,
        config: RetrievalConfig,
        reranker_config: RerankerConfig | None = None,
        verbose: bool = False,
    ) -> None:
        self.settings = get_settings()

        self.strategy = strategy
        self.config = config
        self.reranker_config = reranker_config
        # self.use_reranker = reranker_config is not None
        self.verbose = verbose

        self.korpus_dir = (
            Path(__file__).resolve().parents[3] / self.settings.rag_data_dir
        )

        Settings.embed_model = create_llamaindex_embedding()

        self.chunker = get_chunker(
            strategy=strategy,
            chunk_size=config.chunk_size,
            chunk_overlap=config.overlap,
        )

        self.client = QdrantClient(
            url=self.settings.qdrant_url,
        )

    # ----------------------------------------------------------
    # Documents
    # ----------------------------------------------------------

    def load_documents(self) -> list[Document]:
        """Загрузить документы базы знаний."""

        started_at = time.perf_counter()

        files = sorted(
            self.korpus_dir.rglob("*.md"),
        )

        documents = []

        for file in files:
            text = file.read_text(
                encoding="utf-8",
            )

            documents.append(
                Document(
                    text=text,
                    metadata={
                        "doc_id": file.stem,
                        "source": file.name,
                    },
                )
            )

        elapsed = self._elapsed_seconds(
            started_at,
        )

        self._log(f"Documents     : {len(documents):>4} ({elapsed:.2f}s)")

        return documents

    # ----------------------------------------------------------
    # Index
    # ----------------------------------------------------------

    def build_index(
        self,
    ) -> tuple[list[Document], VectorStoreIndex]:
        """Создать LlamaIndex index поверх Qdrant."""

        self._log("Building index...")

        documents = self.load_documents()

        started_at = time.perf_counter()

        nodes = []

        for document in documents:
            chunks = self.chunker.split(
                document.text,
                document.metadata["doc_id"],
            )

            for chunk in chunks:
                node = chunk.to_node()

                node.metadata.update(
                    document.metadata,
                )

                nodes.append(node)

        chunking_elapsed = self._elapsed_seconds(
            started_at,
        )

        self._log(f"Chunks        : {len(nodes):>4} ({chunking_elapsed:.2f}s)")

        collection_name = self._collection_name()

        self._log(f"Collection    : {collection_name}")

        self._log("Embedding + Qdrant upload...")

        index_started_at = time.perf_counter()

        vector_store = QdrantVectorStore(
            client=self.client,
            collection_name=collection_name,
        )

        index = VectorStoreIndex(
            nodes,
            vector_store=vector_store,
        )

        index_elapsed = self._elapsed_seconds(
            index_started_at,
        )

        self._log(f"✓ Index ready  ({index_elapsed:.2f}s)")

        return documents, index

    # ----------------------------------------------------------
    # Evaluation
    # ----------------------------------------------------------

    def evaluate(
        self,
        retriever,
        reranker: SentenceTransformerRerank | None = None,
    ) -> EvaluationResult:
        """Выполнить retrieval evaluation."""

        golden_dataset = load_golden_dataset()

        questions = golden_dataset.get(
            "questions",
            [],
        )

        self._log(f"Questions     : {len(questions):>4}")

        predictions: list[dict[str, Any]] = []

        for index, question in enumerate(
            questions,
            start=1,
        ):
            question_id = question.get("id")

            question_text = question.get(
                "question",
                "",
            )

            question_started_at = time.perf_counter()

            nodes = retriever.retrieve(
                question_text,
            )

            if reranker is not None:
                nodes = reranker.postprocess_nodes(
                    nodes,
                    query_str=question_text,
                )

            retrieval_time_ms = (time.perf_counter() - question_started_at) * 1000

            if self.verbose:
                self._log(
                    f"[{index:>2}/{len(questions)}] "
                    f"q={question_id:<3} "
                    f"docs={len(nodes):<2} "
                    f"{retrieval_time_ms:>7.1f} ms"
                )

            predictions.append({
                "question_id": question_id,
                "question": question_text,
                "results": [
                    {
                        "id": node.node.node_id,
                        "metadata": node.node.metadata,
                    }
                    for node in nodes
                ],
                "retrieval_time_ms": retrieval_time_ms,
            })

        result = run_retrieval_evaluation(
            predictions,
            include_timing=True,
        )

        metrics = result["metrics"]

        return EvaluationResult(
            metrics=MetricResult(
                hit_rate=metrics["hit_rate@5"],
                mrr=metrics["mrr@10"],
                recall=metrics["recall@10"],
            ),
            total_questions=result["total_questions"],
            avg_retrieved_docs_per_question=(result["avg_retrieved_docs_per_question"]),
            avg_retrieval_time_ms=(result["avg_retrieval_time_ms"]),
        )

    # ----------------------------------------------------------
    # Run
    # ----------------------------------------------------------

    def run(self) -> EvaluationResult:
        """Запустить один полный retrieval experiment."""

        experiment_started_at = time.perf_counter()

        self._print_header()

        documents, index = self.build_index()

        self._log(f"Documents     : {len(documents):>4}")

        reranker = None

        if self.reranker_config:
            reranker = self._create_reranker()
            retrieval_top_k = self.reranker_config.candidate_k

            self._log(f"Re-ranker     : {self.reranker_config.model}")

            self._log(f"Re-rank top_n : {self.reranker_config.top_n}")
        else:
            retrieval_top_k = self.config.top_k

        self._log(f"Retriever     : top_k={retrieval_top_k}")

        retriever = index.as_retriever(
            similarity_top_k=retrieval_top_k,
        )

        result = self.evaluate(
            retriever,
            reranker,
        )

        total_elapsed = self._elapsed_seconds(
            experiment_started_at,
        )

        self._print_result(
            result,
            total_elapsed,
        )

        result.total_docs = len(documents)

        return result

    # ----------------------------------------------------------
    # Re-ranker
    # ----------------------------------------------------------

    def _create_reranker(
        self,
    ) -> SentenceTransformerRerank | None:
        """Создать LlamaIndex SentenceTransformer reranker."""

        self._log("Initializing reranker...")

        started_at = time.perf_counter()
        if self.reranker_config:
            reranker = SentenceTransformerRerank(
                model=self.reranker_config.model,
                top_n=self.reranker_config.top_n,
            )
            elapsed = self._elapsed_seconds(
                started_at,
            )

            self._log(f"✓ Reranker ready ({elapsed:.2f}s)")
        else:
            reranker = None
            self._log("X Reranker config undefined")

        return reranker

    # ----------------------------------------------------------
    # Output
    # ----------------------------------------------------------

    def _print_header(self) -> None:
        """Вывести заголовок эксперимента."""

        reranker = "ON" if self.reranker_config else "OFF"

        print()
        print("=" * 72)
        print(f"Experiment: {self.strategy}")
        print("-" * 72)
        print(
            f"chunk_size={self.config.chunk_size}  "
            f"overlap={self.config.overlap}  "
            f"top_k={self.config.top_k}  "
            f"reranker={reranker}"
        )
        print("=" * 72)

    def _print_result(
        self,
        result: EvaluationResult,
        elapsed: float,
    ) -> None:
        """Вывести итог эксперимента."""

        metrics = result.metrics

        print()
        print(f"Result: {self.strategy}")
        print("-" * 72)
        print(f"Hit@5       : {metrics.hit_rate:.3f}")
        print(f"MRR@10      : {metrics.mrr:.3f}")
        print(f"Recall@10   : {metrics.recall:.3f}")
        print(f"Avg docs    : {result.avg_retrieved_docs_per_question:.1f}")
        print(f"Avg latency : {result.avg_retrieval_time_ms:.1f} ms")
        print(f"Total time  : {elapsed:.2f} s")
        print("=" * 72)

    def _log(
        self,
        message: str,
    ) -> None:
        """Вывести строку прогресса."""

        print(
            f"  {message}",
            flush=True,
        )

    # ----------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------

    def _collection_name(self) -> str:
        """Уникальное имя коллекции для эксперимента."""

        return (
            f"eval_{self.strategy}_"
            f"{self.config.chunk_size}_"
            f"{self.config.overlap}_"
            f"k{self.config.top_k}"
        )

    @staticmethod
    def _elapsed_seconds(
        started_at: float,
    ) -> float:
        return time.perf_counter() - started_at
