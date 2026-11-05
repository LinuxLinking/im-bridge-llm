import bridge.memory_extract as extract


def test_parse_result_reads_plain_json():
    data = extract.parse_result('{"people": [], "conv_summary": "在聊资料"}')
    assert data["conv_summary"] == "在聊资料"


def test_parse_result_strips_code_fence():
    fence = chr(96) * 3
    text = fence + "json" + chr(10) + '{"people": [{"speaker": "老王"}], "conv_summary": ""}' + chr(10) + fence
    data = extract.parse_result(text)
    assert data["people"][0]["speaker"] == "老王"


def test_parse_result_raises_on_garbage():
    try:
        extract.parse_result("我不知道")
    except ValueError:
        pass
    else:
        raise AssertionError("应该抛 ValueError")


def test_merge_facts_keeps_order_and_dedupes():
    assert extract.merge_facts(["a", "b"], ["b", "c"]) == ["a", "b", "c"]


def test_extract_calls_llm_and_parses(monkeypatch):
    seen = {}

    def fake_chat(system, messages, max_tokens=2048):
        seen["system"] = system
        seen["messages"] = messages
        return '{"people": [{"speaker": "老王", "bio": "做水利的", "facts": ["负责资料汇总"]}], "conv_summary": "在聊资料"}'

    monkeypatch.setattr(extract.llm, "chat", fake_chat)
    items = [{"id": 1, "conversation": "群A", "ts": "14:23", "speaker": "老王",
              "uin": "", "text": "我负责资料汇总", "is_self": 0}]
    out = extract.extract(items, [], "", {})
    assert out["people"][0]["bio"] == "做水利的"
    assert out["conv_summary"] == "在聊资料"
    assert "老王" in seen["messages"][0]["content"]
    assert "JSON" in seen["system"]


def test_extract_keeps_string_facts_whole(monkeypatch):
    """模型偶尔把 facts 写成一个字符串而不是数组——不能按字符拆开。"""
    monkeypatch.setattr(extract.llm, "chat",
                        lambda *a, **k: '{"people": [{"speaker": "老王", "bio": "做水利的",'
                                         ' "facts": "在水利工程干了很多年 负责资料汇总"}],'
                                         ' "conv_summary": ""}')
    out = extract.extract([{"id": 1, "conversation": "群A", "ts": "1", "speaker": "老王",
                             "uin": "", "text": "x", "is_self": 0}], [], "", {})
    assert out["people"][0]["facts"] == ["在水利工程干了很多年 负责资料汇总"]


def test_extract_strips_dash_prefix_from_facts(monkeypatch):
    monkeypatch.setattr(extract.llm, "chat",
                        lambda *a, **k: '{"people": [{"speaker": "老王", "facts": ["- 负责资料汇总"]}],'
                                         ' "conv_summary": ""}')
    out = extract.extract([{"id": 1, "conversation": "群A", "ts": "1", "speaker": "老王",
                             "uin": "", "text": "x", "is_self": 0}], [], "", {})
    assert out["people"][0]["facts"] == ["负责资料汇总"]


def test_extract_skips_people_without_speaker(monkeypatch):
    monkeypatch.setattr(extract.llm, "chat",
                        lambda *a, **k: '{"people": [{"bio": "没有名字"}], "conv_summary": ""}')
    out = extract.extract([{"id": 1, "conversation": "群A", "ts": "1", "speaker": "老王",
                             "uin": "", "text": "x", "is_self": 0}], [], "", {})
    assert out["people"] == []
