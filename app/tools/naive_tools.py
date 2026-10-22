"""Инструменты наивного агента: реализации + описания в JSON Schema.

Здесь живут три инструмента, словарь-allowlist `DISPATCH` и список `TOOLS`
с описаниями в формате OpenAI Chat Completions. Агент (`agent_naive.run_agent`)
импортирует `TOOLS` и `DISPATCH` отсюда и сам не знает деталей реализации.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

# Заглушка базы знаний. В дипломном проекте здесь будет вызов
# app/services/rag.py (поиск top-1 фрагмента по реальной коллекции).
_KNOWLEDGE_BASE: dict[str, str] = {
    "cервис поддерживает": "Сервис поддерживает Linux, Kubernetes (K8s) и Proxmox.",
    "статус": "Статус сервиса - оптимальный.",
    "R8S": "Сокращенное название Kubernetes.",
    "Linux": "Операционная система с открытым кодом.",
}


def search_knowledge_base(query: str) -> str:
    """Поиск ответа во внутренней базе знаний по ключевому слову запроса."""
    normalized = query.lower()
    for key, value in _KNOWLEDGE_BASE.items():
        if key in normalized:
            return value
    return "По запросу ничего не найдено."


def get_current_time(timezone: str = "Europe/Moscow") -> str:
    """Текущие дата и время в указанном часовом поясе в формате ISO 8601."""
    now = datetime.now(ZoneInfo(timezone))
    return now.isoformat()


def send_telegram_message(chat_id: str, text: str) -> str:
    """Отправка сообщения клиенту в Telegram (в этом задании — заглушка)."""
    print(f"[TELEGRAM → {chat_id}] {text}")
    return f"Сообщение отправлено в {chat_id}"


# Allowlist: имя инструмента -> реализация. Никаких eval/getattr —
# модель может вызвать только то, что явно перечислено здесь.
DISPATCH = {
    "search_knowledge_base": search_knowledge_base,
    "get_current_time": get_current_time,
    "send_telegram_message": send_telegram_message,
}

# Описания инструментов для Chat Completions. От качества description
# напрямую зависит, выберет ли модель нужный инструмент в нужный момент.
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_knowledge_base",
            "description": (
                "Ищет ответ во внутренней базе знаний компании: Ответы на вопросы по предметным областям: Linux, Kubernetes, Proxmox "
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Поисковый запрос на русском языке",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": (
                "Возвращает текущие дату и время в указанном часовом поясе в формате "
                "ISO 8601. Вызывай, когда нужно знать текущее время."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "timezone": {
                        "type": "string",
                        "description": "Имя часового пояса IANA, например Europe/Moscow",
                        "default": "Europe/Moscow",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_telegram_message",
            "description": (
                "Отправляет текстовое сообщение клиенту в Telegram по идентификатору "
                "чата. Вызывай только для финального ответа клиенту и только после "
                "того, как все нужные данные уже собраны."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "chat_id": {
                        "type": "string",
                        "description": "Идентификатор чата клиента в Telegram",
                    },
                    "text": {
                        "type": "string",
                        "description": "Текст сообщения для клиента",
                    },
                },
                "required": ["chat_id", "text"],
            },
        },
    },
]
