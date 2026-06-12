"""Главный модуль бизнес-логики ассистента поддержки.

Класс ``SupportAssistantApp`` оркестрирует весь цикл обработки запроса:
классификация → проверка кеша → вызов LLM (с retry/fallback) → эскалация →
ведение истории → логирование.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from uuid import uuid4

import sounddevice as sd
import soundfile as sf
from infraassist.core.classification import should_escalate
from infraassist.core.models import AssistantResponse, Category, SessionStats
from infraassist.infrastructure.cache import RedisCache
from infraassist.infrastructure.config import Settings
from infraassist.infrastructure.llm import FALLBACK_ANSWER, RobustLLMClient
from infraassist.infrastructure.stt import RobustSTTClient
from infraassist.infrastructure.tts import RobustTTSClient
from infraassist.prompts.loader import (
    build_answer_messages,
    build_classifier_messages,
    build_system_prompt,
)
from loguru import logger
from openai.types.chat import ChatCompletionMessageParam


@dataclass(frozen=True, slots=True)
class Command:
    name: str
    short: str
    params: str
    handler: Callable[[str | None], str | None]
    description: str


class SupportAssistantApp:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.system_prompt = build_system_prompt(settings.service_name)
        self.history: list[ChatCompletionMessageParam] = []
        self.failed_attempts = 0
        self.stats = SessionStats()

        self.cache = RedisCache(
            settings.redis_host, settings.redis_port, settings.redis_ttl
        )

        self.client = RobustLLMClient(settings)
        self.stt_client = RobustSTTClient(settings)
        self.tts_client = RobustTTSClient(settings)

        self.commands = [
            Command("clear", "c", "", self._cmd_clear, "Очисттка истории"),
            Command("clear_cache", "cc", "", self._cmd_clear_cache, "Очистка кеш"),
            Command(
                "reset_redis_stats",
                "rrs",
                "",
                self._cmd_reset_redis_stats,
                "Сброс статистики Redis",
            ),
            Command("stats", "s", "", self._cmd_stats, "Вывод статистики"),
            Command("quit", "q", "", self._cmd_quit, "Выход из приложения"),
            Command(
                "transcribe",
                "t",
                "<file> [вопрос]",
                self._cmd_transcribe,
                "Распознать речь из файла",
            ),
            Command(
                "speak",
                "sp",
                "",
                self._cmd_speak,
                "Голосовой вывод последнего ответа модели",
            ),
            Command(
                "voice",
                "v",
                "",
                self._cmd_voice,
                "Полностью голосовой pipeline (STT→LLM→TTS в реальном времени)",
            ),
        ]

    def _cmd_clear(self, param: str | None) -> str:
        self.history.clear()
        self.failed_attempts = 0
        print("История очищена.")
        return ""

    def _cmd_clear_cache(self, param: str | None) -> str:
        deleted = self.cache.clear()
        print(f"Кеш очищен. Удалено ключей: {deleted}.")
        return ""

    def _cmd_reset_redis_stats(self, param: str | None) -> str:
        self.cache.reset_stats()
        print("Статистика Redis сброшена.")
        return ""

    def _cmd_stats(self, param: str | None) -> str:
        cache_info = self.cache.stats()
        print(
            f"Запросов: {self.stats.total_queries} | "
            f"LLM вызовов: {self.stats.llm_calls} | "
            f"Токенов: {self.stats.total_tokens} | "
            f"Эскалаций: {self.stats.escalations} | "
            f"Redis: {cache_info['keys']} ключей, "
            f"hit rate: {cache_info['hit_rate']} "
            f"({cache_info['hits']}/{int(cache_info['hits']) + int(cache_info['misses'])})"  # noqa: E501
        )
        return ""

    def _cmd_quit(self, param: str | None) -> None:
        return None

    def _help(self) -> str:
        print("Доступные команды:")
        for c in self.commands:
            command = f"{c.name} {c.params}".strip()
            short = f"(/{c.short})"
            print(f"/{command:<27} {short:<6} - {c.description}")

        return ""

    # ── /voice — транскрипция аудио + ответ ─────────────────────
    def _cmd_transcribe(self, param: str | None) -> str:
        if param:
            parts = param.strip().split(maxsplit=1)
            audio_path = parts[0] if parts else ""
            question = parts[1] if len(parts) > 1 else ""
            if not os.path.isfile(audio_path):
                print(f"Файл не найден: {audio_path}")
                return ""
            print("Распознаю речь...")
            transcript = self.transcribe(audio_path)
            user_input = f"{question} {transcript}".strip() if question else transcript
            if not user_input:
                print("Не удалось распознать речь.")
                return ""
            print(f"Распознано: {transcript}")
            return user_input
        else:
            print("Файл не указан.")
            return ""

    # # ── /speak — озвучить последний ответ через TTS ─────────────
    def _cmd_speak(self, param: str | None) -> str:
        if not self.history:
            print("Нет ответов для озвучивания.")
            return ""

        last_answer = str(self.history[-1].get("content"))
        print("Генерирую аудио...")
        output = self.speak(last_answer)
        if output:
            print(f"Аудио сохранено: {output}")
            return ""
        else:
            print("Не удалось сгенерировать аудио.")
            return ""

    def _cmd_voice(self, param: str | None = None) -> str:
        print("Говорите...")
        audio_path = "input.wav"
        self.record(
            output_path=audio_path,
            duration=5,
        )
        transcript = self._cmd_transcribe(audio_path)
        if transcript == "":
            return ""
        return "/v" + transcript

    def handle_command(self, input: str) -> str | None:
        parts = input.strip().split(maxsplit=1)
        cmd_name = parts[0]
        param = parts[1] if len(parts) > 1 else None

        for cmd in self.commands:
            if cmd_name in (cmd.name, cmd.short):
                return cmd.handler(param)

        print(self._help())
        return ""

    def respond(self, user_message: str) -> AssistantResponse:
        started_at = time.perf_counter()
        self.stats.total_queries += 1

        category = self.client.classify(build_classifier_messages(user_message))
        if category == Category.ESCALATION:
            self.failed_attempts += 1
        if should_escalate(
            category=category,
            failed_attempts=self.failed_attempts,
        ):
            self.stats.escalations += 1
            self.failed_attempts = 0
            text = f"Передаю вопрос специалисту. Номер обращения: {uuid4().hex[:8].upper()}."  # noqa: E501
            latency = time.perf_counter() - started_at
            self._log(
                user_message, category, text, 0, latency, False, "router", "escalation"
            )
            return AssistantResponse(
                text, category, False, latency, "router", "escalation", False
            )

        cached = self.cache.get(user_message)
        if cached is not None:
            self.stats.cache_hits += 1
            self._remember_turn(user_message, str(cached))
            latency = time.perf_counter() - started_at
            self._log(
                user_message, category, str(cached), 0, latency, True, "cache", "cache"
            )
            return AssistantResponse(
                str(cached), category, True, latency, "cache", "cache", False
            )

        self.stats.cache_misses += 1
        self.stats.llm_calls += 1
        messages = build_answer_messages(self.system_prompt, self.history, user_message)
        result = self.client.answer(messages)
        self.cache.set(user_message, result.text)

        if result.text.strip() == FALLBACK_ANSWER:
            self.failed_attempts += 1
        else:
            self.failed_attempts = 0

        latency = time.perf_counter() - started_at
        self._remember_turn(user_message, result.text)
        if result.tokens:
            self.stats.total_tokens += result.tokens
        self._log(
            user_message,
            category,
            result.text,
            result.tokens,
            latency,
            False,
            result.provider,
            result.model,
        )
        return AssistantResponse(
            result.text,
            category,
            False,
            latency,
            result.provider,
            result.model,
            result.used_fallback,
        )

    def record(
        self,
        output_path: str,
        duration: int = 5,
        sample_rate: int = 16000,
    ) -> str:
        recording = sd.rec(
            int(duration * sample_rate),
            samplerate=sample_rate,
            channels=2,
            dtype="int16",
            device=5,
        )

        sd.wait()

        sf.write(output_path, recording, sample_rate)

        return output_path

    def transcribe(self, audio_path: str) -> str:
        """STT: аудиофайл → текст."""
        return self.stt_client.transcribe(audio_path)

    def speak(self, text: str, output_path: str = "response.mp3") -> str:
        """TTS: текст → аудиофайл."""
        result = self.tts_client.synthesize(
            text,
            output_path,
        )
        if result:
            self.tts_client.play(result)
            return result
        return "Ошибка TTS."

    def _remember_turn(self, user_message: str, answer: str) -> None:
        self.history.append({"role": "user", "content": user_message})
        self.history.append({"role": "assistant", "content": answer})
        if len(self.history) > self.settings.history_limit:
            self.history = self.history[-self.settings.history_limit :]

    def _log(
        self,
        user_message: str,
        category: str,
        answer: str,
        tokens: int | None,
        latency_seconds: float,
        from_cache: bool,
        provider: str,
        model: str,
    ) -> None:
        logger.info(
            "{cat} | {prov}/{mod} | {tok} tok | {lat:.3f}s | cache={cache} | Q: {msg} | A: {ans}",  # noqa: E501
            cat=category,
            prov=provider,
            mod=model,
            tok=tokens,
            lat=latency_seconds,
            cache=from_cache,
            msg=user_message[:100],
            ans=answer[:100],
        )
