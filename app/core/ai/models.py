"""AI catalog models."""

from pydantic import BaseModel, Field, SecretStr

from app.core.ai.enums import EndpointApi, ModelType


class Endpoint(BaseModel):
    """AI endpoint configuration."""

    name: str
    description: str
    api: EndpointApi
    url: str = Field(description="Settings attribute containing endpoint URL.")
    api_key: str | None = Field(description="Settings attribute containing API key.")


class PricingConfig(BaseModel):
    input_per_1m_tokens: float = 0
    output_per_1m_tokens: float = 0


class ModelEndpointConfig(BaseModel):
    api_model: str
    pricing: PricingConfig = Field(default_factory=PricingConfig)


class AIModel(BaseModel):
    """Logical AI model."""

    name: str
    description: str
    type: list[ModelType] = Field(default_factory=list)
    dimensions: int | None = None
    normalize: bool = True
    endpoints: dict[str, ModelEndpointConfig]


class ModelConfig(BaseModel):
    """Configuration required to initialize AI client."""

    api: EndpointApi
    url: str
    model: str
    api_key: SecretStr | None
    pricing: PricingConfig = Field(default_factory=PricingConfig)


class AICatalog(BaseModel):
    """Loaded AI catalog."""

    endpoints: dict[str, Endpoint]
    models: dict[str, AIModel]
