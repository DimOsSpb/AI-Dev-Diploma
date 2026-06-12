# Мультимодальный Support Assistant CLI

Простое CLI-приложение для практики блока 2.6. Помощник отвечает только по теме сервиса `InfraAssist`, умеет классифицировать обращения, кешировать FAQ в Redis, делать retry (tenacity) и fallback, логировать диалог (loguru) и поддерживает базовые команды.

## Структура

```text
b06_mm_suppassist/
  .env.example            # Примеры переменных окружения
  config.py               # Конфигурация
  cli.py                  # точка входа
  models.py               # все dataclass-ы и type alias-ы
  core/
    assistant.py          # сценарий диалога и команды CLI
    classification.py     # категории и правила эскалации
  infrastructure/
    tts/piper             # Для озвучивания речи
    cache.py              # Redis-кеш
    llm.py                # retry (tenacity) + fallback для LLM
    stt.py                # Речь -> текст
    tts.py                # Текст -> речь
  prompts/
    loader.py             # загрузка prompt-файлов
    system_prompt.txt
    classifier_system_prompt.txt
    classifier_few_shots.json
    service_facts.txt
```

## Возможности

- `System prompt` в формате РРФО: роль, правила, факты, ограничения
- `Few-shot` в классификаторе: 4 примера
- `Retry`: tenacity с экспоненциальной задержкой (RateLimitError, APIStatusError)
- `Fallback`: primary → fallback → эскалация на оператора
- `Кеширование`: Redis-кеш (TTL по умолчанию 1 час)
- `CLI`: `/clear`, `/clear_cache`, `/reset_redis_stats`, `/stats`, `/quit`, `transcribe`, `/voice`, `/speak`
- `Логирование`: loguru (файл + консоль)
- `Все провайдеры` через OpenAI-совместимый API (OpenAI, Groq, OpenRouter, Ollama)
- `История`: последние 10 сообщений для контекста
- `Классификация`: `faq`, `technical`, `complaint`, `escalation`
- `Эскалация`: ответ `Передаю вопрос специалисту`
- Голосовой ввод -> STT→LLM→TTS -> озвучивание ответов в реальном времени

## Запуск

Из папки:

```bash
python __main__.py
```

Предварительно должен быть запущен Redis:

```bash
redis-server
# или через Docker:
docker run -d --name redis:latest -p 6379:6379 redis:alpine
```

Для сохранения кеша после перезапуска Redis включите RDB или AOF (`appendonly yes` в `redis.conf`).

## Переменные окружения

### Основной провайдер
- `API_KEY` — API-ключ (OpenAI, Groq, OpenRouter и т.д.)
- `BASE_URL` — base URL (по умолчанию OpenAI; для Groq: `https://api.groq.com/openai/v1`)

### Fallback-провайдер
- `FALLBACK_API_KEY` — API-ключ fallback (по умолчанию `ollama`)
- `FALLBACK_BASE_URL` — base URL fallback (по умолчанию `http://localhost:11434/v1`)
- `FALLBACK_MODEL` — модель fallback (по умолчанию `qwen3:8b`)

### Redis
- `REDIS_HOST` — хост Redis, по умолчанию `localhost`
- `REDIS_PORT` — порт Redis, по умолчанию `6379`
- `REDIS_TTL` — время жизни кеша в секундах, по умолчанию `3600`

### Прочее
- `SUPPORT_SERVICE_NAME` — имя сервиса, по умолчанию `InfraAssist`

Без ключей приложение тоже работает: классификация работает эвристикой, при недоступности обоих провайдеров — эскалация на оператора.

## Быстрый сценарий проверки

1. `Сколько стоит тариф Pro?`
2. Повторите тот же вопрос и проверьте `cache` в строке статуса.
3. `Не могу загрузить файл, ошибка 413`
4. `Позовите менеджера`
5. `/stats`
6. `/clear_cache`
7. `/reset_redis_stats`
