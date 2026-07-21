import tiktoken


def count_tokens(
    texts: list[str],
    model: str,
) -> int:
    """
    Count input tokens for embedding request.
    """

    try:
        encoding = tiktoken.encoding_for_model(model)
    except KeyError:
        encoding = tiktoken.get_encoding("cl100k_base")

    return sum(len(encoding.encode(text)) for text in texts)


def calculate_cost(
    tokens: int,
    price_per_1m_tokens: float,
) -> float:
    """
    Calculate embedding request cost.
    """

    return (tokens / 1_000_000) * price_per_1m_tokens
