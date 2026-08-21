import logging
from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, Field, model_validator
from pydantic.types import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


def validate_log_level(v: str | int) -> int:
    if isinstance(v, str):
        # Получаем актуальную карту уровней, например: {"INFO": 20, "DEBUG": 10...}
        level_mapping = logging.getLevelNamesMapping()
        upper_str = v.upper()

        if upper_str in level_mapping:
            return level_mapping[upper_str]

        raise ValueError(f"Неверный уровень логирования: {v}")
    return v


# Создаем валидируемый тип данных
LogLevel = Annotated[int, BeforeValidator(validate_log_level)]


def iter_fields(obj: BaseModel, prefix: str = "") -> Iterator[tuple[object, str]]:
    for field_name in type(obj).model_fields:
        value = getattr(obj, field_name)

        if isinstance(value, BaseModel):
            yield from iter_fields(
                value,
                field_name,
            )
        else:
            yield obj, field_name


class LLMSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LLM_",
        env_file=(".env"),
        extra="ignore",
    )
    api_key: SecretStr = SecretStr("")
    url: str = Field(default="")
    default_model: str = Field(default="")
    request_timeout: float = 30.0
    max_retries: int = 3

    vsellm_api_key: SecretStr = SecretStr("")
    vsellm_url: str = Field(default="")
    vsellm_default_model: str = Field(default="")

    llamacpp_api_key: SecretStr = SecretStr("")
    llamacpp_url: str = Field(default="")
    llamacpp_default_model: str = Field(default="")


class MissingEnvVarsError(Exception):
    """Raised when required environment variables are not set."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env"),
        extra="ignore",
    )
    log_level: LogLevel = Field(default=logging.INFO)
    service_name: str = Field(default="Undefined")
    # Основной провайдер (OpenAI-совместимый API)
    llm: LLMSettings = Field(default_factory=LLMSettings)

    # Общие настройки
    backend_url: str = Field(default="http://localhost:8000")
    request_timeout: int = Field(default=30)
    max_retries: int = Field(default=3)

    history_limit: int = Field(default=10)
    log_path: Path = Field(default=Path(""))
    redis_url: str = Field(default="localhost")
    redis_port: int = Field(default=6379)
    cache_ttl: int = Field(default=3600)

    # Chat service
    database_url: str = "postgresql+asyncpg://chat:chat@localhost:5432/chat"
    chat_repository: Literal["json", "postgres"] = "json"
    chat_storage_dir: Path = Path("./var/chats")
    chat_context_window: int = 10

    # Qdrant vector store settings
    qdrant_url: str = Field(default="http://localhost:6333")
    qdrant_api_key: SecretStr | None = Field(default=None)
    # qdrant_collection: str = Field(default="documents")
    embedding_dim: int = Field(default=1536)  # text-embedding-3-small dimension
    embedding_model: str = Field(default="")
    embedding_endpoint: str = Field(default="")
    embedding_cache_path: Path | None = Field(default=None)

    rag_llm_model: str = Field(default="")
    rag_llm_endpoint: str = Field(default="")
    rag_collection: str = Field(default="collection")
    rag_data_dir: str = Field(default="data/rag-block-03")
    rag_chunk_size: int = Field(default=512)
    rag_chunk_overlap: int = Field(default=64)
    rag_similarity_top_k: int = Field(default=3)
    rag_score_threshold: float = Field(default=0.3)

    # Chunking experiment settings (Б5.4) - rag_ prefix
    rag_chunking_strategy: str = Field(
        default="recursive"
    )  # fixed, recursive, semantic
    rag_chunk_size_fixed: int = Field(default=512)
    rag_chunk_overlap_fixed: int = Field(default=64)
    rag_chunk_size_recursive: int = Field(default=500)
    rag_chunk_overlap_recursive: int = Field(default=64)
    rag_semantic_buffer_size: int = Field(default=1)
    rag_semantic_breakpoint_threshold: float = Field(default=95.0)

    rag_retrieve_top_k: int = Field(default=5)
    # Re-ranker settings
    rag_reranker_enabled: bool = Field(default=True)
    hf_token: str | None = Field(default=None)
    rag_reranker_endpoint: str = Field(default="")
    rag_reranker_model: str = Field(default="")
    rag_reranker_algorithm: str = Field(default="bge")  # cohere, bge, huggingface
    rag_reranker_top_n: int = Field(default=3)

    rag_sparse_model: str | None = Field(default=None)
    rag_restrict_to_internal: bool = Field(default=False)
    rag_use_hybrid: bool = Field(default=False)

    bot_token: str = Field(default="")
    internal_token: str = Field(default="")

    # API KEY валидатор
    @staticmethod
    def resolve_secret_path(v: object | None) -> str | None:
        if isinstance(v, str) and (v.startswith(("~", "/")) or "./" in v):
            path = Path(v).expanduser()
            if path.is_file():
                res = path.read_text(encoding="utf-8").strip()
                return res.replace("\ufeff", "")
            else:
                raise FileNotFoundError(f"Файл api key не найден по пути: {path}")

        return None

    # валидатор объекта, выполняющийся после чтения .env
    @model_validator(mode="after")
    def check_env_vars(self) -> "Settings":

        # Извлекаем прочитанные переменные из .env
        missing = []

        for obj, field in iter_fields(self):
            value = getattr(obj, field)
            if value in (None, ""):
                missing.append(field)
            if "_key" in field[-4:] and isinstance(value, SecretStr):
                resolved = self.resolve_secret_path(value.get_secret_value())
                if resolved is not None:
                    setattr(obj, field, SecretStr(resolved))

        if missing:
            raise MissingEnvVarsError(
                "Не заданы переменные ENV:\n"
                + "\n".join(f"- {name}" for name in missing)
            )

        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
