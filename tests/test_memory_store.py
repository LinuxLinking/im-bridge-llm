from bridge.memory_store import Store, key_for


def test_ingest_deduplicates_same_message(tmp_path):
    store = Store(str(tmp_path / "m.db"))
    items = [{"speaker": "老王", "text": "在吗", "time": "14:23", "is_self": False, "uin": ""}]
    assert store.ingest("群A", items) == 1
    assert store.ingest("群A", items) == 0
    assert store.stats()["messages"] == 1


def test_ingest_keeps_different_conversations(tmp_path):
    store = Store(str(tmp_path / "m.db"))
    items = [{"speaker": "老王", "text": "在吗", "time": "14:23", "is_self": False, "uin": ""}]
    assert store.ingest("群A", items) == 1
    assert store.ingest("群B", items) == 1


def test_pending_skips_scanned(tmp_path):
    store = Store(str(tmp_path / "m.db"))
    store.ingest("群A", [{"speaker": "老王", "text": "旧的", "time": "1", "is_self": False, "uin": ""}])
    pending = store.pending(limit=10, older_than=0)
    assert len(pending) == 1
    store.mark_scanned([pending[0]["id"]])
    assert store.pending(limit=10, older_than=0) == []


def test_pending_skips_recent_messages(tmp_path):
    store = Store(str(tmp_path / "m.db"))
    store.ingest("群A", [{"speaker": "老王", "text": "刚说的", "time": "1", "is_self": False, "uin": ""}])
    assert store.pending(limit=10, older_than=3600) == []


def test_key_prefers_uin():
    assert key_for("老王", "123") == "qq:123"
    assert key_for("老王", "") == "nick:老王"


def test_facts_are_appended_not_overwritten(tmp_path):
    store = Store(str(tmp_path / "m.db"))
    store.upsert_person("老王", "", "做水利的", ["负责资料汇总"])
    store.upsert_person("老王", "", "做水利的", ["习惯微信发文件"])
    people = store.people("老王")
    assert set(people["facts"]) == {"负责资料汇总", "习惯微信发文件"}
    assert people["bio"] == "做水利的"


def test_profile_migrates_to_uin_when_it_becomes_known(tmp_path):
    store = Store(str(tmp_path / "m.db"))
    store.upsert_person("老王", "", "做水利的", ["负责资料汇总"])
    store.upsert_person("老王", "123", "做水利的", ["习惯微信发文件"])
    assert len(store.all_people()) == 1
    people = store.people("老王", uin="123")
    assert people["key"] == "qq:123"
    assert people["uin"] == "123"
    assert set(people["facts"]) == {"负责资料汇总", "习惯微信发文件"}


def test_summary_roundtrip(tmp_path):
    store = Store(str(tmp_path / "m.db"))
    store.set_summary("群A", "在聊资料汇总")
    assert store.summary("群A") == "在聊资料汇总"
    assert store.summary("群B") == ""


def test_forget_removes_person(tmp_path):
    store = Store(str(tmp_path / "m.db"))
    store.upsert_person("老王", "", "做水利的", ["x"])
    assert store.forget("老王") == 1
    assert store.people("老王") == {}


def test_stats_counts_pending(tmp_path):
    store = Store(str(tmp_path / "m.db"))
    store.ingest("群A", [{"speaker": "老王", "text": "在吗", "time": "14:23", "is_self": False, "uin": ""}])
    stats = store.stats()
    assert stats["messages"] == 1
    assert stats["pending"] == 1
    assert stats["people"] == 0
