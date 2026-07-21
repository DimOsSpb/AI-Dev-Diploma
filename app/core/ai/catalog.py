"""AI catalog runtime access."""

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import SecretStr

from app.core.config import get_settings

from .models import (
    AICatalog,
    AIModel,
    Endpoint,
    ModelConfig,
    PricingConfig,
)

CATALOG_PATH = Path(__file__).parent / "ai_catalog.yaml"


class Catalog:
    """
    Runtime AI catalog.

    Combines:
    - static AI catalog from yaml
    - runtime configuration from Settings

    Provides validated access to AI clients configuration.
    """

    def __init__(self):
        self._catalog: AICatalog
        with CATALOG_PATH.open(
            "r",
            encoding="utf-8",
        ) as file:
            data = yaml.safe_load(file)

        self._catalog = AICatalog(
            endpoints={
                endpoint: Endpoint(
                    name=endpoint,
                    **endpoint_data,
                )
                for endpoint, endpoint_data in data["endpoints"].items()
            },
            models={
                model: AIModel(
                    name=model,
                    **model_data,
                )
                for model, model_data in data["models"].items()
            },
        )

    def get_client_config(
        self,
        model_name: str,
        endpoint_name: str,
    ) -> ModelConfig:
        """
        Build client configuration for AI model.

        Raises:
            ValueError:
                If model or endpoint does not exist
                or model is unavailable on endpoint.
        """

        model = self._catalog.models.get(model_name)

        if model is None:
            raise ValueError(f"AI model not found: {model_name}")

        endpoint = self._catalog.endpoints.get(endpoint_name)

        if endpoint is None:
            raise ValueError(f"AI endpoint not found: {endpoint_name}")

        deployment = model.endpoints.get(endpoint_name)

        if deployment:
            depl_model = deployment.api_model
            if not depl_model:
                raise ValueError(
                    f"Model '{model_name}' is not configured on endpoint '{endpoint_name}'"
                )
            pricing = deployment.pricing
            if not isinstance(pricing, PricingConfig):
                raise TypeError(f"Expected PricingConfig but got {type(pricing)}")
        else:
            raise ValueError(
                f"Model '{model_name}' is not available on endpoint '{endpoint_name}'"
            )

        settings = get_settings()
        api_key: str | None = None

        if endpoint.api_key:
            field_name = endpoint.api_key.removeprefix("LLM_").lower()

            api_key = getattr(
                settings.llm,
                field_name,
                None,
            )

            if api_key is None:
                raise AttributeError(
                    f"API key not found for endpoint '{endpoint_name}': {endpoint.api_key}"
                )

            if not isinstance(api_key, SecretStr):
                raise TypeError(f"API key field '{field_name}' must be SecretStr")

        return ModelConfig(
            api=endpoint.api,
            url=endpoint.url,
            api_key=api_key,
            model=depl_model,
            pricing=pricing,
        )


@lru_cache
def get_catalog() -> Catalog:
    """
    Get initialized AI catalog.

    Catalog is created once per application process.
    """

    return Catalog()
