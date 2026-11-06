from bridge import identity


def test_known_returns_cached_uin(tmp_path):
    path = str(tmp_path / "identity.json")
    identity.remember("小明", "10001", path)
    assert identity.known("小明", path) == "10001"


def test_known_is_empty_for_unknown(tmp_path):
    assert identity.known("不存在", str(tmp_path / "identity.json")) == ""


def test_resolve_uses_cache_without_touching_ui(tmp_path, monkeypatch):
    path = str(tmp_path / "identity.json")
    identity.remember("小明", "10001", path)

    def boom(nickname):
        raise AssertionError("有缓存就不该去点资料卡")

    monkeypatch.setattr(identity, "_read_via_card", boom)
    assert identity.resolve("小明", path) == "10001"


def test_resolve_caches_result_from_card(tmp_path, monkeypatch):
    path = str(tmp_path / "identity.json")
    monkeypatch.setattr(identity, "_read_via_card", lambda nickname: "10001")

    assert identity.resolve("小明", path) == "10001"
    assert identity.known("小明", path) == "10001"


def test_configured_ids_parses_pairs(monkeypatch):
    monkeypatch.setenv("KNOWN_IDS", "小明=10001, 小红=10002 ")
    assert identity.configured_ids() == {"小明": "10001", "小红": "10002"}


def test_verify_reports_mismatch_when_uin_differs(tmp_path, monkeypatch):
    path = str(tmp_path / "identity.json")
    monkeypatch.setenv("KNOWN_IDS", "小明=10001")
    identity.remember("小明", "10003", path)
    assert identity.verify("小明", path) == "mismatch"


def test_verify_reports_ok_when_uin_matches(tmp_path, monkeypatch):
    path = str(tmp_path / "identity.json")
    monkeypatch.setenv("KNOWN_IDS", "小明=10001")
    identity.remember("小明", "10001", path)
    assert identity.verify("小明", path) == "ok"


def test_verify_reports_unset_when_not_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("KNOWN_IDS", "")
    assert identity.verify("陌生人", str(tmp_path / "identity.json")) == "unset"
