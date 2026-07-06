"""Inline-клавиатуры для сценариев бота."""

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

FEEDBACK_CB_PREFIX = "fb"

FEEDBACK_UP = "up"
FEEDBACK_DOWN = "down"
FEEDBACK_VALUES = (FEEDBACK_UP, FEEDBACK_DOWN)

# Темы — примеры из диплом-доменов (техподдержка SaaS).
# В реальном дипломе студент подменит на свои.
DEFAULT_TOPICS: list[tuple[str, str]] = [
    ("Статус сервиса", "status"),
    ("Консоль", "console"),
    ("Вопрос", "question"),
]


def topics_kb(
    topics: list[tuple[str, str]] | None = None,
) -> InlineKeyboardMarkup:
    """Inline-кнопки выбора темы + Отмена."""
    topics = topics or DEFAULT_TOPICS
    kb = InlineKeyboardBuilder()
    for label, slug in topics:
        kb.button(text=label, callback_data=f"topic:{slug}")
    kb.button(text="Отмена", callback_data="topic:cancel")
    kb.adjust(1)
    return kb.as_markup()


def feedback_kb(message_id: str) -> InlineKeyboardMarkup:
    """Кнопки оценки ответа. callback_data: fb:<vote>:<msg_id> (42 байта)."""
    kb = InlineKeyboardBuilder()
    kb.button(
        text="👍",
        callback_data=f"{FEEDBACK_CB_PREFIX}:{FEEDBACK_UP}:{message_id}",
    )
    kb.button(
        text="👎",
        callback_data=f"{FEEDBACK_CB_PREFIX}:{FEEDBACK_DOWN}:{message_id}",
    )
    kb.adjust(2)
    return kb.as_markup()
