from pydantic import BaseModel


class EmbeddingModelConfig(BaseModel):
    description: str = ""
    name: str
    endpoint: str

    dimensions: int
    batch_size: int = 128
    normalize: bool = True
    query_prefix: str = ""
    document_prefix: str = ""
