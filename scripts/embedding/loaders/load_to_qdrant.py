"""
load_to_qdrant.py — загрузка 100+ документов в Qdrant.

Идемпотентный скрипт: повторный запуск не дублирует точки.
Читает документы из data/kb/, создаёт коллекцию documents,
заливает векторы и payload с минимальными полями:
source, text, created_at + category (под предметку).

Расположение: scripts/embedding/loaders/load_to_qdrant.py
"""

import asyncio
import re
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

from qdrant_client.models import (
    PointStruct,
)
from tqdm import tqdm

from app.core.config import get_settings
from app.services.embeddings.models import EmbeddingModelConfig
from app.services.embeddings.text_splitter import TextSplitter
from app.services.embeddings.vectorizer import Vectorizer
from app.services.vector_store import VectorStore

# -------------------------
# CONFIG
# -------------------------
settings = get_settings()

# Путь к документам (из задания: data/kb - содержит 100+ документов)
KB_PATH = Path(__file__).parent.parent.parent.parent / "data" / "kb"

# Эмбеддинги — модель и размерность
EMBEDDING_ENDPOINT = settings.embedding_endpoint
EMBEDDING_MODEL = settings.embedding_model
EMBEDDING_DIM = settings.embedding_dim

# Qdrant URL — берём из .env, дефолт localhost (для local запуска)
QDRANT_URL = settings.qdrant_url
# QDRANT_API_KEY = (
#     settings.qdrant_api_key.get_secret_value() if settings.qdrant_api_key else None
# )

QDRANT_COLLECTION = settings.qdrant_collection


import uuid


def compute_embedding_hash(text: str, source: str, index: int) -> str:
    """
    Детерминированный ID для точки (валидный UUID v5).
    Обеспечивает одинаковый ID при повторной загрузке.
    """
    content = f"{source}|{index}|{text}"
    # Исползуем встроенный UUID v5 с любым базовым пространством имен (например, DNS)
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, content))


def extract_metadata(md_header: str) -> dict[str, Any]:
    """
    Парсит YAML-заголовок документа и извлекает полезные поля.
    """
    metadata: dict[str, Any] = {
        "source": "kubernetes-docs",
        "created_at": datetime.now(UTC).isoformat(),
    }

    if not md_header:
        return metadata

    # Простой парсер frontmatter-style
    lines = md_header.strip().split("\n")
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Формат: key: value
        match = re.match(r"^(\w+):\s*(.*)$", line)
        if match:
            key, value = match.groups()
            key = key.strip()
            value = value.strip()

            # Типизация
            if (
                key == "id"
                or key == "title"
                or key == "category"
                or key == "source"
                or key == "language"
            ):
                metadata[key] = value
            elif key == "created_at":
                try:
                    # Пытаемся парсить ISO формат
                    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))  # noqa: FURB162
                    metadata[key] = dt
                except Exception:  # noqa: BLE001
                    metadata[key] = value
            elif key == "tags":
                # Парсим список тегов
                tags = []
                for tag in value.split(","):
                    tag = tag.strip().strip('"').strip("'")
                    if tag:
                        tags.append(tag)
                metadata[key] = tags

    return metadata


def read_document(filepath: Path) -> tuple[str, str]:
    """
    Читает документ и извлекает текст + заголовок frontmatter.

    Возвращает: (full_text, md_header)
    """
    text = filepath.read_text(encoding="utf-8")
    # Извлекаем header между ---
    header_start = text.find("---\n")
    if header_start == -1:
        return text, ""

    header_end = text.find("\n---\n", header_start + 4)
    if header_end == -1:
        md_header = text[: header_start + 4]
    else:
        md_header = text[header_start : header_end + 4]

    # Очистка текста от frontmatter
    clean_text = text[header_end + 4 :].strip()
    return clean_text, md_header


# -------------------------
# MAIN
# -------------------------


