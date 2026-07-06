# Production чат-сервис + Telegram-бот

Образцовая реализация для блока «Чат-боты и конверсационные интерфейсы». Это
снимок **одного сквозного сервиса**, который растёт от чекпоинта к чекпоинту. На
прошлом шаге это был FastAPI-сервис для LLM (кеш, потоковая выдача, обработка
ошибок) — без истории диалога и без бота. На этом шаге сервис превращается в
полноценный чат-продукт: персистентная история в Postgres, тонкий Telegram-бот
на aiogram и вся production-обвязка вокруг диалога.

## Что нового на этом чекпоинте

Это граница модуля — самый большой скачок в проекте. Добавились сразу несколько
крупных кусков: доменное чат-ядро с историей, Telegram-бот, модерация, лимит
запросов, админ-API с рассылками, оповещения операторам и миграции базы.

| Что добавилось | Каталог / файл | Зачем |
|---|---|---|
| Чат-ядро с историей | `app/chat/` | домен на Pydantic, репозитории Postgres/JSON, выбор системного промпта (A/B), приём изображений/голоса/документов, потоковая выдача через SSE |
| Telegram-бот | `bot/` | тонкий клиент на aiogram 3.x: своей истории не хранит, рендерит SSE-поток сервера; команды, сценарий-мастер, медиа, оценки ответов |
| Модерация | `app/moderation/` | каскад из двух слоёв: локальный regex-список и OpenAI Moderation; блокировка ввода до старта потока |
| Лимит запросов | `app/ratelimit/` | счётчик «N сообщений в минуту» на пользователя — атомарный UPSERT в Postgres, при превышении 429 с `Retry-After` |
| Админ-API и рассылки | `app/admin/`, `app/services/broadcaster.py` | статистика за окно, экспорт истории с маскированием персональных данных, рассылка по интерфейсу, пауза диалога; защита заголовком `X-Admin-Token` |
| Оповещения операторам | `app/services/{alerter,notifier,handoff}.py` | очередь оповещений в Postgres; передача диалога оператору; сервер пишет строку, бот её забирает и шлёт в админ-чат |
| Миграции базы | `migrations/`, `alembic.ini` | alembic-схема: чаты, сообщения, лимиты, оценки, системные промпты, оповещения, рассылки |

Базовый вызов модели (`app/services/llm.py`) и ручки `/health` / `/ready` по сути
те же — добавилось всё вокруг диалога.

## Куда смотреть

Если интересен именно этот чекпоинт — начинать здесь:

```
app/chat/service.py        # ChatService: история → контекст → LLM → сохранение, поток событий
app/chat/routes.py         # POST /chats, /chats/{id}/messages (SSE), оценка ответа
app/chat/domain.py         # Chat / ChatMessage / SystemPrompt — чистые Pydantic-модели
app/moderation/service.py  # двухслойный каскад модерации (regex + OpenAI)
app/ratelimit/service.py   # атомарный счётчик лимита через INSERT … ON CONFLICT
app/admin/routes.py        # /chats/admin/* — статистика, экспорт, рассылка, пауза
bot/__main__.py            # бот: long polling + сервер обратного канала + слив оповещений в одном цикле
bot/handlers/text.py       # свободный текст пользователя → запрос к серверу → поток ответа
```

Карта всего сервиса:

```
app/         серверная часть на FastAPI: chat/ (чат-ядро), routers/, services/,
             moderation/ (regex + OpenAI), admin/, ratelimit/, observability/ (маскирование данных)
bot/         тонкий Telegram-бот (aiogram 3.x); истории не хранит — единственный
             источник правды это серверная часть
migrations/  alembic (чаты, сообщения, лимиты, оценки, промпты, оповещения, рассылки)
tests/       pytest-asyncio, httpx.ASGITransport — без обращения к сети
```

## Как устроен путь сообщения

1. Бот получает текст или медиа, идемпотентно создаёт чат по
   `(owner_external_id, interface)` и шлёт сообщение на сервер.
2. Сервер сначала проверяет лимит запросов и модерацию — обе проверки идут
   **до** старта потока, чтобы при блокировке вернуть 403/429 нормальным
   HTTP-статусом, а не внутри уже открытого `text/event-stream`.
3. `ChatService` сохраняет сообщение пользователя, собирает последние N реплик
   как контекст, при наличии кандидатов выбирает системный промпт по A/B и
   стримит ответ модели.
4. Сервер отдаёт стабильный поток событий SSE; бот рендерит его в Telegram через
   `sendMessageDraft` и по событию `message_saved` вешает кнопки оценки ответа.

Контракт SSE неизменен — клиент пишется один раз:

```
data: {"type":"token","delta":"<кусок текста>"}
data: {"type":"message_saved","message_id":"<uuid>"}
data: {"type":"done"}
```

## Быстрый старт

