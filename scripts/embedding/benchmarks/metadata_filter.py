"""
metadata_filter.py

Фильтрация по metadata
"""

import asyncio

from qdrant_client.http.models import FieldCondition, MatchValue
from qdrant_client.models import Filter

from app.services.embeddings.models import EmbeddingModelConfig
from app.services.embeddings.vectorizer import Vectorizer
from app.services.vector_store import VectorStore

QUERIES = [
    "Что такое Kube-proxy?",
]


async def main() -> None:

    store = VectorStore()

    collection = store.collection

    config = EmbeddingModelConfig(
        endpoint=store.settings.embedding_endpoint,
        name=store.settings.embedding_model,
        dimensions=store.settings.embedding_dim,
        normalize=True,
        batch_size=16,
    )

    vectorizer = Vectorizer(config)

    print()
    print("=" * 100)
    print("Match по строке")
    print("=" * 100)
    key = "category"
    value = "networking"
    print(f"Query: '{QUERIES[0]}'\nFilter: key: '{key}' value '{value}'")

    vector = vectorizer.embed_texts([QUERIES[0]])[0]

    res = await store.search(
        vector,
        top_k=3,
        collection=collection,
        query_filter=Filter(
            must=[
                FieldCondition(
                    key=key,
                    match=MatchValue(value=value),
                )
            ]
        ),
    )

    print("Top 3:")
    for point in res:
        doc_id = text = "None"
        if point.payload:
            doc_id = point.payload["id"]
            text = point.payload["text"][:150]

        print(f"   {str(point.id)[:8]}: {doc_id}: {text}")

    print()
    print("=" * 100)
    print("Композитный must + must_not")
    print("=" * 100)
    key = "category"
    value = "networking"
    not_key = "id"
    not_value = "k8s-00091"
    print(
        f"Query: '{QUERIES[0]}'\nFilter: key: '{key}' value '{value}'\nFilter: not_key: '{not_key}' not_value '{not_value}'"
    )

    res = await store.search(
        vector,
        top_k=3,
        collection=collection,
        query_filter=Filter(
            must=[
                FieldCondition(
                    key=key,
                    match=MatchValue(value=value),
                )
            ],
            must_not=[
                FieldCondition(
                    key=not_key,
                    match=MatchValue(value=not_value),
                )
            ],
        ),
    )

    print("Top 3 composi:")
    for point in res:
        doc_id = text = "None"
        if point.payload:
            doc_id = point.payload["id"]
            text = point.payload["text"][:150]
        print(f"   {str(point.id)[:8]}: {doc_id}: {text}")


if __name__ == "__main__":
    asyncio.run(main())
