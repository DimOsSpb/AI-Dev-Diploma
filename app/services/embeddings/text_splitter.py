from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class Chunk:
    """Text chunk."""

    text: str
    index: int


class TextSplitter:
    """Split documents into overlapping text chunks."""

    def __init__(
        self,
        *,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
    ) -> None:

        if chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")

        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def split(
        self,
        document: str,
    ) -> list[Chunk]:

        document = " ".join(document.split())

        if not document:
            return []

        if len(document) <= self.chunk_size:
            return [
                Chunk(
                    text=document,
                    index=0,
                )
            ]

        chunks: list[Chunk] = []

        start = 0
        index = 0

        while start < len(document):
            end = min(
                start + self.chunk_size,
                len(document),
            )

            if end < len(document):
                split = document.rfind(
                    " ",
                    start,
                    end,
                )
                if split > start:
                    end = split

            chunk = document[start:end].strip()

            if chunk:
                chunks.append(
                    Chunk(
                        text=chunk,
                        index=index,
                    )
                )
                index += 1

            if end >= len(document):
                break

            start = end - self.chunk_overlap

        return chunks
