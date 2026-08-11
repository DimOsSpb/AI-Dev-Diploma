"""
Модуль с реализацией трёх стратегий chunking для RAG на основе LlamaIndex:
1. fixed_size - TokenTextSplitter с chunk_size=512, overlap=64 (baseline)
2. recursive - SentenceSplitter с paragraph_separator="\n\n" (эквивалент RecursiveCharacterTextSplitter)
3. semantic - SemanticSplitterNodeParser на основе embedding similarity

Все стратегии возвращают список объектов Node из LlamaIndex или Chunk.
All strategies return a list of Node objects from LlamaIndex or Chunk.
"""

import random
import re
from dataclasses import dataclass
from typing import Any

from llama_index.core import Document as LlamaDocument
from llama_index.core.node_parser import (
    SemanticSplitterNodeParser,
    SentenceSplitter,
    TokenTextSplitter,
)


@dataclass
class Chunk:
    """Текстовый чанк с метаданными."""

    text: str
    index: int
    doc_id: str | None = None

    def to_node(self) -> LlamaDocument:
        return LlamaDocument(
            text=self.text,
            metadata={
                "doc_id": self.doc_id,
                "chunk_index": self.index,
            },
        )


class FixedSizeChunker:
    """
    Стратегия 1: fixed_size - TokenTextSplitter с chunk_size=512, overlap=64.

    Базовая реализация без учёта границ предложений (эквивалент LangChain TokenTextSplitter).
    Режет текст по фиксированной длине в токенах/символах.
    """

    def __init__(self, *, chunk_size: int = 512, chunk_overlap: int = 64) -> None:
        if chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap должен быть меньше chunk_size")

        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self._splitter = TokenTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

    def split(self, document: str, doc_id: str | None = None) -> list[Chunk]:
        """Разделить документ на чанки фиксированного размера."""
        nodes = self._splitter.get_nodes_from_documents([LlamaDocument(text=document)])
        chunks = []

        for i, node in enumerate(nodes):
            chunks.append(
                Chunk(text=getattr(node, "text", ""), index=i, doc_id=doc_id or None)
            )

        return chunks

    @property
    def params(self) -> dict[str, Any]:
        """Параметры сплиттера."""
        return {
            "chunk_size": self.chunk_size,
            "chunk_overlap": self.chunk_overlap,
            "type": "fixed_size",
        }


