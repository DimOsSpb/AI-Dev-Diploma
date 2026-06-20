import asyncio
import time

import app.prompts.loader as loader
from app.core.config import Settings
from app.core.logging import configure_logging
from app.services.llm import LLMClient
from app.services.llm_sync import SyncLLMClient
from loguru import logger
from openai.types.chat import ChatCompletionMessageParam

settings = Settings()
configure_logging(settings)
history: list[ChatCompletionMessageParam] = []
prompts = [f"Proxmox - какая команда проверки статуса vm 1{i:0d}?" for i in range(20)]

sync_client = SyncLLMClient(settings)


def truncate(text: str, width: int = 30) -> str:
    return text if len(text) <= width else text[: width - 3] + "..."


def run_sync() -> float:
    print("=== Start Sync TEST ===")

    started = time.perf_counter()

    for i, prompt in enumerate(prompts, start=1):
        sys_p = loader.build_system_prompt("syncLMMTest")

        messages = loader.build_answer_messages(
            sys_p,
            history,
            prompt,
        )

        res = sync_client.complete(messages)

        elapsed = time.perf_counter() - started

        print(f"[P:{i:02d}] {elapsed:.2f}s\r", end="")
        logger.info(
            "sync.llm.call duration_ms={:.2f} model={} prompt_chars={} status={}",
            elapsed,
            res.model,
            len(prompt),
            "success",
        )

    total = time.perf_counter() - started

    print(f"=== End Sync TEST === {total:.2f}s")

    return total


async def run_async(async_client: LLMClient, concurrency: int) -> float:
    print(f"=== Start Async TEST c={concurrency} ===")

    started = time.perf_counter()

    messages_batch = []

    for prompt in prompts:
        sys_p = loader.build_system_prompt("asyncLMMTest")

        messages_batch.append(
            loader.build_answer_messages(
                sys_p,
                history,
                prompt,
            )
        )

    results = await async_client.batch_chat(
        messages_batch,
        concurrency=concurrency,
    )

    total = time.perf_counter() - started

    ok = sum(1 for r in results if not isinstance(r, Exception))

    print(
        f"=== End Async TEST c={concurrency} time={total:.2f}s ok={ok}/{len(results)}"
    )

    return total


sync_time = 0  # run_sync()


async def main():
    async_client = LLMClient(settings)

    async_1 = await run_async(async_client, 1)
    async_5 = await run_async(async_client, 5)
    async_10 = await run_async(async_client, 10)

    print()
    print("===== SUMMARY =====")
    print(f"Sync     : {sync_time:.2f}s")
    print(f"Async x1 : {async_1:.2f}s")
    print(f"Async x5 : {async_5:.2f}s")
    print(f"Async x10: {async_10:.2f}s")


asyncio.run(main())
