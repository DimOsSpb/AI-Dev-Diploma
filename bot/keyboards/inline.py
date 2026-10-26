"""Inline-клавиатуры для сценариев бота."""

from uuid import UUID

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

FEEDBACK_CB_PREFIX = "fb"

# HIL-подтверждение опасного действия агента (например, создание
# снапшота Proxmox). callback_data: "pve_hil:<approve|reject>:<chat_id>".
PVE_HIL_CB_PREFIX = "pve_hil"
PVE_HIL_APPROVE = "approve"
PVE_HIL_REJECT = "reject"

FEEDBACK_UP = "up"
FEEDBACK_DOWN = "down"
FEEDBACK_VALUES = (FEEDBACK_UP, FEEDBACK_DOWN)

# Темы сценариев прототипа: вопрос по базе знаний (RAG) или по инфраструктуре
# Proxmox (агент вызовет pve_status/pve_list_vms/pve_create_snapshot сам —
# явный выбор инструмента пользователю не нужен, агент решает по тексту
# вопроса).
DEFAULT_TOPICS: list[tuple[str, str]] = [
    ("📚 Вопрос по базе знаний (K8s)", "knowledge"),
    ("🖥️ Статус инфраструктуры (Proxmox)", "infra"),
]

_TOPIC_LABELS: dict[str, str] = {slug: label for label, slug in DEFAULT_TOPICS}


def topic_label(slug: str) -> str:
    """Человекочитаемая подпись темы для UI (вести edit_text после выбора)."""
    return _TOPIC_LABELS.get(slug, slug)


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


def pve_confirm_kb(chat_id: UUID) -> InlineKeyboardMarkup:
    """Кнопки подтверждения/отклонения опасного действия агента
    (HIL-гейт над `pve_create_snapshot`). callback_data: pve_hil:<decision>:<chat_id>.
    """
    kb = InlineKeyboardBuilder()
    kb.button(
        text="✅ Подтвердить",
        callback_data=f"{PVE_HIL_CB_PREFIX}:{PVE_HIL_APPROVE}:{chat_id}",
    )
    kb.button(
        text="❌ Отклонить",
        callback_data=f"{PVE_HIL_CB_PREFIX}:{PVE_HIL_REJECT}:{chat_id}",
    )
    kb.adjust(2)
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
