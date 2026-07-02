import logging

import structlog

from app.core.config import get_settings


class Loggers:
    app = logging.getLogger("app")
    obs = structlog.get_logger("observability")
    settings = get_settings()

    logging.basicConfig(
        filename=settings.log_path,
        encoding="utf-8",
        level="INFO",
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
    )


logger = Loggers()
