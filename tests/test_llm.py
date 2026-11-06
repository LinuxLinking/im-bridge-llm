import bridge.llm as llm


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self):
        return self._payload


def test_dashscope_provider_posts_openai_body(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_BASE_URL", "https://example.invalid/compatible-mode/v1")
    monkeypatch.setenv("DASHSCOPE_MODEL", "qwen-plus")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "DS-KEY")
    seen = {}

    def fake_post(self, url, headers=None, json=None):
        seen["url"] = url
        seen["headers"] = headers
        seen["body"] = json
        return FakeResponse({"choices": [{"message": {"content": "在的"}}]})

    monkeypatch.setattr(llm.httpx.Client, "post", fake_post)
    out = llm.chat("你是助手", [{"role": "user", "content": "在吗"}])
    assert out == "在的"
    assert seen["url"] == "https://example.invalid/compatible-mode/v1/chat/completions"
    assert seen["headers"]["Authorization"] == "Bearer DS-KEY"
    assert seen["body"]["model"] == "qwen-plus"
    assert seen["body"]["messages"][0] == {"role": "system", "content": "你是助手"}


def test_chat_retries_then_raises(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_BASE_URL", "https://example.invalid/compatible-mode/v1")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "DS-KEY")
    calls = []

    def fake_post(self, url, headers=None, json=None):
        calls.append(url)
        raise RuntimeError("boom")

    monkeypatch.setattr(llm.httpx.Client, "post", fake_post)
    monkeypatch.setattr(llm.time, "sleep", lambda _s: None)
    try:
        llm.chat("s", [])
    except RuntimeError as exc:
        assert "模型调用失败" in str(exc)
    else:
        raise AssertionError("应该抛错")
    assert len(calls) == 3
