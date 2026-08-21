"""RAG на LlamaIndex: широкий retrieval, опциональный реранкинг, ответ с цитатами.

Онлайн-контур построен по принципу «retrieve → guard → synthesize»:

1. Ретривер достаёт `rag_retrieve_top_k` кандидатов из Qdrant.
2. Опциональный реранкер (config-флаг, тяжёлая зависимость) пересортировывает
   и оставляет `rag_rerank_top_n`; без него — обрезка dense-топа до того же N.
3. Код-гард: если лучших score ниже порога — отдаём честный отказ, не дёргая
   LLM (быстрее и дешевле галлюцинации).
4. Иначе синтез ответа по пронумерованному контексту с цитатами [1], [2] и в конце ссылки в виде строк в формате [n] - file_name стр. page.

Запуск отдельно:
    uv run python -m app.services.rag
"""

import logging
import re
from collections.abc import AsyncIterator
from typing import Any

from llama_index.core import (
    PromptTemplate,
    Settings,
    SimpleDirectoryReader,
    StorageContext,
    VectorStoreIndex,
)
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.schema import NodeWithScore
from llama_index.core.vector_stores import (
    FilterOperator,
    MetadataFilter,
    MetadataFilters,
)
from llama_index.vector_stores.qdrant import QdrantVectorStore
from qdrant_client import AsyncQdrantClient, QdrantClient

from app.core.ai.catalog import get_catalog
from app.core.config import get_settings
from app.services.llamaindex.embeddings import create_llamaindex_embedding
from app.services.llamaindex.rerankers import LlamaCppReranker
from app.services.rag.rag_llm import RagLLM

logger = logging.getLogger(__name__)

REFUSAL_TEXT = "В базе знаний я не нашёл ответа на этот вопрос."

CITATION_QA_PROMPT = PromptTemplate(
    "Ниже — пронумерованные источники из базы знаний.\n"
    "---------------------\n{context_str}\n---------------------\n"
    "Ответь на вопрос, опираясь ТОЛЬКО на источники. Каждый факт сопровождай номером источника в квадратных скобках, например [n]"
    "В конце ответа дай список источников в формате"
    "[n] - {id} - {file_name} стр. {page}"
    "Если ответа в источниках нет — честно напиши, что не нашёл его в базе знаний, и ничего "
    "не выдумывай. Отвечай по-русски, коротко и по делу.\n"
    "Вопрос: {query_str}\n"
    "Ответ: "
)

REFUSAL_PROMPT = PromptTemplate(
    "Отвечай только по предоставленному контексту. "
    "Если ответа нет — скажи 'Релевантного ответа не нашлось'. "
    "Вопрос: {query_str}\n"
    "Ответ: {context_str}"
)


async def _generate_refusal(rag_llm: Any, question: str, refusal_text: str) -> str:
    """Генерирует ответ для случая, когда релевантных источников нет.

    rag_llm может быть любым объектом с методом acomplete() returning CompletionResponse.
    """

    prompt = REFUSAL_PROMPT.format(
        context_str="",
        query_str=question,
    )
    response = await rag_llm.acomplete(prompt)
    return response.text or refusal_text


def build_sources(source_nodes: list[NodeWithScore]) -> list[dict]:
    """Нумерованные цитаты [1..N]: id, file_name, page, score, snippet."""
    sources = []
    for i, sn in enumerate(source_nodes, start=1):
        meta = sn.metadata or {}
        sources.append({
            "id": i,
            "file_name": meta.get("file_name") or meta.get("source") or "unknown",
            "page": meta.get("page"),
            "score": round(sn.score or 0.0, 3),
            "snippet": sn.get_content()[:200].strip(),
        })
    return sources


def parse_citations(text: str, sources: list[dict]) -> str:
    """Разворачивает [1] в [1 — file.pdf], чтобы источник был виден в тексте."""
    by_id = {s["id"]: s for s in sources}

    def replace(match: re.Match) -> str:
        source = by_id.get(int(match.group(1)))
        return (
            f"[{match.group(1)} — {source['file_name']}]" if source else match.group(0)
        )

    return re.sub(r"\[(\d+)\]", replace, text)


