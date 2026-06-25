from fastapi import APIRouter

from app.schemas.models import CATALOG, ModelInfo

router = APIRouter(tags=["models"])


@router.get(
    "/models",
    summary="Список поддерживаемых моделей",
)
async def get_models() -> list[ModelInfo]:
    return list(CATALOG.values())
