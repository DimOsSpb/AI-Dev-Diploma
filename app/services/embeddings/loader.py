"""
Loading embedding model configuration from YAML.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

from .models import EmbeddingModelConfig

_CONFIG_FILE = Path(__file__).with_name("embedding_models.yaml")


@lru_cache
def load_models(
    models_file: Path = _CONFIG_FILE, enabled_only=True
) -> dict[str, EmbeddingModelConfig]:
    """
    Load the configuration of all available embeddings from a YAML file.

    Args:
        models_file (Path): The path to the YAML file containing
            configuration data. Defaults to `embedding_models.yaml`.
        enabled_only (bool): If True
    """

    if not models_file.exists():
        raise FileNotFoundError(f"Embedding configuration not found: {models_file}")

    with models_file.open("r", encoding="utf-8") as fp:
        data = yaml.safe_load(fp) or {}

    models = data.get("models")

    if not isinstance(models, dict):
        raise ValueError("Invalid embedding_models.yaml: 'models' section is missing.")  # noqa: TRY004

    return {
        name: EmbeddingModelConfig.model_validate(config)
        for name, config in models.items()
    }
