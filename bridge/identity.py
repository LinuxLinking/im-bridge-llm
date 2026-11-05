"""号码身份识别：昵称 → 号码（uin），用于区分同名的不同人。

为什么需要：群昵称可改、可撞名。昵称 + 号码才是真实身份。

号码怎么读：点开对方的**资料卡**，卡片里号码标签后面的数字就是。

代价：读号要走界面（点名字 → 弹资料卡 → 读 → 关卡片），约 2~5 秒，
而且要求聊天区当前展开。所以：
- **不做成自动回复链路的一部分**（那条路要每条消息都查，会卡住轮询）；
- 做成**按需查询 + 缓存**：查到一次记进 identity.json，之后直接读缓存。

查找策略（按可靠性排序）：
1. 聊天标题按钮（`chat-header__contact-name`）——私聊场景最稳。
2. 群成员面板里的名字——需要成员面板展开。
3. 会话列表里的名字——那是会话项，点开是聊天不是资料卡，通常无效。

局限：昵称改过缓存会失效（重新查即可）；查不到返回空串，调用方应退回昵称判断。
"""

import json
import os
import time

from bridge import config, qq_uia

STATE_FILE = "identity.json"

# 昵称 → {uin, at}
_cache = {}


def _load(path: str = STATE_FILE) -> dict:
    global _cache
    try:
        with open(path, "r", encoding="utf-8") as f:
            _cache = json.load(f)
    except (OSError, ValueError):
        _cache = {}
    return _cache


def _save(path: str = STATE_FILE) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_cache, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def known(nickname: str, path: str = STATE_FILE) -> str:
    """缓存里已有的号码；没有返回空串（不触发任何界面操作）。"""
    if not _cache:
        _load(path)
    entry = _cache.get(nickname)
    if isinstance(entry, dict):
        return entry.get("uin", "")
    return entry or ""


def remember(nickname: str, uin: str, path: str = STATE_FILE) -> None:
    """记下昵称与号码的对应关系。"""
    if not _cache:
        _load(path)
    _cache[nickname] = {"uin": uin, "at": int(time.time())}
    _save(path)


def resolve(nickname: str, path: str = STATE_FILE) -> str:
    """查昵称对应的号码；查不到返回空串。走资料卡，命中缓存则不碰界面。"""
    if not _cache:
        _load(path)
    cached = known(nickname, path)
    if cached:
        return cached
    uin = _read_via_card(nickname)
    if uin:
        remember(nickname, uin, path)
    return uin


def configured_ids() -> dict:
    """KNOWN_IDS 配置：昵称 → 号码。"""
    raw = config.get("KNOWN_IDS", "")
    out = {}
    for item in raw.split(","):
        if "=" not in item:
            continue
        name, _, uin = item.partition("=")
        name = name.strip()
        uin = uin.strip()
        if name and uin:
            out[name] = uin
    return out


def verify(nickname: str, path: str = STATE_FILE) -> str:
    """核对昵称对应的号码是否与配置一致。

    返回 "ok" / "mismatch" / "unknown" / "unset"：
    - ok：配置里的号码与实际一致
    - mismatch：不一致——**可能是有人冒用昵称**
    - unknown：查不到这个人的号码
    - unset：没配这个昵称
    """
    expected = configured_ids().get(nickname)
    if not expected:
        return "unset"
    actual = known(nickname, path) or resolve(nickname, path)
    if not actual:
        return "unknown"
    return "ok" if actual == expected else "mismatch"


def _visible(ctrl) -> bool:
    try:
        rect = ctrl.BoundingRectangle
        return rect.top > 0 and rect.left > 0 and rect.width() > 0
    except Exception:
        return False


def _read_via_card(nickname: str) -> str:
    """点开昵称的资料卡读号码。找不到成员或读不到就返回空串。"""
    win = qq_uia.find_qq_window()
    if win is None:
        return ""

    for clicker in (_click_header_name, _click_any_name):
        target = clicker(win, nickname)
        if target is None:
            continue
        try:
            target.Click(simulateMove=False)
        except Exception:
            continue
        uin = qq_uia.read_profile_card_qqid()
        qq_uia.close_profile_card()
        if uin:
            return uin
    return ""


def _click_header_name(win, nickname: str):
    """聊天标题按钮：私聊里点对方名字直接弹资料卡（实测最可靠）。"""
    for ctrl in qq_uia.iter_controls(win):
        try:
            if ctrl.ControlTypeName != "ButtonControl":
                continue
            if "chat-header__contact-name" not in (ctrl.ClassName or ""):
                continue
            if (ctrl.Name or "").strip() != nickname:
                continue
            if _visible(ctrl):
                return ctrl
        except Exception:
            continue
    return None


def _click_any_name(win, nickname: str):
    """兜底：聊天区/成员面板里任意可见的同名控件。"""
    for ctrl in qq_uia.iter_controls(win):
        try:
            if (ctrl.Name or "").strip() != nickname:
                continue
            if _visible(ctrl):
                return ctrl
        except Exception:
            continue
    return None
