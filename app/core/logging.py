from app.core.config import Settings
from loguru import logger


def configure_logging(settings: Settings) -> None:
    logger.remove()

    logger.add(
        settings.log_path,
        rotation="10 MB",
        level="INFO",
        format="{time} | {level} | {message}",
    )
