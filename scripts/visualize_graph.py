"""Сохраняет Mermaid-схему кастомного графа агента в `docs/agent-graph-custom.mmd`.

Структура графа не зависит от реального API-ключа: модель строится офлайн,
сеть не дёргается. Файл открывается в mermaid.live.

    uv run python -m scripts.visualize_graph
"""

import sys
from pathlib import Path

from langchain_openai import ChatOpenAI

from app.core.ai.catalog import get_catalog
from app.core.config import get_settings

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agents.graph import build_custom_graph
from app.agents.tools import multiply


def main() -> None:
    settings = get_settings()
    catalog = get_catalog()

    config = catalog.get_client_config(
        model_name=settings.llm.model,
        endpoint_name=settings.llm.endpoint,
    )

    api_key = "None"
    if config.api_key:
        api_key = config.api_key.get_secret_value()

    model = ChatOpenAI(
        base_url=config.url,
        model=config.model,
        temperature=0,
        api_key=api_key,  # pyright: ignore[reportArgumentType]
    )

    graph = build_custom_graph(model, [multiply])
    mermaid = graph.get_graph().draw_mermaid()

    out = Path("docs/agent-graph-custom.mmd")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(mermaid, encoding="utf-8")
    print(f"saved {out}")


if __name__ == "__main__":
    main()
