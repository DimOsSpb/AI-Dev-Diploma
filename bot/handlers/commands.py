"""Команды бота: /start, /help, /clear, /cancel."""

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.services.backend_client import BackendClient

router = Router(name="commands")

_START_TEXT = (
    "👋 Добро пожаловать! Я — интеллектуальный ассистент для мониторинга и "
    "диагностики ИТ-инфраструктуры (прототип).\n\n"
    "Я могу:\n"
    "• отвечать на вопросы по базе знаний (документация по K8s), с "
    "ссылками на источники;\n"
    "• самостоятельно вызывать инструменты и проверять статус/VM на "
    "реальном Proxmox;\n"
    "• создавать снапшот VM — с вашим подтверждением перед выполнением.\n\n"
    "Просто напишите вопрос — я сам определю, нужен ли инструмент или "
    "поиск по базе знаний.\n\n"
    "Команды: /help, /ask, /clear, /cancel"
)

_HELP_TEXT = (
    "Доступные команды:\n"
    "/start — начать заново, краткое описание возможностей\n"
    "/ask — выбрать тему (база знаний или инфраструктура) и задать вопрос\n"
    "/clear — очистить историю диалога и память агента (начать с чистого листа)\n"
    "/cancel — отменить текущий сценарий /ask\n\n"
    "💡 Можно просто писать вопросы без /ask — агент сам выберет, использовать "
    "ли базу знаний или инструменты Proxmox.\n"
    "Примеры: «что такое k8s?», «какие VM сейчас запущены?», "
    "«сделай снапшот VM 101»."
)


@router.message(CommandStart())
async def cmd_start(
    message: Message, backend: BackendClient, state: FSMContext
) -> None:
    await state.clear()
    # Прогреваем chat_id в backend, чтобы /clear / on_text потом не падали.
    await backend.get_or_create_chat(
        owner_external_id=str(message.chat.id),
        interface="telegram",
    )
    await message.answer(_START_TEXT)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(_HELP_TEXT)


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    current = await state.get_state()
    if current is None:
        await message.answer("Нечего отменять.")
        return
    await state.clear()
    await message.answer("Сценарий отменён.")


@router.message(Command("clear"))
async def cmd_clear(
    message: Message, backend: BackendClient, state: FSMContext
) -> None:
    await state.clear()
    chat_id = await backend.get_or_create_chat(
        owner_external_id=str(message.chat.id),
        interface="telegram",
    )
    await backend.clear_messages(chat_id, owner_external_id=str(message.chat.id))
    await message.answer("История очищена.")
