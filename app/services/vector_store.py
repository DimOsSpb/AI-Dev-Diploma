from qdrant_client import AsyncQdrantClient
from qdrant_client.http.models import ScoredPoint
from qdrant_client.models import (
    Distance,
    Filter,
    PayloadSchemaType,
    PointStruct,
    VectorParams,
)

from app.core.config import get_settings


class VectorStore:
    def __init__(
        self,
        url: str | None = None,
        collection: str | None = None,
        dim: int | None = None,
        settings=None,
    ) -> None:
        self.settings = get_settings()

        self.collection = self.settings.qdrant_collection
        self.dim = self.settings.embedding_dim

        self.client = AsyncQdrantClient(
            url=self.settings.qdrant_url,
        )

    async def is_ready(self) -> tuple[bool, str | None]:
        try:
            await self.client.get_collections()
            return True, None
        except Exception as e:
            return False, str(e)

    async def ensure_collection(
        self,
        collection: str | None = None,
        distance: Distance = Distance.COSINE,
    ) -> None:
        """
        Создаёт коллекцию с правильной размерностью
        и payload индексами для фильтрации.
        """
        if collection is None:
            collection = self.collection

        # Проверяем существование коллекции
        collections = await self.client.get_collections()
        collection_names = {c.name for c in collections.collections}

        if collection in collection_names:
            # Проверяем размерность
            info = await self.client.get_collection(collection)

            # info.config.params.vectors может быть None — проверяем это сначала
            if info.config and info.config.params and info.config.params.vectors:
                size: int = info.config.params.vectors.size  # pyright: ignore[reportAttributeAccessIssue]
                if size != self.dim:
                    raise RuntimeError(
                        f"Коллекция {collection} уже существует"
                        f" с размерностью {info.config.params.vectors.size},"  # pyright: ignore[reportAttributeAccessIssue]
                        f" ожидаем {self.dim}. Удалите коллекцию и перезапустите."
                    )
            print(f"  ✓ Коллекция '{collection}' существует (dim={self.dim})")
            return

        # Создаём новую коллекцию
        vectors_config = VectorParams(size=self.dim, distance=distance)
        await self.client.create_collection(
            collection_name=collection,
            vectors_config=vectors_config,
        )
        print(f"  ✓ Создана коллекция '{collection}' (dim={self.dim})")

        # Создаём payload индексы для фильтрации
        # Минимум source (KEYWORD), created_at (DATETIME) + category (KEYWORD)
        indexes = [
            ("source", PayloadSchemaType.KEYWORD),
            ("created_at", PayloadSchemaType.DATETIME),
            ("category", PayloadSchemaType.KEYWORD),
            ("tenant_id", PayloadSchemaType.INTEGER),  # Опционально
            ("department", PayloadSchemaType.KEYWORD),  # Опционально
        ]

        for field, schema_type in indexes:
            try:
                await self.client.create_payload_index(
                    collection_name=collection,
                    field_name=field,
                    field_schema=schema_type,
                )
                print(f"  ✓ Создан индекс для '{field}'")
            except Exception as e:
                # Игнорируем, если индекс уже создан
                if "already exists" not in str(e):
                    print(f"  ⚠ Ошибка индекса '{field}': {e}")

    async def upsert(
        self,
        points: list[PointStruct],
        collection: str | None = None,
        batch_size: int = 256,
    ) -> None:
        """
        Загружает точки батчами с wait=True на последнем батче.
        """
        if collection is None:
            collection = self.collection

        total = len(points)
        if total == 0:
            print("  ℹ Нет точек для загрузки")
            return

        for start in range(0, total, batch_size):
            batch = points[start : start + batch_size]
            wait = start + batch_size >= total

            await self.client.upsert(
                collection_name=collection,
                points=batch,
                wait=wait,
            )
            progress = (start + len(batch)) / total * 100
            print(
                f"  ⏳ Батч {start // batch_size + 1}/{(total + batch_size - 1) // batch_size} "
                f"({progress:.1f}%) — {len(batch)} точек"
            )

    async def get_points_count(
        self,
        collection: str | None = None,
    ) -> int | None:
        """Возвращает количество точек в коллекции."""
        if collection is None:
            collection = self.collection

        info = await self.client.get_collection(collection)
        return info.points_count

    async def search(
        self,
        query_vector: list[float],
        top_k: int = 5,
        query_filter: Filter | None = None,
        collection: str | None = None,
    ) -> list[ScoredPoint]:

        if collection is None:
            collection = self.collection

        result = await self.client.query_points(
            collection_name=collection,
            query=query_vector,
            limit=top_k,
            query_filter=query_filter,
        )

        return result.points