class RecursiveChunker:
    """
    Стратегия 2: recursive - SentenceSplitter с paragraph_separator="\n\n".

    Эквивалент LangChain RecursiveCharacterTextSplitter, но использует LlamaIndex подход.
    Разделяет текст по абзацам и границам предложений для более осмысленных чанков.
    """

    def __init__(
        self,
        *,
        chunk_size: int = 500,
        chunk_overlap: int = 64,
        paragraph_separator: str = "\n\n",
        sentence_separator: str = ".\n",
    ) -> None:
        """Инициализация с параметрами для разделения на предложения."""

        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.paragraph_separator = paragraph_separator

        # Создаем SentenceSplitter через LlamaIndex API
        self._sentence_splitter = SentenceSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

    def split(self, document: str, doc_id: str | None = None) -> list[Chunk]:
        """Разделить документ на осмысленные чанки с учётом границ предложений."""

        if not doc_id:
            # Используем индекс документа как ID для отслеживания источника
            doc_id = f"doc_{random.randint(10000, 99999)}"

        # Сначала разбиваем по абзацам (высокоуровневое разделение)
        paragraphs = (
            re.split(r"\n\s*\n", document) if "\n\n" in document else [document]
        )

        all_chunks = []
        for i, paragraph in enumerate(paragraphs):
            if len(paragraph.strip()) <= self.chunk_size:
                # Маленький абзац - добавляем как есть (или режем по предложениям)
                sentences = re.split(r"(?<=[.!?])\n+", paragraph)
                for sentence in sentences:
                    if sentence.strip() and len(sentence.strip()) > 30:
                        chunks = self._split_by_size(
                            sentence.strip(), max_chunk_size=self.chunk_size
                        )
                        for chunk_text in chunks:
                            all_chunks.append(
                                Chunk(
                                    text=chunk_text,
                                    index=len(all_chunks),
                                    doc_id=doc_id,
                                )
                            )
            else:
                # Большой абзац - режем по размеру с учётом предложений
                sentences = self._split_by_sentences(paragraph)
                current_idx = len(all_chunks)

                for sentence in sentences:
                    if (
                        len(sentence.strip()) > self.chunk_size * 0.3
                        and len(sentence.strip()) < self.chunk_size
                    ):
                        all_chunks.append(
                            Chunk(
                                text=sentence.strip(), index=current_idx, doc_id=doc_id
                            )
                        )
                        current_idx += 1
                    elif len(sentence.strip()) > self.chunk_size:
                        chunks = self._split_by_size(
                            sentence.strip(), max_chunk_size=self.chunk_size
                        )
                        for chunk_text in chunks:
                            all_chunks.append(
                                Chunk(text=chunk_text, index=current_idx, doc_id=doc_id)
                            )
                            current_idx += 1

        return all_chunks

    def _split_by_sentences(self, text: str) -> list[str]:
        """Разделить текст на осмысленные предложения."""
        # Русский язык: разделяем по . ! ? ... с сохранением контекста
        sentences = re.split(r"(?<=[.!?…])(?=\s+[\wА-ЯЁ])", text)
        return [s.strip() for s in sentences if len(s.strip()) > 20]

    def _split_by_size(self, text: str, max_chunk_size: int = 500) -> list[str]:
        """Разделить текст по размеру с сохранением границ предложений."""
        if len(text) <= max_chunk_size:
            return [text] if text.strip() else []

        chunks = []
        start = 0

        while start < len(text):
            end = min(start + max_chunk_size, len(text))

            # Поиск ближайшей границы предложения перед концом чанка
            for split_point in range(end - 1, max(start + 50, end - 20), -1):
                if text[split_point - 1 : split_point] in ".!?…":
                    chunk_text = text[start:split_point].strip()
                    if len(chunk_text) > 30:
                        chunks.append(chunk_text)
                    start = split_point
                    break
            else:
                # Если не нашли границу, режем прямо
                chunk_text = text[start:end].strip()[:max_chunk_size]
                if chunk_text and len(chunk_text) > 30:
                    chunks.append(chunk_text)

                start = end

        return chunks

    @property
    def params(self) -> dict[str, Any]:
        """Параметры сплиттера."""
        return {
            "chunk_size": self.chunk_size,
            "chunk_overlap": self.chunk_overlap,
            "paragraph_separator": self.paragraph_separator,
            "type": "recursive",
        }


