"""Классификация пользовательских запросов и правила эскалации.

Определяет 4 категории (faq, technical, complaint, escalation), словари
ключевых слов для эвристической классификации и функцию ``should_escalate``,
которая решает, нужно ли передавать запрос живому оператору.
"""

from __future__ import annotations

from infraassist.core.models import Category

ESCALATION_KEYWORDS = {
    "менеджер",
    "начальник",
    "жалоба",
    "юрист",
    "суд",
    "прокуратура",
    "роспотребнадзор",
}

TECHNICAL_KEYWORDS = {
    "ошибка",
    "не работает",
    "не могу",
    "413",
    "500",
    "404",
    "загрузка",
    "вход",
    "синхронизация",
    "файл",
}

COMPLAINT_KEYWORDS = {
    "ужасно",
    "отстой",
    "недоволен",
    "плохо",
    "разочарован",
}

FAQ_KEYWORDS = {
    "сколько стоит",
    "тариф",
    "как",
    "где",
    "можно ли",
    "поддерживается",
    "лимит",
    "восстановить",
}


def heuristic_classify(user_message: str) -> Category:
    text = user_message.lower()
    if any(keyword in text for keyword in ESCALATION_KEYWORDS):
        return Category.ESCALATION
    if any(keyword in text for keyword in COMPLAINT_KEYWORDS):
        return Category.COMPLAINT
    if any(keyword in text for keyword in TECHNICAL_KEYWORDS):
        return Category.TECHNICAL
    if any(keyword in text for keyword in FAQ_KEYWORDS):
        return Category.FAQ
    return Category.TECHNICAL


def should_escalate(category: Category, failed_attempts: int) -> bool:
    if category == Category.ESCALATION and failed_attempts >= 3:
        return True
    return False
