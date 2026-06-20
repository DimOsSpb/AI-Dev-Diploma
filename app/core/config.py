from functools import lru_cache
from pathlib import Path
from typing import ClassVar

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_file=(".env"),
        extra="ignore",
    )
    service_name: str = Field(default="Undefined")
    # Основной провайдер (OpenAI-совместимый API)
    api_key: str | None = Field(default="")
    base_url: str = Field(default="")
    primary_model: str = Field(default="")

    # Fallback-провайдер (OpenAI-совместимый API)
    fallback_api_key: str | None = Field(default="")
    fallback_base_url: str = Field(default="")
    fallback_model: str = Field(default="")

    # Общие настройки
    request_timeout: int = Field(default=30)
    max_retries: int = Field(default=3)

    history_limit: int = Field(default=10)
    log_path: Path = Field(default=Path("assistant.log"))
    redis_host: str = Field(default="localhost")
    redis_port: int = Field(default=6379)
    redis_ttl: int = Field(default=3600)

    # API KEY валидатор
    @staticmethod
    def resolve_secret_path(v: object | None) -> str | None:
        if isinstance(v, str) and (v.startswith("~") or v.startswith("/") or "./" in v):
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

        for field_name in type(self).model_fields:
            value = getattr(self, field_name)

            if value in (None, ""):
                missing.append(field_name)
            if "_key" in field_name[-4:]:
                setattr(self, field_name, self.resolve_secret_path(value))

        if missing:
            raise ValueError(
                "Не заданы переменные ENV:\n"
                + "\n".join(f"- {name}" for name in missing)
            )

        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
