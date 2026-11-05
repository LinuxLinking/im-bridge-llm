from bridge import reader


def _text(value):
    return {"type": "TextControl", "name": value, "value": "", "children": []}


def _group(children, name=""):
    return {"type": "GroupControl", "name": name, "value": "", "children": children}


def _conv_item(name, time_text, preview_texts):
    return _group([
        _group([_text(name), _group([_text(time_text)]), _group([_text(t) for t in preview_texts])]),
        _group([], name="免打扰"),
    ])


def _chat_item(time_text, sender, body):
    return _group([
        _group([_text(time_text)]),
        _group([
            _group([], name=sender),
            _group([_group([_text(body)])]),
        ]),
    ])


# ---------- 会话列表（行为） ----------

def test_parse_conversations_finds_name_time_preview():
    tree = [{"type": "PaneControl", "name": "会话列表", "value": "", "children": [
        _conv_item("会话B", "19:11", ["小明：", "在吗"]),
        _conv_item("会话A", "20:20", ["小红：", "收到"]),
    ]}]
    convs = reader.parse_conversations(tree)
    names = [c.name for c in convs]
    assert "会话B" in names
    conv = convs[names.index("会话B")]
    assert reader.TIME_RE.match(conv.time), conv.time
    assert conv.preview == "小明：在吗"


def test_parse_conversations_reads_unread_badge():
    tree = [{"type": "PaneControl", "name": "会话列表", "value": "", "children": [
        _group([
            _group([_text("会话C"), _group([_text("04/04")]), _group([_text("1个会话有新消息")])]),
        ]),
    ]}]
    by_name = {c.name: c for c in reader.parse_conversations(tree)}
    assert by_name["会话C"].unread == "1"
    assert by_name["会话C"].preview == ""
    assert by_name["会话C"].time == "04/04"


# ---------- 消息区（行为） ----------

def test_parse_chat_extracts_sender_and_body():
    tree = [{"type": "PaneControl", "name": "消息列表", "value": "", "children": [
        _chat_item("13:19", "小明", "在吗"),
        _chat_item("13:20", "小红", "在的"),
    ]}]
    msgs = reader.parse_chat(tree)
    assert {m.sender for m in msgs} == {"小明", "小红"}
    assert any("在吗" in m.text for m in msgs)


def test_parse_chat_inherits_time_when_missing():
    tree = [{"type": "PaneControl", "name": "消息列表", "value": "", "children": [
        _text("2026/10/28 13:19"),
        _group([
            _group([], name="小明"),
            _group([_group([_text("在吗")])]),
        ]),
        _group([
            _group([], name="小红"),
            _group([_group([_text("在的")])]),
        ]),
    ]}]
    msgs = reader.parse_chat(tree)
    assert len(msgs) == 2
    assert all(m.time for m in msgs)
    assert all(m.time == "2026/10/28 13:19" for m in msgs)


# ---------- 合成树（规则） ----------

def test_conversation_item_splits_name_time_and_preview():
    tree = [{"type": "PaneControl", "name": "会话列表", "value": "", "children": [
        _conv_item("会话A", "20:20", ["小明：", "在吗"]),
    ]}]
    convs = reader.parse_conversations(tree)
    assert len(convs) == 1
    assert convs[0].name == "会话A"
    assert convs[0].time == "20:20"
    assert convs[0].preview == "小明：在吗"
    assert convs[0].unread == ""


def test_conversation_item_unread_badge_is_not_preview():
    tree = [{"type": "PaneControl", "name": "会话列表", "value": "", "children": [
        _group([
            _group([_text("会话A"), _group([_text("19:11")]), _group([_text("3个会话有新消息")])]),
        ]),
    ]}]
    conv = reader.parse_conversations(tree)[0]
    assert conv.unread == "3"
    assert conv.preview == ""


def test_chat_message_sender_body_and_time():
    tree = [{"type": "PaneControl", "name": "消息列表", "value": "", "children": [
        _chat_item("2026/10/28 13:19", "小明", "在吗"),
    ]}]
    msgs = reader.parse_chat(tree)
    assert len(msgs) == 1
    assert msgs[0].sender == "小明"
    assert msgs[0].text == "在吗"
    assert msgs[0].time == "2026/10/28 13:19"


def test_chat_file_message_has_no_body():
    tree = [{"type": "PaneControl", "name": "消息列表", "value": "", "children": [
        _chat_item("2026/10/28 13:19", "小明", "47.77 KB"),
    ]}]
    assert reader.parse_chat(tree)[0].text == ""


def _title_button(name):
    return {"type": "ButtonControl", "name": name, "value": "", "children": []}


def test_current_conversation_comes_from_title_button():
    tree = [
        {"type": "PaneControl", "name": "会话列表", "value": "", "children": [
            _group([_group([_text("会话A"), _group([_text("19:11")])])]),
        ]},
        {"type": "GroupControl", "name": "", "value": "", "children": [
            _title_button("会话A | 123456 (66人)"),
        ]},
    ]
    assert reader.parse_current_conversation(tree) == "会话A"


def test_current_conversation_empty_when_no_title():
    tree = [{"type": "PaneControl", "name": "会话列表", "value": "", "children": [
        _group([_group([_text("会话A")])]),
    ]}]
    assert reader.parse_current_conversation(tree) == ""
