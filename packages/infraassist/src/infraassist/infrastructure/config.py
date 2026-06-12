from pathlib import Path
from typing import Annotated, Any, ClassVar

from pydantic import AfterValidator, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def find_repo_root(start_path: Path) -> Path:
    for parent in [start_path] + list(start_path.parents):
        if (parent / ".git").exists():
            return parent
    return start_path


app_dir = Path(__file__).resolve().parent
root_dir = find_repo_root(app_dir)
# API KEY валидатор


def resolve_secret_path(v: object | None) -> Any:
    if isinstance(v, str) and (v.startswith("~") or v.startswith("/") or "./" in v):
        path = Path(v).expanduser()
        if path.is_file():
            res = path.read_text(encoding="utf-8").strip()
            return res.replace("\ufeff", "")
        else:
            raise FileNotFoundError(f"Файл ключа не найден по пути: {path}")
    return v


# 2. Главный класс настроек
class Settings(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_file=(root_dir / ".env"),
        extra="ignore",
    )
    service_name: str = Field(default="SupportAssistent")
    # Основной провайдер (OpenAI-совместимый API)
    api_key: Annotated[str | None, AfterValidator(resolve_secret_path)] = Field(
        default=""
    )
    base_url: str = Field(default="")
    primary_model: str = Field(default="")

    # Fallback-провайдер (OpenAI-совместимый API)
    fallback_api_key: Annotated[str | None, AfterValidator(resolve_secret_path)] = (
        Field(default="")
    )
    fallback_base_url: str = Field(default="")
    fallback_model: str = Field(default="")

    # STT
    stt_model: str = Field(default="small")
    stt_device: str = Field(default="cpu")
    stt_ctype: str = Field(default="int8")

    # TTS
    piper_bin: Path = Path("infrastructure/tts/piper/bin/piper")
    tts_model_path: Path = Path(
        "infrastructure/tts/piper/models/ru_RU-irina-medium.onnx"
    )

    # Общие настройки
    request_timeout_seconds: float = Field(default=30)
    retry_attempts: int = Field(default=3)
    history_limit: int = Field(default=10)
    log_path: Path = Field(default=app_dir / "assistant.log")
    redis_host: str = Field(default="localhost")
    redis_port: int = Field(default=6379)
    redis_ttl: int = Field(default=3600)

    # Proxmox cluster
    pve_host: str = Field(default="")  # Например: "192.168.1.100"
    pve_user: str = Field(default="")  # audit@pam
    pve_token_name: str = Field(default="")
    pve_token_value: Annotated[str | None, AfterValidator(resolve_secret_path)] = Field(
        default=""
    )
    pve_verify_ssl: bool = Field(default=False)

    # валидатор объекта, выполняющийся после чтения .env
    @model_validator(mode="after")
    def check_env_vars(self) -> "Settings":

        # Извлекаем прочитанные переменные из .env
        missing = []

        for field_name in type(self).model_fields:
            value = getattr(self, field_name)

            if value in (None, ""):
                missing.append(field_name)

        if missing:
            raise ValueError(
                "Не заданы переменные ENV:\n"
                + "\n".join(f"- {name}" for name in missing)
            )

        return self


settings = Settings()
