from openai import OpenAI
from pydantic import SecretStr

from app.core.ai.models import ModelConfig

from .base import BaseEmbeddingAdapter


class OpenAIAdapter(BaseEmbeddingAdapter):
    def __init__(self, config: ModelConfig):
        super().__init__(config)
        if isinstance(config.api_key, SecretStr):
            api_key = config.api_key.get_secret_value()
        else:
            api_key = "None"

        self.client = OpenAI(
            base_url=config.url,
            api_key=api_key,
        )

    def embed(self, texts: list[str]) -> list[list[float]]:

        response = self.client.embeddings.create(model=self.config.model, input=texts)

        return [item.embedding for item in response.data]
