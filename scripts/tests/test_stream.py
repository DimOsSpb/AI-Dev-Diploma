#!/usr/bin/env python3
"""
Тест отключения thinking через extra_body
"""

import asyncio
import json

import httpx
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from openai import AsyncOpenAI


async def test_thinking_off():
    url = "http://172.16.30.12:8080/v1/chat/completions"

    # Вариант 1: через extra_body (как рекомендуют в документации)
    payload_1 = {
        "model": "Qwen3.5-9B-Q5_K_M",
        "messages": [{"role": "user", "content": "Count from 1 to 5"}],
        "stream": True,
        "max_tokens": 30,
        "temperature": 0.1,
        "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
    }

    # Вариант 2: chat_template_kwargs прямо в корне запроса
    payload_2 = {
        "model": "Qwen3.5-9B-Q5_K_M",
        "messages": [{"role": "user", "content": "Count from 1 to 5"}],
        "stream": True,
        "max_tokens": 30,
        "temperature": 0.1,
        "chat_template_kwargs": {"enable_thinking": False},
    }

    # Вариант 3: enable_thinking через reasoning_effort (как в OpenAI)
    payload_3 = {
        "model": "Qwen3.5-9B-Q5_K_M",
        "messages": [{"role": "user", "content": "Count from 1 to 5"}],
        "stream": True,
        "max_tokens": 30,
        "temperature": 0.1,
        "reasoning_effort": "none",
    }

    # Вариант 4: как вариант 1, но с tools в payload — проверяем гипотезу,
    # что именно наличие tool definitions форсирует thinking независимо от
    # enable_thinking (это то, что реально отправляет агент в проде).
    dummy_tool = {
        "type": "function",
        "function": {
            "name": "search_knowledge_base",
            "description": "Поиск по базе знаний",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    }
    payload_4 = {
        "model": "Qwen3.5-9B-Q5_K_M",
        "messages": [{"role": "user", "content": "Count from 1 to 5"}],
        "stream": True,
        "max_tokens": 30,
        "temperature": 0.1,
        "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
        "tools": [dummy_tool],
    }

    test_cases = [
        ("1. extra_body", payload_1),
        ("2. chat_template_kwargs в корне", payload_2),
        ("3. reasoning_effort='none'", payload_3),
        ("4. extra_body + tools (как у агента)", payload_4),
    ]

    for name, payload in test_cases:
        print("\n" + "=" * 80)
        print(f"🧪 Тест: {name}")
        print("=" * 80)
        print(f"Payload: {json.dumps(payload, indent=2)}")
        print("\n🔄 Streaming...")
        print("-" * 40)

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                async with client.stream("POST", url, json=payload) as response:
                    print(f"📡 Status: {response.status_code}\n")

                    if response.status_code != 200:
                        error_text = await response.aread()
                        print(f"❌ Error: {error_text.decode()[:500]}")
                        continue

                    has_reasoning = False
                    has_content = False
                    chunk_count = 0

                    async for line in response.aiter_lines():
                        if not line or not line.startswith("data: "):
                            continue

                        data = line[6:]
                        if data == "[DONE]":
                            print("\n✅ Done!")
                            break

                        try:
                            chunk = json.loads(data)
                            choices = chunk.get("choices", [])
                            if choices:
                                delta = choices[0].get("delta", {})

                                reasoning = delta.get("reasoning_content", "")
                                content = delta.get("content", "")

                                if reasoning:
                                    has_reasoning = True
                                    chunk_count += 1
                                    print(
                                        f"[{chunk_count}] [reasoning] {reasoning}",
                                        end="",
                                        flush=True,
                                    )
                                if content:
                                    has_content = True
                                    chunk_count += 1
                                    print(
                                        f"[{chunk_count}] [content] {content}",
                                        end="",
                                        flush=True,
                                    )

                        except json.JSONDecodeError:
                            continue

                    print("\n" + "-" * 40)
                    print("📊 Результат:")
                    print(
                        f"  reasoning_content: {'✅ ЕСТЬ' if has_reasoning else '❌ НЕТ'}"
                    )
                    print(f"  content: {'✅ ЕСТЬ' if has_content else '❌ НЕТ'}")

                    if has_content and not has_reasoning:
                        print("🎉 УСПЕХ! Мышление отключено!")
                    elif has_reasoning:
                        print("⚠️ Мышление всё еще включено")
                    else:
                        print("❌ Нет никакого контента")

        except Exception as e:
            print(f"❌ Ошибка ({type(e).__name__}): {e!r}")

        await asyncio.sleep(0.5)


async def test_via_openai_sdk():
    """Проверяет, что реально уходит «на проводе», когда extra_body задаётся
    через сам OpenAI SDK (тот самый путь, что использует app/main.py и rag_llm.py).
    OpenAI SDK делает реальный top-level merge extra_body в JSON-тело запроса,
    в отличие от ручного httpx-запроса с буквальным ключом "extra_body" в
    варианте 1/4 выше — там это неправильная эмуляция.
    """
    client = AsyncOpenAI(
        base_url="http://172.16.30.12:8080/v1",
        api_key="none",
    )

    dummy_tool = {
        "type": "function",
        "function": {
            "name": "search_knowledge_base",
            "description": "Поиск по базе знаний",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    }

    cases = [
        ("5. SDK extra_body, без tools", {}, False),
        ("6. SDK extra_body, с tools", {}, True),
    ]

    for name, _extra, with_tools in cases:
        print("\n" + "=" * 80)
        print(f"🧪 Тест: {name}")
        print("=" * 80)

        kwargs: dict = dict(
            model="Qwen3.5-9B-Q5_K_M",
            messages=[{"role": "user", "content": "Count from 1 to 5"}],
            stream=True,
            max_tokens=30,
            temperature=0.1,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
        if with_tools:
            kwargs["tools"] = [dummy_tool]

        has_reasoning = False
        has_content = False
        chunk_count = 0
        try:
            stream = await client.chat.completions.create(**kwargs)
            async for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                reasoning = getattr(delta, "reasoning_content", None)
                content = getattr(delta, "content", None)
                if reasoning:
                    has_reasoning = True
                    chunk_count += 1
                    print(
                        f"[{chunk_count}] [reasoning] {reasoning}", end="", flush=True
                    )
                if content:
                    has_content = True
                    chunk_count += 1
                    print(f"[{chunk_count}] [content] {content}", end="", flush=True)
            print("\n" + "-" * 40)
            print("📊 Результат:")
            print(f"  reasoning_content: {'✅ ЕСтЬ' if has_reasoning else '❌ НЕТ'}")
            print(f"  content: {'✅ ЕСтЬ' if has_content else '❌ НЕТ'}")
            if has_content and not has_reasoning:
                print("🎉 Успех! Мышление отключено!")
            elif has_reasoning:
                print("⚠️ Мышление всё ещё включено")
        except Exception as e:
            print(f"❌ Ошибка ({type(e).__name__}): {e!r}")

        await asyncio.sleep(0.5)

    await client.close()


async def test_via_langchain():
    """То же самое, но через langchain_openai.ChatOpenAI — тот класс, который
    реально использует агент в app/main.py. Проверяет, действительно ли
    LangChain ломает extra_body иначе, чем голый openai SDK.
    """
    from langchain_openai import ChatOpenAI

    @tool
    def search_knowledge_base(query: str) -> str:
        """Поиск по базе знаний."""
        return "stub"

    cases = [
        ("7. LangChain extra_body, без tools", False),
        ("8. LangChain extra_body, с bind_tools", True),
    ]

    for name, with_tools in cases:
        print("\n" + "=" * 80)
        print(f"🧪 Тест: {name}")
        print("=" * 80)

        model = ChatOpenAI(
            base_url="http://172.16.30.12:8080/v1",
            model="Qwen3.5-9B-Q5_K_M",
            temperature=0.1,
            max_completion_tokens=30,
            api_key="none",  # pyright: ignore[reportArgumentType]
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
        if with_tools:
            model = model.bind_tools([search_knowledge_base])

        has_reasoning = False
        has_content = False
        chunk_count = 0
        try:
            async for chunk in model.astream([HumanMessage("Count from 1 to 5")]):
                reasoning = (
                    chunk.additional_kwargs.get("reasoning_content")
                    if hasattr(chunk, "additional_kwargs")
                    else None
                )
                content = chunk.content if hasattr(chunk, "content") else None
                if reasoning:
                    has_reasoning = True
                    chunk_count += 1
                    print(
                        f"[{chunk_count}] [reasoning] {reasoning}", end="", flush=True
                    )
                if content:
                    has_content = True
                    chunk_count += 1
                    print(f"[{chunk_count}] [content] {content}", end="", flush=True)
            print("\n" + "-" * 40)
            print("📊 Результат:")
            print(f"  reasoning_content: {'✅ ЕСтЬ' if has_reasoning else '❌ НЕТ'}")
            print(f"  content: {'✅ ЕСтЬ' if has_content else '❌ НЕТ'}")
            if has_content and not has_reasoning:
                print("🎉 Успех! Мышление отключено!")
            elif has_reasoning:
                print("⚠️ Мышление всё ещё включено")
        except Exception as e:
            print(f"❌ Ошибка ({type(e).__name__}): {e!r}")

        await asyncio.sleep(0.5)


if __name__ == "__main__":
    asyncio.run(test_thinking_off())
    asyncio.run(test_via_openai_sdk())
    asyncio.run(test_via_langchain())