Нужен [`uv`](https://docs.astral.sh/uv/) (`brew install uv` или `pip install uv`);
Python 3.12+ `uv` поставит сам. Бот работает только в полном стеке, поэтому
основной способ запуска — Docker.

### Полный стек через Docker (сервер + бот + Postgres + Redis)

```bash
cp .env.example .env
# заполнить:
#   LLM__OPENAI_API_KEY  — ключ OpenAI
#   BOT_TOKEN            — токен бота от @BotFather
#   BOT_ADMIN_IDS        — Telegram user id админов (через запятую)
#   ADMIN_TOKEN          — openssl rand -hex 32 (общий для сервера и бота)
#   INTERNAL_TOKEN       — openssl rand -hex 32 (обратный канал сервер → бот)
#   ADMIN_CHAT_ID        — куда боту слать оповещения операторам

docker compose up -d --build
docker compose exec app alembic upgrade head   # накатить миграции базы
docker compose logs -f bot                      # увидеть «Bot starting ...»
```

`compose.override.yaml` в dev подмерживается автоматически: перезапуск по
изменению кода, проброс `redis:6379` и `postgres:5432` на хост.

### Только сервер, без бота

```bash
uv sync
cp .env.example .env                  # вписать LLM__OPENAI_API_KEY
uv run uvicorn app.main:app --reload --port 8000
# Swagger: http://localhost:8000/docs
```

Postgres и Redis опциональны для разработки: если их нет на старте, `lifespan`
ловит ошибку и поднимается без них — кеш отключается, история переключается в
файловый режим (`CHAT_REPOSITORY=json`), лимит и оценки в таком режиме недоступны.

## Примеры вызовов

### Создать чат и послать сообщение (SSE)

```bash
# идемпотентно по (owner_external_id, interface)
curl -s -X POST http://localhost:8000/chats \
  -H "Content-Type: application/json" \
  -d '{"owner_external_id":"u-42","interface":"telegram"}'
# → {"chat_id":"<uuid>"}

curl -N -X POST "http://localhost:8000/chats/<uuid>/messages" \
  -H "X-Owner-External-Id: u-42" \
  -F content="Привет, расскажи о себе одним предложением"
# data: {"type":"token","delta":"..."}
# data: {"type":"message_saved","message_id":"<uuid>"}
# data: {"type":"done"}
```

### Админ-API (нужен заголовок `X-Admin-Token`)

```bash
TOKEN="$(grep ^ADMIN_TOKEN= .env | cut -d= -f2)"

curl -s -H "X-Admin-Token: $TOKEN" http://localhost:8000/chats/admin/stats

curl -s -H "X-Admin-Token: $TOKEN" -X POST http://localhost:8000/chats/admin/broadcast \
  -H "Content-Type: application/json" \
  -d '{"text":"Тех-работы в 02:00","interface":"telegram"}'

curl -s -H "X-Admin-Token: $TOKEN" http://localhost:8000/chats/admin/alerts
```

### Команды бота в Telegram

- `/start` / `/help` / `/clear` / `/cancel` — базовые
- `/ask` — вопрос с выбором темы (сценарий-мастер)
- `/operator` — запрос на передачу оператору
- `/stats`, `/broadcast <текст>` — только для пользователей из `BOT_ADMIN_IDS`
- под каждым ответом — кнопки оценки (палец вверх / вниз), уходят на сервер через
  `POST /chats/{id}/messages/{msg_id}/feedback`

## Тесты

```bash
uv run pytest -q
```

Тесты идут без сети и без `OPENAI_API_KEY`: для сервера — `httpx.AsyncClient` с
`ASGITransport`, для клиента бота — `httpx.MockTransport`. Часть тестов касается
чат-ядра, модерации, лимита, маскирования персональных данных и сценариев бота.

## Архитектурные решения

- **Тонкий бот.** Бот не хранит историю и контекст — сервер единственная точка
  истины. Это позволит позже подключить веб-чат без дублирования логики.
- **Блокировки до старта потока.** Лимит запросов и модерация проверяются в
  обработчике маршрута, а не внутри генератора потока: после старта
  `text/event-stream` ответ уже летит как 200, и поменять статус на 403/429 уже
  нельзя.
- **Оповещения по модели «сервер пишет — бот забирает».** Сервер кладёт строку в
  таблицу `alerts`, бот раз в несколько секунд её вычитывает и шлёт в админ-чат.
  Отдельный брокер сообщений не нужен — Postgres уже есть; доставка
  гарантируется отметкой `acked_at`.
- **Лимит запросов — фиксированное окно в минуту.** Атомарный
  `INSERT … ON CONFLICT DO UPDATE count+1` на ключ
  `(owner_external_id, kind, bucket)`, где `bucket` — минута. Без блокировок и
  гонок между воркерами.
- **Приём медиа без отдельных вызовов.** Изображения уходят частью контента в
  основной `chat.completions.create`, голос распознаётся через Whisper.

## Конфиг (см. `.env.example`)

Переменные с `__` — это вложенные секции pydantic-settings:
`LLM__OPENAI_API_KEY` → `Settings.llm.openai_api_key`.
