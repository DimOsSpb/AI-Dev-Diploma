from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator
from pydantic.types import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    service_name: str = Field(default="Undefined")
    # Основной провайдер (OpenAI-совместимый API)
    llm: LLMSettings = Field(default_factory=LLMSettings)

    # Общие настройки
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
    qdrant_collection: str = Field(default="documents")
    embedding_dim: int = Field(default=1536)  # text-embedding-3-small dimension
    embedding_model: str = Field(default="")
    embedding_endpoint: str = Field(default="")

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
