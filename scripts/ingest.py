"""Скрипт для индексации корпуса документов.

Usage:
    python scripts/ingest.py [data_dir]

Пример:
    python scripts/ingest.py data/kb
"""

import argparse
import logging
import sys
from pathlib import Path

from app.core.config import get_settings
from app.services.ingestion import IngestionService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description="Индексация корпуса документов")
    parser.add_argument(
        "data_dir",
        nargs="?",
        default=None,
        help="Путь к директории с документами (по умолчанию: RAG_DATA_DIR из конфига)",
    )
    args = parser.parse_args()

    settings = get_settings()

    # Определяем data_dir
    if args.data_dir:
        data_dir = Path(args.data_dir)
    else:
        data_dir = Path(settings.rag_data_dir)

    if not data_dir.exists():
        logger.error(f"Директория не найдена: {data_dir}")
        return 1

    logger.info(f"Индексация из: {data_dir}")
    logger.info(f"Коллекция: {settings.rag_collection}")

    service = IngestionService(settings)

    try:
        # Проверяем, нужна ли полная переиндексация
        if service.is_collection_empty():
            logger.info(
                "Коллекция пуста или не существует. Выполняю полную индексацию..."
            )
            node_count = service.ingest_all()
            logger.info(f"Индексация завершена: {node_count} нод")
        else:
            # Инкрементальная индексация через UPSERTS
            logger.info("Выполняю инкрементальную индексацию (UPSERTS)...")
            node_count = service.ingest_all()
            logger.info(f"Индексация завершена: {node_count} нод (изменено/обновлено)")
    finally:
        service.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
