from typing import cast

from .adapters.factory import create_adapter
from .cache import create_cache
from .models import EmbeddingModelConfig


class Vectorizer:
    def __init__(
        self,
        config: EmbeddingModelConfig,
    ):

        self.config = config

        self.model = create_adapter(config)

        self.cache = create_cache()

    # texts: list[str] - Это куски документа(ов) - осмысленные куки текста (предложения, абзацы...)
    # Разбитые предварительно на chunks через специализированные TextSplitter
    def embed_texts(
        self,
        texts: list[str],
    ) -> list[list[float]]:

        result: list[list[float] | None] = [None for _ in texts]

        missing_texts: list[str] = []
        missing_indexes: list[int] = []

        # 1. Проверяем cache

        for index, text in enumerate(texts):
            cached = self.cache.get(
                model=self.config.name,
                dimensions=self.config.dimensions,
                normalize=self.config.normalize,
                text=text,
            )

            if cached is not None:
                result[index] = cached

            else:
                missing_texts.append(text)
                missing_indexes.append(index)

        # 2. Получаем только отсутствующие embedding

        vectors: list[list[float]] = []

        batch_size = self.config.batch_size

        # Получаем векторы для каждого чанка, запросы идут батчами по batch_size чанков
        #
        for start in range(
            0,
            len(missing_texts),
            batch_size,
        ):
            batch = missing_texts[start : start + batch_size]

            batch_vectors = self.model.embed(batch)

            vectors.extend(batch_vectors)

        # 3. Записываем новые embedding

        for index, text, vector in zip(
            missing_indexes,
            missing_texts,
            vectors,
        ):
            self.cache.set(
                model=self.config.name,
                dimensions=self.config.dimensions,
                normalize=self.config.normalize,
                text=text,
                embedding=vector,
            )

            result[index] = vector

        assert all(vector is not None for vector in result)

        return cast(
            list[list[float]],
            result,
        )
