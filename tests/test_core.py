from bridge import core, guard
from bridge.reader import Message as _Msg


def _bridge(tmp_path, monkeypatch):
    """状态文件指到临时目录，别把测试消息写进真实 state.json。"""
    monkeypatch.setenv("STATE_FILE", str(tmp_path / "state.json"))
    return core.Bridge(poll=False)


def _stub(bridge, monkeypatch, reply="ok"):
    """把模型和发送都打桩，返回一个装着「模型收到的话」的字典。"""
    captured = {}

    def fake_reply(conversation, history, user_text, **kwargs):
        captured["user_text"] = user_text
        captured["memory_note"] = kwargs.get("memory_note", "")
        return reply

    monkeypatch.setattr(bridge.agent, "reply", fake_reply)
    monkeypatch.setattr(core.writer, "send", lambda conversation, text: True)
    monkeypatch.setattr(bridge, "can_send", lambda conversation: "")
    return captured


def test_handle_tells_the_model_who_is_asking(tmp_path, monkeypatch):
    """群聊里模型必须看到「谁在问」——否则它认不出是谁在提问。"""
    bridge = _bridge(tmp_path, monkeypatch)
    messages = [_Msg("小明", "我是？")]
    captured = _stub(bridge, monkeypatch)
    monkeypatch.setattr(bridge, "messages", lambda conversation, nodes=None: messages)

    bridge.handle("会话A")

    assert captured["user_text"] == "小明: 我是？"


def test_handle_refuses_controversial_topic_without_calling_model(tmp_path, monkeypatch):
    """炒股这类争议话题只回固定一句，不能让模型自由发挥。"""
    bridge = _bridge(tmp_path, monkeypatch)
    messages = [_Msg("esfesfesf", "分析下美国救市是抄底吗")]
    called = []
    monkeypatch.setattr(bridge, "messages", lambda conversation, nodes=None: messages)
    monkeypatch.setattr(core.writer, "send", lambda conversation, text: True)
    monkeypatch.setattr(bridge.agent, "reply", lambda *a, **k: called.append(a) or "不该被调用")

    result = bridge.handle("会话A")

    assert not called, "争议话题不该调模型"
    assert result["reply"] == guard.REFUSAL


def test_handle_answers_chitchat_too(tmp_path, monkeypatch):
    """闲聊也回——不靠关键词挡，频率交给计数和冻结控制。"""
    bridge = _bridge(tmp_path, monkeypatch)
    messages = [_Msg("路人", "今天天气不错")]
    captured = _stub(bridge, monkeypatch)
    monkeypatch.setattr(bridge, "messages", lambda conversation, nodes=None: messages)

    result = bridge.handle("会话A")

    assert result["replied"] is True
    assert captured["user_text"] == "路人: 今天天气不错"


def test_chitchat_freezes_after_limit(tmp_path, monkeypatch):
    """窗口内闲聊超过上限就冻结，冻结期间不再回。"""
    bridge = _bridge(tmp_path, monkeypatch)
    monkeypatch.setenv("CHAT_COUNT_LIMIT", "2")
    messages = []
    monkeypatch.setattr(bridge, "messages", lambda conversation, nodes=None: list(messages))
    _stub(bridge, monkeypatch)

    for i in range(2):
        messages.append(_Msg("路人", "闲聊%d" % i))
        assert bridge.handle("会话A")["replied"] is True

    messages.append(_Msg("路人", "闲聊2"))
    result = bridge.handle("会话A")
    assert not result["replied"]
    assert "冻结" in result["reason"]

    messages.append(_Msg("路人", "闲聊3"))
    result = bridge.handle("会话A")
    assert not result["replied"]
    assert "冻结" in result["reason"]


def test_screened_out_reply_does_not_block_the_queue(tmp_path, monkeypatch):
    """出口筛查拦下的回复要记成已处理，不然这条会一直堵在队首。"""
    bridge = _bridge(tmp_path, monkeypatch)
    messages = [_Msg("路人", "注入消息")]
    monkeypatch.setattr(bridge, "messages", lambda conversation, nodes=None: list(messages))
    monkeypatch.setattr(bridge.agent, "reply", lambda *a, **k: "")
    monkeypatch.setattr(core.writer, "send", lambda conversation, text: True)
    monkeypatch.setattr(bridge, "can_send", lambda conversation: "")

    first = bridge.handle("会话A")
    assert not first["replied"]

    messages.append(_Msg("路人", "正常问题"))
    captured = _stub(bridge, monkeypatch, reply="ok")
    second = bridge.handle("会话A")

    assert second["replied"] is True
    assert captured["user_text"] == "路人: 正常问题"


def test_dispute_is_not_answered(tmp_path, monkeypatch):
    """脏词/吵架不掺和。"""
    bridge = _bridge(tmp_path, monkeypatch)
    messages = [_Msg("路人", "你傻逼吧")]
    called = []
    monkeypatch.setattr(bridge, "messages", lambda conversation, nodes=None: messages)
    monkeypatch.setattr(core.writer, "send", lambda conversation, text: True)
    monkeypatch.setattr(bridge.agent, "reply", lambda *a, **k: called.append(a) or "不该被调用")

    result = bridge.handle("会话A")

    assert not result["replied"]
    assert not called
