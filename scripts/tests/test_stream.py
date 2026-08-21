#!/usr/bin/env python3
"""
Тест отключения thinking через extra_body
"""

import asyncio
import json

import httpx


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

    test_cases = [
        ("1. extra_body", payload_1),
        ("2. chat_template_kwargs в корне", payload_2),
        ("3. reasoning_effort='none'", payload_3),
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
            print(f"❌ Ошибка: {e}")

        await asyncio.sleep(0.5)


if __name__ == "__main__":
    asyncio.run(test_thinking_off())
