import logging

import structlog

from app.core.config import get_settings


class Loggers:
    app = logging.getLogger("app")
    obs = structlog.get_logger("observability")
    json_repo = logging.getLogger("llm-service.chat.json_repo")
    settings = get_settings()

    # Консольный handler для отладки
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console_handler.setFormatter(console_formatter)

    # Файловый handler (если log_path указан)
    if settings.log_path:
        file_handler = logging.FileHandler(settings.log_path, encoding="utf-8")
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(console_formatter)
        app.addHandler(file_handler)

    # Добавляем console handler для app логгера
    app.addHandler(console_handler)

    # Добавляем console handler для root логгера (чтобы все логи выводились)
    root_logger = logging.getLogger()
    root_logger.addHandler(console_handler)
    root_logger.setLevel(logging.INFO)

    # Установим уровень логирования
    logging.getLogger().setLevel(settings.log_level)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
    )


logger = Loggers()
