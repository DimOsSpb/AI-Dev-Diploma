import re
import unicodedata
from typing import Final

from app.schemas.chat import Message
from app.services.security.exceptions import SecurityInputViolation

INJECTION_PATTERNS: Final[list[re.Pattern[str]]] = [
    # Английские паттерны
    re.compile(
        r"\bignore\s+(all\s+)?(previous|prior|above)\s+instructions?\b",
        re.IGNORECASE | re.UNICODE,
    ),
    re.compile(
        r"\bdisregard\s+(the\s+)?(system|previous|above)\b", re.IGNORECASE | re.UNICODE
    ),
    re.compile(
        r"\byou\s+are\s+now\s+(a|an|the|dan|do anything now)\b",
        re.IGNORECASE | re.UNICODE,
    ),
    re.compile(r"\bforget\s+(everything|all|previous)\b", re.IGNORECASE | re.UNICODE),
    re.compile(r"\b(jailbroken|developer mode|godmode)\b", re.IGNORECASE | re.UNICODE),
    # Русские паттерны
    re.compile(
        r"\b(игнорируй|забудь|сотри)\s+(все\s+)?(предыдущие|прошлые|вышеописанные)?\s*(инструкции|указания|промпты)?\b",
        re.IGNORECASE | re.UNICODE,
    ),
    re.compile(
        r"\b(не\s+обращай\s+внимания\s+на|не\s+учитывай)\s+(системные|предыдущие|вышеописанные)?\s*(инструкции|настройки|правила)?\b",
        re.IGNORECASE | re.UNICODE,
    ),
    re.compile(
        r"\b(теперь\s+ты|ты\s+теперь)\s+(ассистент|бот|режим|разработчик|dan)\b",
        re.IGNORECASE | re.UNICODE,
    ),
    re.compile(
        r"\b(включи|активируй)\s+(режим\s+разработчика|godmode|режим\s+бога|jailbreak)\b",
        re.IGNORECASE | re.UNICODE,
    ),
    # Маркеры base64 / обхода кодированием
    re.compile(
        r"\b(base64|decode|encoded|b64|hex|utf-?8)\b", re.IGNORECASE | re.UNICODE
    ),
    re.compile(
        r"^[A-Za-z0-9+/]{15,}=*$", re.MULTILINE
    ),  # Подозрительно длинные строки base64
]

MAX_INPUT_CHARS: Final[int] = 4000
NON_PRINTABLE_RATIO_LIMIT: Final[float] = 0.10

# Разрешенные Unicode-блоки (Латиница, Кириллица, знаки препинания)
ALLOWED_UNICODE_SCRIPTS: Final[set[str]] = {"LATIN", "CYRILLIC", "COMMON", "INHERITED"}


def validate_input(messages: list[Message]) -> str:

    # 0. Проверка структуры: ищем сообщения от пользователя
    user_messages = [msg for msg in messages if msg.role == "user"]

    if not user_messages:
        raise SecurityInputViolation(
            "No user messages found in request", rule="structure"
        )

    # Берем самое последнее (актуальное) сообщение
    last_user_msg = user_messages[-1]
    text = last_user_msg.content

    # 1. Проверка длины
    if len(text) > MAX_INPUT_CHARS:
        raise SecurityInputViolation("Input too long", rule="length")

    # 2. Эвристика: доля непечатных символов
    non_printable = sum(1 for c in text if not c.isprintable() and c not in "\n\r\t")
    if non_printable / max(len(text), 1) > NON_PRINTABLE_RATIO_LIMIT:
        raise SecurityInputViolation(
            "High non-printable characters ratio", rule="encoding"
        )

    # 3. Эвристика на нетипичные Unicode-блоки (атаки иероглифами/арабской вязью)
    for char in text:
        if char.isspace() or unicodedata.category(char).startswith("P"):
            continue
        try:
            script = unicodedata.name(char).split()[0]
            if script not in ALLOWED_UNICODE_SCRIPTS:
                raise SecurityInputViolation(
                    f"Unusual unicode block: {script}", rule="unicode_anomaly"
                )

        except ValueError:
            continue

    # 4. Проверка blocklist шаблонов инъекций и base64
    for pat in INJECTION_PATTERNS:
        if pat.search(text):
            raise SecurityInputViolation("Matched malicious pattern", rule="injection")

    return text
