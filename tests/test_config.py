from bridge import config


def test_env_file_does_not_override_real_env(tmp_path, monkeypatch):
    p = tmp_path / ".env"
    p.write_text("DASHSCOPE_MODEL=from-file\n", encoding="utf-8")
    monkeypatch.setenv("DASHSCOPE_MODEL", "from-env")
    config.load_env(str(p))
    assert config.get("DASHSCOPE_MODEL") == "from-env"


def test_env_file_fills_missing_key(tmp_path, monkeypatch):
    p = tmp_path / ".env"
    p.write_text("DASHSCOPE_MODEL=from-file\n", encoding="utf-8")
    monkeypatch.delenv("DASHSCOPE_MODEL", raising=False)
    config.load_env(str(p))
    assert config.get("DASHSCOPE_MODEL") == "from-file"


def test_whitelist_splits_and_strips(monkeypatch):
    monkeypatch.setenv("AUTO_REPLY_CONVERSATIONS", "会话A, 会话B ,")
    assert config.whitelist() == {"会话A", "会话B"}


def test_defaults_apply_when_env_missing(monkeypatch):
    monkeypatch.delenv("DASHSCOPE_BASE_URL", raising=False)
    assert config.get("DASHSCOPE_BASE_URL") == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    monkeypatch.delenv("MIN_SEND_INTERVAL", raising=False)
    assert config.get_float("MIN_SEND_INTERVAL", 15) == 15.0


def test_reload_env_picks_up_manual_edit(tmp_path, monkeypatch):
    p = tmp_path / ".env"
    p.write_text("AUTO_REPLY_CONVERSATIONS=会话A\n", encoding="utf-8")
    monkeypatch.delenv("AUTO_REPLY_CONVERSATIONS", raising=False)
    config.load_env(str(p))
    assert config.whitelist() == {"会话A"}

    p.write_text("AUTO_REPLY_CONVERSATIONS=会话A,会话B\n", encoding="utf-8")
    config.load_env(str(p))
    assert config.whitelist() == {"会话A", "会话B"}


def test_set_whitelist_writes_back_to_env(tmp_path, monkeypatch):
    p = tmp_path / ".env"
    p.write_text("MIN_SEND_INTERVAL=15\nAUTO_REPLY_CONVERSATIONS=会话A\n", encoding="utf-8")
    monkeypatch.delenv("AUTO_REPLY_CONVERSATIONS", raising=False)
    config.load_env(str(p))

    config.set_whitelist(["会话B", "会话C"], str(p))
    assert config.whitelist() == {"会话B", "会话C"}
    content = p.read_text(encoding="utf-8")
    assert "AUTO_REPLY_CONVERSATIONS=会话B,会话C" in content
    assert "MIN_SEND_INTERVAL=15" in content, "其他配置不能被覆盖"
