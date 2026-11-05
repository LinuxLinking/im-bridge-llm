import bridge.memory_service as service
from bridge.memory_store import Store


def _client():
    from fastapi.testclient import TestClient
    return TestClient(service.app)


def test_ingest_endpoint(tmp_path):
    store = Store(str(tmp_path / "m.db"))
    service.get_store = lambda: store
    client = _client()
    r = client.post("/ingest", json={
        "conversation": "群A",
        "messages": [{"speaker": "老王", "text": "在吗", "time": "14:23", "is_self": False, "uin": ""}],
    })
    assert r.status_code == 200
    assert r.json()["added"] == 1
    r2 = client.post("/ingest", json={
        "conversation": "群A",
        "messages": [{"speaker": "老王", "text": "在吗", "time": "14:23", "is_self": False, "uin": ""}],
    })
    assert r2.json()["added"] == 0


def test_people_endpoints(tmp_path):
    store = Store(str(tmp_path / "m.db"))
    service.get_store = lambda: store
    client = _client()
    client.post("/ingest", json={
        "conversation": "群A",
        "messages": [{"speaker": "老王", "text": "在吗", "time": "14:23", "is_self": False, "uin": ""}],
    })
    assert client.get("/people/老王").json() == {}
    assert client.get("/people").json()["people"] == []
    assert client.get("/stats").json()["messages"] == 1


def test_run_once_extracts_and_marks_scanned(tmp_path, monkeypatch):
    # 刚入库的消息在 MEMORY_MIN_AGE 秒内不抽取，测试里放开这个门槛
    monkeypatch.setenv("MEMORY_MIN_AGE", "0")
    store = Store(str(tmp_path / "m.db"))
    store.ingest("群A", [{"speaker": "老王", "text": "我负责资料汇总", "time": "14:23",
                          "is_self": False, "uin": ""}])
    monkeypatch.setattr(service.memory_extract, "extract",
                        lambda items, existing, summary, uin_of: {
                            "people": [{"speaker": "老王", "bio": "做水利的",
                                        "facts": ["负责资料汇总"], "uin": ""}],
                            "conv_summary": "在聊资料汇总",
                        })
    handled = service.run_once(store)
    assert handled == 1
    assert store.people("老王")["bio"] == "做水利的"
    assert store.summary("群A") == "在聊资料汇总"
    assert store.stats()["pending"] == 0


def test_run_once_keeps_batch_when_llm_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMORY_MIN_AGE", "0")
    store = Store(str(tmp_path / "m.db"))
    store.ingest("群A", [{"speaker": "老王", "text": "我负责资料汇总", "time": "14:23",
                          "is_self": False, "uin": ""}])

    def boom(*args, **kwargs):
        raise RuntimeError("模型挂了")

    monkeypatch.setattr(service.memory_extract, "extract", boom)
    assert service.run_once(store) == 0
    assert store.stats()["pending"] == 1
