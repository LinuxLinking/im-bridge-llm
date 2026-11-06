"""发送层：把文本写进客户端输入框 → 发出 → 回读校验。

目标客户端的输入框是 contenteditable（GroupControl），不支持 ValuePattern，
所以写值靠「点击聚焦 + PostMessage(WM_CHAR) 逐字符投递」，发出靠点「发送」按钮。
本机 SendInput 合成键入不生效（Chromium 收不到），只有 PostMessage 这条路可用。
"""

import contextlib
import json
import msvcrt
import os
import threading
import time

import win32con

from bridge import client_uia, reader

SEND_DELAY = 0.8
PLACEHOLDER = "按住 Win + Alt"
STATE_FILE = "writer_state.json"  # 记录「我上次输入到一半的文本」，用来认领自己的残留
LOCK_FILE = "bridge.lock"  # 跨进程锁：服务进程和常驻 MCP 进程共用同一个输入框
_local = threading.local()


@contextlib.contextmanager
def ui_lock():
    """串行化「读界面 → 打字 → 发送」。

    服务进程和常驻 MCP 进程是两个 Python 进程，进程内的锁互相看不见；
    同时往同一个输入框打字会把消息搅乱，所以这里用文件锁做进程间互斥。
    同一线程可重入（handle 内部还会调 send）。
    """
    depth = getattr(_local, "depth", 0)
    if depth:
        _local.depth = depth + 1
        try:
            yield
        finally:
            _local.depth -= 1
        return
    with open(LOCK_FILE, "a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        deadline = time.time() + 30
        while True:
            try:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                if time.time() > deadline:
                    raise RuntimeError("等待界面操作锁超时")
                time.sleep(0.2)
        _local.depth = 1
        try:
            yield
        finally:
            _local.depth = 0
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def _load_known() -> dict:
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_known(data: dict) -> None:
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    except OSError:
        pass


def _norm(text: str) -> str:
    return "".join((text or "").split())


def editor_text(conversation: str, editor=None) -> str:
    """读输入框当前内容（TextPattern）。

    editor 可以把已经找到的输入框控件传进来复用——重新找一次要遍历整棵树（2 秒以上）。
    """
    if editor is None:
        editor = client_uia.input_editor(conversation)
    if editor is None:
        return ""
    try:
        return editor.GetPattern(client_uia.TEXT_PATTERN_ID).DocumentRange.GetText(-1) or ""
    except Exception:
        return ""


def _focus_editor(editor) -> bool:
    if editor is None:
        return False
    rect = editor.BoundingRectangle
    # 点靠左上的正文起点，避开右下角的发送按钮
    client_uia.click_at(rect.left + 20, rect.top + 16)
    return True


def _clear_editor(editor) -> None:
    """选中文本再退格清空。

    Ctrl+A 组合键通过 PostMessage 送不进去，改用 TextPattern 选中 + VK_BACK。
    """
    if editor is None:
        return
    try:
        pattern = editor.GetPattern(client_uia.TEXT_PATTERN_ID)
        content = pattern.DocumentRange.GetText(-1) or ""
        if not content.strip() or PLACEHOLDER in content:
            return
        pattern.DocumentRange.Select()
        time.sleep(0.15)
        client_uia.post_key(win32con.VK_BACK)
        time.sleep(0.25)
    except Exception:
        pass


def verify_sent(conversation: str, text: str) -> bool:
    """回读消息区，确认这条文本已经出现。"""
    target = _norm(text)
    if not target:
        return False
    for message in reversed(reader.parse_chat(client_uia.snapshot())):
        body = _norm(message.text)
        if body and (body == target or target in body):
            return True
    return False


def _focus_window(win) -> bool:
    """抢前台；用户正在操作别的窗口时可能失败，重试几次。"""
    for _ in range(3):
        if client_uia.set_focus(win):
            return True
        time.sleep(0.4)
    return False


def _wait_for_text(editor, text: str, timeout: float = 2.5) -> bool:
    """等输入框回读到文本（AX 树有延迟，立即读可能还没更新）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _norm(text) in _norm(editor_text("", editor)):
            return True
        time.sleep(0.2)
    return False


def send(conversation: str, text: str) -> bool:
    """把 text 发到 conversation，返回是否确认送达。"""
    with ui_lock():
        return _send(conversation, text)


def _send(conversation: str, text: str) -> bool:
    text = (text or "").replace("\r", " ").replace("\n", " ").strip()
    if not text:
        return False
    win = client_uia.find_client_window()
    if win is None:
        return False
    # 只往「当前打开的会话」发：切会话后输入框会指向别的群，发错代价太大
    current = reader.parse_current_conversation(client_uia.snapshot())
    if current != conversation:
        return False
    # 一次遍历拿齐输入框和发送按钮，后面全部复用，省掉 4 次整树遍历
    editor, button = client_uia.find_chat_controls(conversation)
    if editor is None:
        return False
    if not _focus_window(win):
        return False
    if not _focus_editor(editor):
        return False
    time.sleep(0.2)

    known = _load_known()
    content = editor_text(conversation, editor).strip()
    if content and PLACEHOLDER not in content and content != known.get(conversation, ""):
        return False  # 输入框里是用户自己的草稿，既不覆盖也不追加

    _clear_editor(editor)
    known[conversation] = text
    _save_known(known)
    typed = False
    for _ in range(2):
        client_uia.type_text(text)
        if _wait_for_text(editor, text):
            typed = True
            break
        _clear_editor(editor)
    if not typed:
        return False

    if button is not None:
        try:
            button.Click(simulateMove=False)
        except Exception:
            client_uia.press_enter()
    else:
        client_uia.press_enter()
    time.sleep(SEND_DELAY)
    if verify_sent(conversation, text):
        known[conversation] = ""
        _save_known(known)
        return True
    return False
