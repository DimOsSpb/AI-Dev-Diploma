from functools import lru_cache

from fastapi import APIRouter, Depends, UploadFile
from fastapi.responses import JSONResponse

from app.schemas.rag import (
    RAGQueryRequest,
    RAGQueryResponse,
)
from app.services.ingestion import IngestionService
from app.services.rag import (
    RAGService,
    get_rag,
)


@lru_cache
def get_ingestion_service() -> IngestionService:
    """Lazy singleton для IngestionService."""
    from app.core.config import get_settings

    settings = get_settings()
    return IngestionService(settings)


router = APIRouter(
    prefix="/rag",
    tags=["RAG"],
)


@router.post(
    "/query",
    response_model=RAGQueryResponse,
)
async def query(
    request: RAGQueryRequest,
    rag: RAGService = Depends(get_rag),
) -> RAGQueryResponse:

    result = await rag.answer_sync(request.question)

    return RAGQueryResponse(**result)


@router.post(
    "/documents/upload",
    status_code=202,
    tags=["Documents"],
)
async def upload_document(
    file: UploadFile,
    ingestion_service: IngestionService = Depends(get_ingestion_service),
) -> JSONResponse:
    """Загрузка документа для индексации.

    Файл сохраняется в data/ и запускается фоновая индексация.
    Возвращает 202 Accepted.
    """
    # Сохраняем файл в data/корпус
    data_dir = ingestion_service._data_dir
    if not file.filename:
        return JSONResponse(
            status_code=400,
            content={"message": "No filename provided"},
        )
    file_path = data_dir / file.filename

    # Создаём папку, если нет
    file_path.parent.mkdir(parents=True, exist_ok=True)

    # Записываем содержимое
    contents = await file.read()
    file_path.write_bytes(contents)

    # Индексируем файл
    count = ingestion_service.ingest_files([str(file_path)])

    return JSONResponse(
        status_code=202,
        content={
            "message": "Document accepted for indexing",
            "filename": file.filename,
            "indexed_nodes": count,
        },
    )
