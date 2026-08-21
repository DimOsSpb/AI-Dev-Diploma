import requests
from llama_index.core.postprocessor.types import BaseNodePostprocessor
from llama_index.core.schema import NodeWithScore, QueryBundle


class LlamaCppReranker(BaseNodePostprocessor):
    """Reranker через llama.cpp OpenAI-compatible API.

    llama.cpp использует endpoint /v1/rerank с параметрами:
    - model: имя модели
    - query: поисковый запрос
    - documents: список документов
    - top_n: количество лучших результатов
    """

    endpoint: str
    model: str
    top_n: int = 5
    timeout: float = 30.0

    def _postprocess_nodes(
        self,
        nodes: list[NodeWithScore],
        query_bundle: QueryBundle | None = None,
    ) -> list[NodeWithScore]:

        if not nodes:
            return nodes

        if query_bundle is None:
            return nodes

        query = query_bundle.query_str

        documents = [node.node.get_content() for node in nodes]

        # llama.cpp использует OpenAI-compatible API
        # endpoint может быть базовым (http://host:port) или полным (http://host:port/v1)
        # проверяем, уже ли есть /v1, и добавляем только /rerank если нужно
        if self.endpoint.endswith("/v1"):
            url = f"{self.endpoint.rstrip('/')}/rerank"
        else:
            url = f"{self.endpoint.rstrip('/')}/v1/rerank"

        response = requests.post(
            url,
            json={
                "model": self.model,
                "query": query,
                "documents": documents,
                "top_n": self.top_n,
            },
            timeout=self.timeout,
        )

        response.raise_for_status()

        data = response.json()

        reranked = []

        for result in data["results"]:
            index = result["index"]
            score = result["relevance_score"]

            original_node = nodes[index]

            reranked.append(
                NodeWithScore(
                    node=original_node.node,
                    score=score,
                )
            )

        return reranked
