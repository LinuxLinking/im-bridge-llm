"""解析层：AX 节点树 → 会话列表 / 消息流。纯函数，不 import uiautomation，可离线单测。"""

import re
from dataclasses import dataclass

from bridge import config

CONVERSATION_PANE = "会话列表"  # 默认值；可被 CLIENT_CONVERSATION_PANE_NAME 覆盖
CHAT_PANE = "消息列表"          # 默认值；可被 CLIENT_CHAT_PANE_NAME 覆盖


def _conversation_pane_name() -> str:
    return config.get("CLIENT_CONVERSATION_PANE_NAME", CONVERSATION_PANE)


def _chat_pane_name() -> str:
    return config.get("CLIENT_CHAT_PANE_NAME", CHAT_PANE)

TIME_RE = re.compile(
    r"^(\d{1,2}:\d{2}(:\d{2})?|\d{4}/\d{1,2}/\d{1,2}( \d{1,2}:\d{2}(:\d{2})?)?|\d{1,2}/\d{1,2}"
    r"|星期[一二三四五六日天]|今天|昨天|前天|刚刚)$"
)
UNREAD_COUNT_RE = re.compile(r"^(\d+)个.*新消息$")
UNREAD_NUM_RE = re.compile(r"^\d+\+?$")
FILE_SIZE_RE = re.compile(r"^\d+(\.\d+)?\s*(B|KB|MB|GB)$", re.IGNORECASE)


@dataclass
class Conversation:
    name: str = ""
    time: str = ""
    preview: str = ""
    unread: str = ""


@dataclass
class Message:
    sender: str = ""
    text: str = ""
    time: str = ""
    is_self: bool = False


def iter_nodes(nodes):
    """按文档顺序产出 (node, depth)。"""
    stack = [(n, 0) for n in reversed(nodes)]
    while stack:
        node, depth = stack.pop()
        yield node, depth
        for child in reversed(node.get("children", [])):
            stack.append((child, depth + 1))


def texts_of(node):
    """子树里所有 Text 节点的文本，按文档顺序。"""
    out = []
    for child, _ in iter_nodes(node.get("children", [])):
        if child.get("type") == "TextControl" and child.get("name"):
            out.append(child["name"].strip())
    return out


def find_pane(nodes, name: str):
    for node, _ in iter_nodes(nodes):
        if node.get("type") == "PaneControl" and node.get("name") == name:
            return node
    return None


def _is_time(text: str) -> bool:
    return bool(TIME_RE.match(text))


def _unread_of(text: str) -> str:
    m = UNREAD_COUNT_RE.match(text)
    if m:
        return m.group(1)
    if UNREAD_NUM_RE.match(text):
        return text
    return ""


def _parse_conversation_item(item) -> Conversation:
    """会话项 → Conversation。缺失字段留空串，不抛异常。"""
    texts = texts_of(item)
    if not texts:
        return Conversation()
    conv = Conversation(name=texts[0])
    rest = texts[1:]
    for text in rest:
        if not conv.time and _is_time(text):
            conv.time = text
            continue
        if not conv.unread and _unread_of(text):
            conv.unread = _unread_of(text)
            continue
        conv.preview += text
    return conv


def parse_conversations(nodes) -> list:
    """会话列表 → Conversation 列表。

    主路径读「会话列表」Pane 下的会话项；Pane 找不到时退化为全树扫描
    （会话项 = 含时间文本、且不在消息区内的 Group）。
    """
    pane = find_pane(nodes, _conversation_pane_name())
    if pane is not None:
        convs = [_parse_conversation_item(child) for child in pane.get("children", [])]
        return [c for c in convs if c.name]

    chat = find_pane(nodes, _chat_pane_name())
    convs = []
    for node, _ in iter_nodes(nodes):
        if node.get("type") != "GroupControl":
            continue
        if chat is not None and _contains(chat, node):
            continue
        texts = texts_of(node)
        if len(texts) < 2 or not any(_is_time(t) for t in texts):
            continue
        conv = _parse_conversation_item(node)
        if conv.name and conv.time:
            convs.append(conv)
    return convs


def _contains(root, target) -> bool:
    for node, _ in iter_nodes(root.get("children", [])):
        if node is target:
            return True
    return False


def _self_class_mark() -> str:
    """本账号消息气泡的 className 标记（按客户端填，可用 scripts/dump_ax.py 查实际值）。

    留空则放弃按 className 判定自己，退回昵称匹配（core 层有兜底）。比昵称可靠：
    昵称会改、也可能撞名；self 标记由客户端自己打。
    """
    return config.get("CLIENT_SELF_CLASS_MARK", "").strip()


def _is_self_message(node) -> bool:
    """气泡容器里带配置的 self 标记就是本账号发的。"""
    mark = _self_class_mark()
    if not mark:
        return False
    for child, _ in iter_nodes(node.get("children", [])):
        if mark in (child.get("className") or ""):
            return True
    return False


def _sender_of(node) -> str:
    """消息容器 = 直接含具名 GroupControl 的组；该子组的名字就是发送者。"""
    for child in node.get("children", []):
        if child.get("type") == "GroupControl" and (child.get("name") or "").strip():
            return child["name"].strip()
    return ""


def _body_of(node, sender: str) -> str:
    """容器内最后一个非发送者名的文本即正文；文件大小文本视为无正文（不触发回复）。"""
    body = ""
    for text in texts_of(node):
        if text == sender:
            continue
        body = text
    if FILE_SIZE_RE.match(body):
        return ""
    return body


def parse_current_conversation(nodes) -> str:
    """当前手动打开的会话名。

    聊天区标题是 ButtonControl，名字可能是「群名」或「群名 | 简介」；
    会话列表里同名的项是 TextControl，不会混淆。找不到就返回空串（不猜）。
    """
    names = {c.name for c in parse_conversations(nodes)}
    if not names:
        return ""
    for node, _ in iter_nodes(nodes):
        if node.get("type") != "ButtonControl":
            continue
        name = (node.get("name") or "").strip()
        if not name:
            continue
        title = name.split(" | ")[0].strip()
        if title in names:
            return title
    return ""


def parse_chat(nodes) -> list:
    """消息区 → Message 列表。

    结构：气泡容器 = [时间组?, 内容组]；内容组 = [发送者组(具名), 名字组, 正文组]。
    正文取容器内最后一个非发送者名的文本；时间取正文前最近的时间戳文本，缺失时沿用上一条。
    """
    pane = find_pane(nodes, _chat_pane_name())
    if pane is None:
        return []

    messages = []
    current_time = ""
    for node, _ in iter_nodes(pane.get("children", [])):
        if node.get("type") == "TextControl":
            text = (node.get("name") or "").strip()
            if text and _is_time(text):
                current_time = text
            continue
        if node.get("type") != "GroupControl":
            continue
        sender = _sender_of(node)
        if not sender:
            continue
        messages.append(
            Message(
                sender=sender,
                text=_body_of(node, sender),
                time=current_time,
                is_self=_is_self_message(node),
            )
        )
    return messages
