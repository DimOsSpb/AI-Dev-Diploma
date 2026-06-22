from app.schemas.models import CATALOG, ModelInfo
from fastapi import APIRouter

router = APIRouter(tags=["models"])


@router.get(
    "/models",
    summary="Список поддерживаемых моделей",
)
async def get_models() -> list[ModelInfo]:
    return list(CATALOG.values())
