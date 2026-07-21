from app.core.ai.catalog import get_catalog
from app.core.ai.enums import EndpointApi
from app.core.ai.models import ModelConfig

from ..models import EmbeddingModelConfig
from .base import BaseEmbeddingAdapter
from .openai import OpenAIAdapter


def create_adapter(
    cfg: EmbeddingModelConfig,
) -> BaseEmbeddingAdapter:
    catalog = get_catalog()
    client_config: ModelConfig = catalog.get_client_config(
        model_name=cfg.name,
        endpoint_name=cfg.endpoint,
    )
    match client_config.api:
        case EndpointApi.OPENAI:
            return OpenAIAdapter(client_config)

        case _:
            raise ValueError(f"Unsupported endpoint: {cfg.endpoint}")
