"""Интерактивный CLI (REPL) для общения с ассистентом поддержки.

Принимает пользовательский ввод, обрабатывает команды CLI
и выводит ответ ассистента с метаданными (категория, источник, задержка).
"""

from __future__ import annotations

from infraassist.core.assistant import SupportAssistantApp
from infraassist.infrastructure.config import settings
from loguru import logger
from pydantic import ValidationError
from redis.exceptions import ConnectionError, TimeoutError


def main():

    try:
        # Логирование только в файл (убираем дефолтный вывод в stderr)
        logger.remove()
        logger.add(
            settings.log_path, format="{time} {message}", rotation="10 MB", level="INFO"
        )

        assistant = SupportAssistantApp(settings)
        assistant.cache.client.ping()
    except ValidationError as e:
        print(f"! {e.errors()[0]['msg']}")
        raise SystemExit(1)
    except (ConnectionError, TimeoutError) as e:
        print(f"! Redis недоступен: {e}")
        raise SystemExit(1)

    print(f"=== {settings.service_name} Support CLI ===")
    print(assistant._help())

    while True:
        try:
            user_input = input("\nВы: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nДо свидания!")
            return None

        if not user_input:
            continue

        # --- / команды ------------------------
        if user_input.startswith("/"):
            command_result = assistant.handle_command(user_input[1:])
            if command_result is None:
                print("До свидания!")
                return None
            if command_result == "":
                continue
            user_input = command_result

        voice = False
        if user_input.startswith("/v"):
            user_input = user_input[2:]
            voice = True

        response = assistant.respond(user_input)
        source = "cache" if response.from_cache else response.provider
        print(f"[{response.category} | {source} | {response.latency_seconds:.2f}с]")

        if voice:
            print("Озвучиваю...")
            assistant.speak(response.text)
        else:
            print(response.text)