class SemanticChunker:
    """
    Стратегия 3: semantic - SemanticSplitterNodeParser.

    Разбивает текст там, где embeddings становятся разными (по 95-му перцентилю similarity).
    Требует embed_model для вычисления векторных представлений сегментов.
    """

    def __init__(
        self,
        *,
        buffer_size: int = 1,
        breakpoint_percentile_threshold: int = 95,
        embed_model=None,  # Embedding model instance from app configuration
        chunk_size: int
        | None = None,  # Фоллбек к размеру сегмента перед semantic split
        chunk_overlap: int = 64,  # Переопределение chunk_overlap для фоллбэка
    ) -> None:
        """Инициализация с параметрами SemanticSplitterNodeParser."""

        self.buffer_size = buffer_size
        self.breakpoint_percentile = breakpoint_percentile_threshold
        self.embed_model = embed_model
        self.chunk_size = chunk_size or 500
        self.chunk_overlap = chunk_overlap

        # Создаем сплиттер через LlamaIndex API
        if self.embed_model is not None and hasattr(self.embed_model, "get_embedding"):
            # Модель с методом get_embedding (как в app.services.embeddings)
            self._semantic_splitter = SemanticSplitterNodeParser(
                breakpoint_percentile_threshold=breakpoint_percentile_threshold,
                buffer_size=buffer_size,
                embed_model=self.embed_model,  # Передаем модель для вычисления эмбеддингов
            )
            self._use_embeddings = True
        else:
            # Фоллбек на SentenceSplitter при отсутствии embeddings
            self._semantic_splitter = SentenceSplitter(
                chunk_size=self.chunk_size,
                chunk_overlap=self.chunk_overlap,
            )
            self._use_embeddings = False

    def split(self, document: str, doc_id: str | None = None) -> list[Chunk]:
        """Разделить документ на осмысленные сегменты."""

        if not document or len(document.strip()) < 10:
            return [
                Chunk(text=document.strip() if document else "", index=0, doc_id=doc_id)
            ]

        chunks = []

        # Используем get_nodes_from_documents для обоих типов сплиттеров
        nodes = self._semantic_splitter.get_nodes_from_documents([
            LlamaDocument(text=document)
        ])

        for i, node in enumerate(nodes):
            chunks.append(
                Chunk(
                    text=getattr(node, "text", ""),
                    index=i,
                    doc_id=doc_id,
                )
            )

        return chunks

    def split_fallback(self, text: str) -> list[Chunk]:
        """Фоллбек splitter без embeddings - разбивает текст по структуре."""
        # Простой семантический сплит на основе структуры текста (заголовки, списки)
        text = text.strip()

        # Разбиваем по крупным разделителям (заголовки markdown, секции)
        sections = re.split(r"(#+\s+\w+|\n{3,})", text, flags=re.MULTILINE)

        chunks = []
        current_chunk = ""

        for section in sections:
            if not section.strip() or len(section) < 10:
                continue

            # Добавляем к текущему чанку если он есть и небольшой
            if current_chunk and len(current_chunk) + len(section) <= 500:
                current_chunk += " " + section
            else:
                if current_chunk.strip():
                    chunks.append(Chunk(text=current_chunk.strip(), index=len(chunks)))

                # Новый чанк с разделителем
                separator = section.strip() if not re.match(r"#+", section) else ""
                if section.startswith("#"):
                    separator = "\n" + section
                elif len(section) > 20:
                    separator = "\n\n" + section[:50] + "..."

                current_chunk = separator

        if current_chunk.strip():
            chunks.append(Chunk(text=current_chunk.strip(), index=len(chunks)))

        return chunks

    @property
    def params(self) -> dict[str, Any]:
        """Параметры сплиттера."""
        return {
            "buffer_size": self.buffer_size,
            "breakpoint_percentile_threshold": self.breakpoint_percentile,
            "embed_model_type": type(self.embed_model).__name__
            if self.embed_model
            else None,
            "type": "semantic",
        }


def get_chunker(
    strategy: str = "fixed_size", **kwargs
) -> FixedSizeChunker | RecursiveChunker | SemanticChunker:
    """
    Factory function для получения chunker по имени стратегии.

    Args:
        strategy: Один из ['fixed_size', 'recursive', 'semantic']
        **kwargs: Параметры конкретного chunker

    Returns:
        Объект соответствующего chunker

    Raises:
        ValueError: Если неизвестная стратегия
    """
    strategies = {
        "fixed_size": FixedSizeChunker,
        "recursive": RecursiveChunker,
        "semantic": SemanticChunker,
    }

    if strategy not in strategies:
        raise ValueError(
            f"Неизвестная стратегия chunking: {strategy}. "
            f"Доступны: {list(strategies.keys())}"
        )

    return strategies[strategy](**kwargs)


# Aliases для удобства
FixedSize = FixedSizeChunker
Recursive = RecursiveChunker
Semantic = SemanticChunker
