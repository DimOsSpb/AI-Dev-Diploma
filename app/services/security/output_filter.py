from app.core.context import get_current_app
from app.prompts.builder import build_system_prompt
from app.services.security.exceptions import SecurityOutputViolation
from app.services.security.pii import redact_pii


def _normalize_spaces(text: str) -> str:
    """Убирает дубли пробелов и переносы строк для точного поиска подстрок."""
    return " ".join(text.split())


def filter_output(answer: str) -> str:
    """Режет утечку системного промпта, проверяет канарейку, маскирует PII."""
    normalized_answer = _normalize_spaces(answer)

    system_prompt = build_system_prompt()

    # Проверки безопасности на утечки и политики контента
    app = get_current_app()
    if app:
        canary = getattr(app.state, "canary", None)
        if canary and canary in answer:
            raise SecurityOutputViolation(
                "System prompt leakage detected via canary token.", rule="canary"
            )

    normalized_system = _normalize_spaces(system_prompt)
    if normalized_system[:80].lower() in normalized_answer.lower():
        raise SecurityOutputViolation(
            "System prompt leakage detected via prompt substring.", rule="prompt_prefix"
        )

    # Применяем маскирование PII, принадлежащее слою безопасности
    return redact_pii(answer)
