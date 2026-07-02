# app/core/context.py
from fastapi import FastAPI

# Обычная переменная уровня модуля (глобальный синглтон приложения)
_global_app: FastAPI | None = None


def get_current_app() -> FastAPI:
    """Возвращает глобальный объект app (работает на уровне всего приложения)."""
    if _global_app is None:
        # На случай запуска изолированных юнит-тестов, создаем пустой инстанс,
        # чтобы избежать падения с ошибкой
        return FastAPI()
    return _global_app


def set_current_app(app: FastAPI):
    """Фиксирует объект app на глобальном уровне при старте сервера."""
    global _global_app
    _global_app = app
