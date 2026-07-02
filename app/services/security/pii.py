import hashlib
import re

PII_PATTERNS = {
    "EMAIL": re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b"),
    "PHONE_RU": re.compile(
        r"(?:\+7|8)\s*\(?\d{3}\)?[\s\-]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}"
    ),
    "CARD": re.compile(r"\b(?:\d{4}[\s\-]?){3}\d{4}\b"),
    "INN": re.compile(r"\b(?:\d{10}|\d{12})\b"),
    "PASSPORT": re.compile(r"\b\d{2}\s?\d{2}\s?\d{6}\b"),
    "ORDER_NUMBER": re.compile(r"\b(?:№\s*|заказ\s*(?:№\s*)?|order\s*(?:#\s*)?)\d{4,10}\b", re.IGNORECASE)
}


def redact_pii(text: str) -> str:
    for name, pattern in PII_PATTERNS.items():
        text = pattern.sub(f"[{name}]", text)
    return text


def prompt_hash(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()[:16]
