from __future__ import annotations

from faster_whisper import WhisperModel
from infraassist.infrastructure.config import Settings
from loguru import logger


class RobustSTTClient:
    """Локальное распознавание речи через faster-whisper."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

        logger.info(
            "Loading STT model: {}",
            settings.stt_model,
        )

        self.model = WhisperModel(
            settings.stt_model,
            device=settings.stt_device,
            compute_type=settings.stt_ctype,
        )

    def transcribe(self, audio_path: str) -> str:
        """Преобразует аудиофайл в текст."""

        try:
            segments, _ = self.model.transcribe(
                audio_path,
                language="ru",
                beam_size=1,
                temperature=0.0,
            )

            return " ".join(segment.text.strip() for segment in segments).strip()

        except Exception:
            logger.exception(
                "Не удалось расшифровать аудио: {}",
                audio_path,
            )
            return ""
