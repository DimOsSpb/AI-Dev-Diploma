"""
distance_metric.py

Сравнение метрик COSINE и DOT на одинаковых эмбеддингах.
После завершения временная коллекция удаляется.
"""

import asyncio
from typing import cast

from qdrant_client.models import Distance, PointStruct

from app.services.embeddings.models import EmbeddingModelConfig
from app.services.embeddings.vectorizer import Vectorizer
from app.services.vector_store import VectorStore

QUERIES = [
    "Почему pod постоянно перезапускается?",
    "Почему PVC не монтируется?",
    "Какая нагрузка на worker node?",
    "Почему nginx возвращает 502 Bad Gateway?",
    "Есть ли ошибки подключения к Redis?",
]


async def clone_collection(
    store: VectorStore,
    source: str,
    target: str,
    distance: Distance,
) -> None:
    """Создает новую коллекцию и копирует в нее все точки."""

    await store.ensure_collection(
        collection=target,
        distance=distance,
    )

    offset = None

    while True:
        records, offset = await store.client.scroll(
            collection_name=source,
            limit=256,
            offset=offset,
            with_payload=True,
            with_vectors=True,
        )

        if not records:
            break

        points = [
            PointStruct(
                id=record.id,
                vector=cast(list[float], record.vector),
                payload=record.payload,
            )
            for record in records
        ]

        await store.upsert(
            points,
            collection=target,
        )

        if offset is None:
            break


async def main() -> None:

    store = VectorStore()

    source_collection = store.collection
    cosine_collection = "documents_cosine"
    dot_collection = "documents_dot"

    print("Создание тестовых коллекций...")
    print("Cosine")
    await clone_collection(
        store,
        source_collection,
        cosine_collection,
        Distance.COSINE,
    )

    print("Dot")
    await clone_collection(
        store,
        source_collection,
        dot_collection,
        Distance.DOT,
    )

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
    print("Cosine vs Dot Product")
    print("=" * 100)

    matched = 0

    for query in QUERIES:
        vector = vectorizer.embed_texts([query])[0]

        cosine = await store.search(
            vector,
            top_k=5,
            collection=cosine_collection,
        )

        dot = await store.search(
            vector,
            top_k=5,
            collection=dot_collection,
        )

        cosine_ids = [str(point.id)[:8] for point in cosine]
        dot_ids = [str(point.id)[:8] for point in dot]

        same = cosine_ids == dot_ids

        if same:
            matched += 1

        print(f"\n❓ {query}")
        print(f"   COSINE : {' → '.join(cosine_ids)}")
        print(f"   DOT    : {' → '.join(dot_ids)}")
        print(f"   Match  : {'✓ Yes' if same else '✗ No'}")

    print("\n" + "=" * 100)
    print("Summary")
    print("=" * 100)
    print(f"Queries checked   : {len(QUERIES)}")
    print(
        f"Identical ranking : {matched}/{len(QUERIES)} ({matched / len(QUERIES):.0%})"
    )

    if matched == len(QUERIES):
        print("Conclusion        : COSINE and DOT produce identical ranking.")
        print("Production metric : COSINE")
    else:
        print("Conclusion        : Ranking differs. Check vector normalization.")


if __name__ == "__main__":
    asyncio.run(main())
