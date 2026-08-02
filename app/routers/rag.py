from fastapi import APIRouter, Depends

from app.schemas.rag import (
    RAGQueryRequest,
    RAGQueryResponse,
)
from app.services.rag import (
    RAGService,
    get_rag,
)

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

    result = await rag.answer(request.question)

    return RAGQueryResponse(**result)
