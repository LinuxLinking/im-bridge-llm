import bridge.memory as memory


def test_ingest_returns_added_count(monkeypatch):
    seen = {}

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"added": 3}

    def fake_post(url, json=None, timeout=None):
        seen["url"] = url
        seen["body"] = json
        return FakeResponse()

    monkeypatch.setattr(memory.httpx, "post", fake_post)
    items = [{"speaker": "老王", "text": "在吗", "time": "14:23", "is_self": False, "uin": "123"}]
    assert memory.ingest("群A", items) == 3
    assert seen["body"]["messages"][0]["uin"] == "123"


def test_ingest_swallows_errors(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("连不上")

    monkeypatch.setattr(memory.httpx, "post", boom)
    assert memory.ingest("群A", []) == 0


def test_people_returns_empty_on_error(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("连不上")

    monkeypatch.setattr(memory.httpx, "get", boom)
    assert memory.people("老王") == {}


def test_people_returns_profile(monkeypatch):
    class FakeResponse:
        status_code = 200

        def json(self):
            return {"key": "uin:123", "speaker": "老王", "uin": "123",
                    "bio": "做水利的", "facts": ["负责资料汇总"],
                    "updated_at": "2026-11-04 10:00:00"}

    monkeypatch.setattr(memory.httpx, "get", lambda *a, **k: FakeResponse())
    profile = memory.people("老王", uin="123")
    assert profile["bio"] == "做水利的"
    assert profile["facts"] == ["负责资料汇总"]


def test_memory_note_is_empty_without_profile(monkeypatch):
    import bridge.core as core
    bridge = core.Bridge(poll=False)
    monkeypatch.setattr(core.memory, "people", lambda speaker, uin="": {})
    monkeypatch.setattr(core.memory, "summary", lambda conversation: "")
    assert bridge._memory_note("群A", "老王") == ""


def test_memory_note_lists_facts_and_summary(monkeypatch):
    import bridge.core as core
    bridge = core.Bridge(poll=False)
    monkeypatch.setattr(core.memory, "people", lambda speaker, uin="": {
        "bio": "做水利的", "facts": ["负责资料汇总"]})
    monkeypatch.setattr(core.memory, "summary", lambda conversation: "在聊资料")
    note = bridge._memory_note("群A", "老王")
    assert "老王" in note
    assert "负责资料汇总" in note
    assert "在聊资料" in note
    assert "参考资料" in note


def test_mcp_memory_tool_lists_profiles(monkeypatch):
    import bridge.mcp_server as mcp
    monkeypatch.setattr(mcp.memory, "all_people",
                        lambda: [{"speaker": "老王", "bio": "做水利的", "facts": []}])
    out = mcp.memory_profile("")
    assert out["people"][0]["speaker"] == "老王"
