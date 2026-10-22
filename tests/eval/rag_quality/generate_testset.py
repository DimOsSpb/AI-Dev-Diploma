"""
Генерация golden dataset через RAGAS TestsetGenerator.

Создаёт тестовые пары вопрос-ответ на основе корпуса данных.
"""

import asyncio
import json
import logging
from pathlib import Path

from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from llama_index.core import SimpleDirectoryReader
from pydantic import SecretStr
from ragas.embeddings import LangchainEmbeddingsWrapper
from ragas.llms import LangchainLLMWrapper
from ragas.testset import Testset, TestsetGenerator

from app.core.ai.catalog import get_catalog
from app.core.config import get_settings

logger = logging.getLogger(__name__)

DATASET_SIZE = 30


async def main() -> None:
    """Главная функция."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    settings = get_settings()
    catalog = get_catalog()

    # ------------------------------------------------------------------
    # LLM
    # ------------------------------------------------------------------

    llm_config = catalog.get_client_config(
        model_name=settings.rag_llm_model,
        endpoint_name=settings.rag_llm_endpoint,
    )
    api_key = llm_config.api_key or SecretStr("local")
    llm = ChatOpenAI(
        model=llm_config.model,
        base_url=llm_config.url,
        api_key=api_key,
        temperature=0,
        extra_body={
            "chat_template_kwargs": {
                "enable_thinking": False,
            },
        },
    )

    ragas_llm = LangchainLLMWrapper(llm)

    # ------------------------------------------------------------------
    # Embeddings
    # ------------------------------------------------------------------

    embedding_config = catalog.get_client_config(
        model_name=settings.embedding_model,
        endpoint_name=settings.embedding_endpoint,
    )
    api_key = llm_config.api_key or SecretStr("local")
    embeddings = OpenAIEmbeddings(
        model=embedding_config.model,
        base_url=embedding_config.url,
        api_key=api_key,
    )

    ragas_embeddings = LangchainEmbeddingsWrapper(embeddings)

    # ------------------------------------------------------------------
    # Documents
    # ------------------------------------------------------------------

    reader = SimpleDirectoryReader(
        input_dir=str(settings.rag_data_dir),
        recursive=True,
    )

    llama_documents = reader.load_data()

    logger.info("Loaded %d documents", len(llama_documents))

    # RAGAS generate_with_langchain_docs() требует именно
    # langchain_core.documents.Document.
    #
    # Поэтому конвертируем LlamaIndex Document -> LangChain Document.
    from langchain_core.documents import Document as LangChainDocument

    documents = [
        LangChainDocument(
            page_content=document.text,
            metadata=document.metadata or {},
        )
        for document in llama_documents
    ]

    # ------------------------------------------------------------------
    # RAGAS
    # ------------------------------------------------------------------

    testset_gen = TestsetGenerator(
        llm=ragas_llm,
        embedding_model=ragas_embeddings,
    )

    testset = testset_gen.generate_with_langchain_docs(
        documents,
        testset_size=DATASET_SIZE,
    )

    if not isinstance(testset, Testset):
        raise RuntimeError(f"Expected Testset, got {type(testset).__name__}")

    testset_df = testset.to_pandas()

    logger.info(
        "Generated testset with %d questions",
        len(testset_df),
    )

    questions = [
        {"question": str(question)} for question in testset_df["user_input"].dropna()
    ]

    raw_path = Path("tests/eval/rag_quality/golden_dataset_raw.json")
    raw_path.parent.mkdir(parents=True, exist_ok=True)

    with raw_path.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "questions": questions,
                "generated_by": "RAGAS TestsetGenerator",
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    logger.info("Saved raw dataset to %s", raw_path)
    logger.info("Total questions: %d", len(questions))


if __name__ == "__main__":
    asyncio.run(main())
