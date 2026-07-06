### Управление изменениями для реляционной базы данных
- Используем [Alembic](https://alembic.sqlalchemy.org/en/latest/tutorial.html) -> SQLAlchemy
1. В корне проекта инициализируем проект Alembic
```bash
alembic init migrations
```
Это создаст файл alembic.ini в корне и папку migrations/.

2. Настром динамическое подключение к БД & подключим наши модели SQLAlchemy в migrations/env.py
```pyton
from app.chat.repositories.pg_models import Base
from app.core.config import get_settings

# URL из настроек
settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url)

target_metadata = Base.metadata
```
3. Найдите функцию run_migrations_online(). Перепишите её с использованием асинхронного движка примерно так
```python
import asyncio
from logging.config import fileConfig
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config # Важный импорт
from alembic import context

# ... (ваш остальной код, target_metadata и настройки логов остаются без изменений) ...

def do_run_migrations(connection):
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
    )

    with context.begin_transaction():
        context.run_migrations()

async def run_migrations_online() -> None:
    """Запуск миграций в 'online' режиме (с подключением к БД)."""
    
    # Создаем асинхронный движок вместо синхронного
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    # Используем run_sync для запуска синхронного контекста Alembic в асинхронной среде
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()

if context.is_offline_mode():
    run_migrations_offline()
else:
    # Запускаем асинхронную функцию через event loop
    asyncio.run(run_migrations_online())
```
4. Временно сделаем доступной postgresql пробросим порт на localhost:5432
5. Создаем миграцию
```bash
alembic revision --autogenerate -m "Initial migration"
```
6. Накатить базу в контейнер после build app image
```bash
docker compose exec app alembic upgrade head
```