def build_filters(
    *, visibility: str | None = "internal", departments: list[str] | None = None
) -> MetadataFilters | None:
    """Фильтр доступа до поиска: документы вне видимости даже не достаются.

    Применяется на уровне векторного хранилища, а не после ретрива — иначе
    кусок недоступного документа может попасть в контекст LLM.
    """
    filters = []
    if visibility:
        filters.append(
            MetadataFilter(
                key="visibility", value=visibility, operator=FilterOperator.EQ
            )
        )
    if departments:
        filters.append(
            MetadataFilter(
                key="department", value=departments, operator=FilterOperator.IN
            )
        )
    return MetadataFilters(filters=filters) if filters else None


def _numbered_context(nodes: list[NodeWithScore]) -> str:
    return "\n\n".join(
        f"[{i}] {sn.get_content()}" for i, sn in enumerate(nodes, start=1)
    )


class RAGService:
    """Один экземпляр на процесс: ретривер и движок собираются один раз на старте."""

    def __init__(self) -> None:
        self._settings = get_settings()

        qdrant_key = (
            self._settings.qdrant_api_key.get_secret_value()
            if self._settings.qdrant_api_key is not None
            else None
        )
        self._llm = RagLLM()
        Settings.llm = self._llm
        Settings.embed_model = create_llamaindex_embedding()
        Settings.node_parser = SentenceSplitter(
            chunk_size=self._settings.rag_chunk_size,
            chunk_overlap=self._settings.rag_chunk_overlap,
        )

        self._client = QdrantClient(url=self._settings.qdrant_url, api_key=qdrant_key)
        self._aclient = AsyncQdrantClient(
            url=self._settings.qdrant_url, api_key=qdrant_key
        )
        self._index: VectorStoreIndex | None = None
        self._retriever = None
        self._postprocessors: list = []

    async def _generate_refusal(self, question: str) -> str:
        """Генерирует отказ при отсутствии релевантных источников."""
        prompt = REFUSAL_PROMPT.format(
            context_str="",
            query_str=question,
        )
        response = await Settings.llm.acomplete(prompt)
        return response.text or REFUSAL_TEXT

    def _vector_store(self) -> QdrantVectorStore:
        kwargs: dict = {
            "collection_name": self._settings.rag_collection,
            "client": self._client,
            "aclient": self._aclient,
        }
        if self._settings.rag_use_hybrid:
            kwargs["enable_hybrid"] = True
            kwargs["fastembed_sparse_model"] = self._settings.rag_sparse_model
        return QdrantVectorStore(**kwargs)

    def _collection_ready(self) -> bool:
        """Коллекция существует и непуста — индексировать заново не нужно."""
        if not self._client.collection_exists(self._settings.rag_collection):
            return False
        return self._client.count(self._settings.rag_collection).count > 0

    def _build_reranker(self):
        catalog = get_catalog()

        cfg = catalog.get_client_config(
            model_name=self._settings.rag_reranker_model,
            endpoint_name=self._settings.rag_reranker_endpoint,
        )

        return LlamaCppReranker(
            endpoint=cfg.url,
            model=cfg.model,
            top_n=self._settings.rag_reranker_top_n,
        )

    async def build(self) -> None:
        """Подключается к готовой коллекции либо индексирует корпус из файлов."""

        vector_store = self._vector_store()

        if self._collection_ready():
            self._index = VectorStoreIndex.from_vector_store(vector_store)

        else:
            documents = SimpleDirectoryReader(
                input_dir=str(self._settings.rag_data_dir),
                recursive=True,
            ).load_data()

            storage = StorageContext.from_defaults(vector_store=vector_store)
            self._index = VectorStoreIndex.from_documents(
                documents, storage_context=storage
            )

        filters = (
            build_filters(visibility="internal")
            if self._settings.rag_restrict_to_internal
            else None
        )
        retriever_kwargs: dict = {"similarity_top_k": self._settings.rag_retrieve_top_k}
        if filters is not None:
            retriever_kwargs["filters"] = filters
        if self._settings.rag_use_hybrid:
            retriever_kwargs["vector_store_query_mode"] = "hybrid"
            retriever_kwargs["sparse_top_k"] = self._settings.rag_retrieve_top_k
        self._retriever = self._index.as_retriever(**retriever_kwargs)

        if self._settings.rag_reranker_enabled:
            self._postprocessors = [self._build_reranker()]

    async def _retrieve(self, question: str) -> list[NodeWithScore]:
        if self._retriever is None:
            raise RuntimeError(
                "RAG-индекс не инициализирован: сначала вызвать build()."
            )
        nodes = await self._retriever.aretrieve(question)
        for postprocessor in self._postprocessors:
            nodes = postprocessor.postprocess_nodes(nodes, query_str=question)
        return nodes[: self._settings.rag_reranker_top_n]

    async def answer(self, question: str) -> AsyncIterator[dict]:
        """Стримит SSE события:
        - {"type":"token","delta":"..."} - каждый токен
        - {"type":"message_saved","message_id":"..."} - после сохранения
        - {"type":"sources","data":[...]} - финальные источники
        - {"type":"done"} - завершение
        """
        if self._retriever is None:
            raise RuntimeError(
                "RAG-индекс не инициализирован: сначала вызвать build()."
            )

        # Retrieval + reranking
        nodes = await self._retrieve(question)

        top_score = max(
            (sn.score or 0.0 for sn in nodes),
            default=0.0,
        )

        logger.info(
            "RAG: retrieved %d nodes, top_score=%.3f",
            len(nodes),
            top_score,
        )

        # Score guard
        if not nodes or top_score < self._settings.rag_score_threshold:
            logger.info("RAG: score-guard triggered")

            answer = await self._generate_refusal(question)

            from uuid import uuid4

            msg_id = str(uuid4())

            yield {
                "type": "token",
                "delta": answer,
            }
            yield {
                "type": "message_saved",
                "message_id": msg_id,
            }
            yield {
                "type": "sources",
                "data": [],
            }
            yield {
                "type": "done",
            }
            return

        # Формируем prompt
        prompt = CITATION_QA_PROMPT.format(
            context_str=_numbered_context(nodes),
            query_str=question,
        )

        # Async streaming через стандартный LlamaIndex API
        llm_answer = ""

        stream = await Settings.llm.astream_complete(prompt)

        async for chunk in stream:
            part = chunk.delta or ""

            if not part:
                continue

            llm_answer += part

            yield {
                "type": "token",
                "delta": part,
            }

        # Источники
        sources = build_sources(nodes)

        # Подставляем имена файлов вместо [1], [2]

        from uuid import uuid4

        msg_id = str(uuid4())

        yield {
            "type": "message_saved",
            "message_id": msg_id,
        }

        yield {
            "type": "sources",
            "data": sources,
        }

        yield {
            "type": "done",
        }

    async def answer_sync(self, question: str) -> dict:
        """Синхронный ответ для /rag/query.

        Возвращает:
        {
            "answer": ...,
            "top_score": ...,
            "sources": [...],
            "confident": ...
        }
        """

        # Retrieval + reranking
        nodes = await self._retrieve(question)

        top_score = max(
            (sn.score or 0.0 for sn in nodes),
            default=0.0,
        )

        confident = len(nodes) > 0 and top_score >= self._settings.rag_score_threshold

        # Score guard
        if not confident:
            logger.info("RAG: sync score-guard triggered")

            answer = await self._generate_refusal(question)

            return {
                "answer": answer,
                "top_score": top_score,
                "sources": [],
                "confident": False,
            }

        # Prompt
        prompt = CITATION_QA_PROMPT.format(
            context_str=_numbered_context(nodes),
            query_str=question,
        )

        # Обычная async генерация полного ответа уже напрямую через self._llm.
        # Endpoint при этом синхронный для клиента:
        # HTTP ждёт готовый JSON.

        response = await self._llm.acomplete(prompt)

        llm_answer = response.text or ""

        # Sources
        sources = build_sources(nodes)

        final_answer = parse_citations(
            llm_answer,
            sources,
        )

        return {
            "answer": final_answer,
            "top_score": top_score,
            "sources": sources,
            "confident": True,
        }

    async def close(self) -> None: ...


def _demo() -> None:
    import asyncio
    import json

    async def run() -> None:
        service = RAGService()
        await service.build()
        for question in (
            "За сколько дней можно вернуть деньги за подписку?",
            "Как приготовить плов?",
        ):
            print(f"\nВопрос: {question}")
            async for event in service.answer(question):
                print(json.dumps(event, ensure_ascii=False))
        await service.close()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    asyncio.run(run())


if __name__ == "__main__":
    _demo()
