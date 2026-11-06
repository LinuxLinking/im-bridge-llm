import bridge.agent as agent


from bridge.reader import Message as _Msg


def test_own_messages_are_mapped_to_assistant(monkeypatch):
    monkeypatch.setenv("SELF_NICKNAME", "助手")
    history = [_Msg("小明", "在吗"), _Msg("助手", "在的")]
    out = agent.Agent().build_messages(history, "有人在吗")
    assert out == [
        {"role": "user", "content": "小明: 在吗"},
        {"role": "assistant", "content": "助手: 在的"},
        {"role": "user", "content": "有人在吗"},
    ]


def test_line_keeps_sender_visible(monkeypatch):
    # 群聊里模型只看正文认不出是谁在问，发送者必须留在内容里
    assert agent.line("小明", "我是？") == "小明: 我是？"


def test_empty_history_text_is_skipped(monkeypatch):
    monkeypatch.setenv("SELF_NICKNAME", "助手")
    history = [_Msg("小明", ""), _Msg("小明", "你好")]
    out = agent.Agent().build_messages(history, "ping")
    assert len(out) == 2


def test_system_prompt_appends_memory_note(monkeypatch):
    monkeypatch.setenv("SYSTEM_PROMPT", "你是助手")
    prompt = agent.Agent.system_prompt("【记忆】\n- 老王：做水利的")
    assert "【记忆】" in prompt
    assert prompt.index("你是助手") < prompt.index("【记忆】")


def test_system_prompt_without_note_is_unchanged(monkeypatch):
    monkeypatch.setenv("SYSTEM_PROMPT", "你是助手")
    plain = agent.Agent.system_prompt()
    assert agent.Agent.system_prompt("") == plain


def test_system_prompt_carries_todays_date(monkeypatch):
    """不给日期模型会瞎猜「今天周几」。"""
    monkeypatch.setenv("SYSTEM_PROMPT", "你是助手")
    prompt = agent.Agent.system_prompt()
    assert "今天是" in prompt
    assert "星期" in prompt
