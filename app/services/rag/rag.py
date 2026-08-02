import re
from typing import Any

from llama_index.core import (
    Document,
    Settings,
    SimpleDirectoryReader,
    StorageContext,
    VectorStoreIndex,
)
from llama_index.core.node_parser import SentenceSplitter
from llama_index.vector_stores.qdrant import QdrantVectorStore

from app.core.ai.catalog import get_catalog
from app.core.config import get_settings
from app.services.rag.rag_embedding import DiplomaEmbedding
from app.services.rag.rag_llm import RagLLM
from app.services.vector_store import VectorStore


def strip_frontmatter(text: str) -> str:
    return re.sub(r"^---.*?---\s*", "", text, flags=re.DOTALL)


class RAGService:
    """
    RAG implementation based on LlamaIndex.

    Pipeline:

        SimpleDirectoryReader
            ↓
        SentenceSplitter
            ↓
        Embedding
            ↓
        QdrantVectorStore
            ↓
        VectorStoreIndex
            ↓
        QueryEngine
    """

    def __init__(self) -> None:
        self.settings = get_settings()
        self.catalog = get_catalog()
        self.store = VectorStore(
            collection=self.settings.rag_collection, dim=self.settings.rag_chunk_size
        )

        self.index: VectorStoreIndex | None = None
        self.query_engine = None

    async def build(self) -> None:
        """
        Build index or connect to existing collection.
        """

        Settings.embed_model = DiplomaEmbedding()

        Settings.node_parser = SentenceSplitter(
            chunk_size=self.settings.rag_chunk_size,
            chunk_overlap=self.settings.rag_chunk_overlap,
        )

        Settings.llm = RagLLM()

        vector_store = QdrantVectorStore(
            aclient=self.store.aclient,
            client=self.store.client,
            collection_name=self.settings.rag_collection,
        )

        storage_context = StorageContext.from_defaults(
            vector_store=vector_store,
        )

        collections = await self.store.aclient.get_collections()

        exists = any(
            c.name == self.settings.rag_collection for c in collections.collections
        )

        if exists:
            self.index = VectorStoreIndex.from_vector_store(
                vector_store=vector_store,
            )

        else:
            documents = SimpleDirectoryReader(
                input_dir=self.settings.rag_data_dir,
                recursive=True,
            ).load_data()

            documents = [
                Document(
                    text=strip_frontmatter(doc.text),
                    metadata=doc.metadata,
                )
                for doc in documents
            ]

            self.index = VectorStoreIndex.from_documents(
                documents,
                storage_context=storage_context,
            )

        self.query_engine = self.index.as_query_engine(
            similarity_top_k=self.settings.rag_similarity_top_k,
        )

    async def answer(
        self,
        question: str,
    ) -> dict[str, Any]:

        if self.query_engine is None:
            raise RuntimeError("RAGService.build() must be called first.")

        response = self.query_engine.query(question)

        if response.source_nodes:
            top_score = response.source_nodes[0].score or 0.0
        else:
            top_score = 0.0

        sources = []

        for node in response.source_nodes:
            sources.append({
                "text": node.text[:300],
                "source": node.metadata.get(
                    "id",
                    "unknown",
                ),
                "score": round(node.score or 0.0, 3),
            })

        return {
            "answer": str(response),
            "top_score": round(top_score, 3),
            "sources": sources,
        }


async def main() -> None:
    rag = RAGService()

    await rag.build()

    result = await rag.answer("Что такое Kubernetes?")

    print("\n" + "=" * 80)
    print("ANSWER")
    print("=" * 80)
    print(result["answer"])

    print("\nTOP SCORE:", result["top_score"])

    print("\n" + "=" * 80)
    print("SOURCES")
    print("=" * 80)

    for i, source in enumerate(result["sources"], 1):
        print(f"\n[{i}] {source['source']}   score={source['score']}")
        print("-" * 80)
        print(source["text"])


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