async def main() -> None:
    """
    Главный процесс загрузки:
    1. Создаёт коллекцию
    2. Считает документы
    3. Генерирует эмбеддинги через Vectorizer
    4. Заливает в Qdrant

    Использование async with httpx.AsyncClient() — не блокирует event loop
    """
    print("=" * 60)
    print("load_to_qdrant.py — загрузка документов в Qdrant")
    print("=" * 60)

    # Инициализация Vectorizer из app/services/embeddings/
    # batch_size=128 — как в задании (128-256 точек на батч) — оптимизация производительности
    config = EmbeddingModelConfig(
        endpoint=EMBEDDING_ENDPOINT,
        name=EMBEDDING_MODEL,
        dimensions=EMBEDDING_DIM,
        normalize=True,
        batch_size=128,
    )
    vectorizer = Vectorizer(config)

    # Инициализация клиента — используем localhost для local запуска
    store = VectorStore(
        url=QDRANT_URL,  # localhost:6333 для local запуска
        # api_key=None,  # Для dev не требуется
        collection=QDRANT_COLLECTION,
        dim=EMBEDDING_DIM,
    )

    # Проверка подключения к Qdrant
    ready, err = await store.is_ready()
    if ready:
        print("  ✓ Qdrant доступен")
    else:
        print(f"  ⚠ Не удалось подключиться к Qdrant {err}")
        print(" - Убедитесь, что docker compose up -d qdrant выполнен")

    # Гарантируем существование коллекции
    await store.ensure_collection()

    # Считаем документы
    if not KB_PATH.exists():
        print(f"  ✗ Каталог документов не найден: {KB_PATH}")
        return

    documents = list(KB_PATH.rglob("*.md"))
    if not documents:
        print(f"  ✗ Найдено 0 markdown файлов в {KB_PATH}")
        return

    print(f"  📄 Найдено {len(documents)} документов")

    # Генерация точек
    points: list[PointStruct] = []
    splitter = TextSplitter()
    start = perf_counter()
    for filepath in tqdm(
        documents, desc="  🧩 Разбиение и векторизация", unit="док.", leave=False
    ):
        elapsed = perf_counter() - start
        try:
            text, md_header = read_document(filepath)
            if len(text) < 50:
                print(f"  ⚠ Пропускаем короткий документ: {filepath.name}")
                continue

            # Извлекаем метаданные
            metadata = extract_metadata(md_header)

            # Разбиваем на чанки
            chunks = splitter.split(
                text,
            )

            # Вычисляем embedding через Vectorizer
            # Vectorizer использует cache и батчи для эффективности
            chunk_texts = [chunk.text for chunk in chunks]

            vectors = vectorizer.embed_texts(chunk_texts)

            for chunk, vector in zip(chunks, vectors):
                payload = {
                    **metadata,
                    "text": chunk.text[:1000],
                }

                # ID — идемпотентность через source + index
                doc_id = compute_embedding_hash(
                    chunk.text,
                    filepath.name,
                    chunk.index,
                )

                point = PointStruct(
                    id=doc_id,
                    vector=vector,
                    payload=payload,
                )

                points.append(point)

        except Exception as e:  # noqa: BLE001
            print(f"  ✗ Ошибка обработки {filepath.name}: {e}")
            continue

    print(
        f"  ✓ Разбиение и векторизация: "
        f"{len(documents)} документов "
        f"за {elapsed:.1f} с "
        f"({len(documents) / elapsed:.2f} док./с)"
    )

    print(f"  ✓ Сгенерировано {len(points)} точек")

    if not points:
        print("  ℹ Нет точек для загрузки — выходим")
        return

    # Загрузка в Qdrant
    await store.upsert(points)

    # Финальная проверка
    count = await store.get_points_count()
    print(f"\n{'=' * 60}")
    print(f"📊 Итого в коллекции: {count} точек")
    print(f"{'=' * 60}")


# -------------------------
# ENTRY POINT
# -------------------------

if __name__ == "__main__":
    asyncio.run(main())
