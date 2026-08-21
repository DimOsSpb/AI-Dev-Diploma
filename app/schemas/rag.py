from pydantic import BaseModel


class RAGQueryRequest(BaseModel):
    question: str


class SourceItem(BaseModel):
    id: int
    file_name: str
    page: str | None
    score: float
    snippet: str


class RAGQueryResponse(BaseModel):
    answer: str
    top_score: float
    sources: list[SourceItem]
