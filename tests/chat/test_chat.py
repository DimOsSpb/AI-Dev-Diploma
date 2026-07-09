async def test_chat_ok(client, mock_llm):
    resp = await client.post(
        "/chat",
        json={"messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["content"] == "мок-ответ"
    assert data["model"] == "gpt-4o-mini"
    assert data["usage"]["total_tokens"] == 15
    mock_llm.chat.completions.create.assert_awaited_once()


async def test_chat_custom_request_id_propagated(client):
    resp = await client.post(
        "/chat",
        json={"messages": [{"role": "user", "content": "hi"}]},
        headers={"X-Request-ID": "rid-abc-123"},
    )
    assert resp.headers["X-Request-ID"] == "rid-abc-123"


async def test_chat_validation_empty_messages(client):
    resp = await client.post("/chat", json={"messages": []})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"


async def test_chat_max_tokens_limit(client):
    resp = await client.post(
        "/chat",
        json={
            "messages": [{"role": "user", "content": "x"}],
            "max_tokens": 99_999,
        },
    )
    assert resp.status_code == 422


async def test_chat_assistant_first_message_rejected(client):
    resp = await client.post(
        "/chat",
        json={"messages": [{"role": "assistant", "content": "hi"}]},
    )
    assert resp.status_code == 422


async def test_chat_temperature_out_of_range(client):
    resp = await client.post(
        "/chat",
        json={
            "messages": [{"role": "user", "content": "x"}],
            "temperature": 5.0,
        },
    )
    assert resp.status_code == 422


async def test_chat_cache_hit(client, mock_cache, mock_llm):
    # При temperature=0 включается кеш. Подсунем закешированный ответ.
    cached_blob = (
        '{"content":"из-кеша","model":"gpt-4o-mini",'
        '"usage":{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2,"estimated_cost_usd":0.0},'
        '"finish_reason":"stop","cached":false,"request_id":null}'
    )
    mock_cache.get.return_value = cached_blob

    resp = await client.post(
        "/chat",
        json={
            "messages": [{"role": "user", "content": "deterministic"}],
            "temperature": 0,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["content"] == "из-кеша"
    assert data["cached"] is True
    mock_llm.chat.completions.create.assert_not_called()
