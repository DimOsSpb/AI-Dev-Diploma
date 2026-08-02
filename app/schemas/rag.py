from pydantic import BaseModel


class RAGQueryRequest(BaseModel):
    question: str


class SourceItem(BaseModel):
    source: str
    score: float
    text: str


class RAGQueryResponse(BaseModel):
    answer: str
    top_score: float
    sources: list[SourceItem]
