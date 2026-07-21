"""AI catalog enumerations."""

from enum import StrEnum


class EndpointApi(StrEnum):
    """Supported endpoint API protocols."""

    OPENAI = "openai-compatible"
    OLLAMA = "ollama"
    LLAMACPP = "llama-cpp"


class ModelType(StrEnum):
    """Supported AI model types."""

    LLM = "llm"
    EMBEDDING = "embedding"
    RERANKER = "reranker"
    OCR = "ocr"
    STT = "stt"
    TTS = "tts"
