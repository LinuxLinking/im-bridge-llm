"""UIA 原语层：唯一直接 import uiautomation 的地方。其他模块只吃这里导出的 dict 树。

客户端的识别特征（窗口标题、进程名、输入框控件类、资料卡号码标签）都从配置读，
不写死任何具体客户端的字样——按你的 IM 客户端在 .env 里填好对应值即可。
"""

import os
import subprocess
import sys
import threading
import time

import uiautomation as auto
import win32api
import win32con
import win32gui
import win32process

from bridge import config

CLIENT_WINDOW_CLASS = "Chrome_WidgetWin_1"  # Chromium/Electron 通用窗口类
ACCESSIBILITY_FLAG = "--force-renderer-accessibility"

VALUE_PATTERN_ID = 10002
TEXT_PATTERN_ID = 10014
WM_CHAR = 0x0102
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101

_com_state = threading.local()


def _client_exe_name() -> str:
    """CLIENT_EXE 的 basename（小写），用于按进程名匹配窗口所属进程。"""
    exe = config.get("CLIENT_EXE", r"C:\path\to\client.exe")
    return os.path.basename(exe).lower()


def _client_window_title() -> str:
    """配置的主窗口标题；留空则只按窗口类匹配。"""
    return config.get("CLIENT_WINDOW_TITLE", "").strip()


def _editor_class_substring() -> str:
    """聊天输入框控件的 ClassName 子串（按客户端填）。未配置时报错。"""
    sub = config.get("CLIENT_EDITOR_CLASS", "").strip()
    if not sub:
        raise RuntimeError("未配置 CLIENT_EDITOR_CLASS：请在 .env 里填入聊天输入框控件的 ClassName 子串")
    return sub


def _id_label() -> str:
    """资料卡里号码标签的文本（按客户端填）。未配置时报错。"""
    label = config.get("CLIENT_ID_LABEL", "").strip()
    if not label:
        raise RuntimeError("未配置 CLIENT_ID_LABEL：请在 .env 里填入资料卡号码标签的文本")
    return label


def _default_max_depth() -> int:
    """AX 树遍历深度上限（从配置读，默认 60）。

    不同客户端 / 不同版本的 accessibility 树深浅不一：树太浅会读不到消息气泡，
    太深又拖慢全树遍历（每节点一次 COM 往返）。按你的客户端在 .env 里调 AX_MAX_DEPTH。
    """
    return config.get_int("AX_MAX_DEPTH", 60)


def _patch_thread_local_automation():
    """让 uiautomation 的 IUIAutomation 每线程一份。

    uiautomation 默认是进程级单例，实例绑定在第一次创建它的线程公寓里，
    换线程调用会报「尚未调用 CoInitialize」（FastAPI 工作线程、轮询线程都会踩到）。
    """
    module = sys.modules.get("uiautomation.uiautomation")
    client = getattr(module, "_AutomationClient", None)
    if client is None:
        return
    local = threading.local()

    def instance(cls):
        inst = getattr(local, "inst", None)
        if inst is None:
            inst = cls()
            local.inst = inst
        return inst

    client.instance = classmethod(instance)


_patch_thread_local_automation()


def ensure_com() -> None:
    """当前线程初始化 COM（必须持有初始化器引用，否则被 GC 时会 CoUninitialize 掉）。"""
    if getattr(_com_state, "ready", False):
        return
    try:
        _com_state.init = auto.UIAutomationInitializerInThread()
    except Exception:
        _com_state.init = None
    _com_state.ready = True


# ---------- AX 树导出 ----------


def _node(ctrl, depth: int, max_depth: int):
    # 只取 reader 真正用到的三个字段：type / name / className。
    # 之前还顺手取一次 ValuePattern，全代码没有任何地方读它，
    # 光这一项就占掉每个节点一次 COM 往返（整棵树几千个节点）。
    try:
        node = {
            "type": ctrl.ControlTypeName,
            "name": ctrl.Name or "",
            "className": ctrl.ClassName or "",
            "children": [],
        }
    except Exception:
        return None
    if depth < max_depth:
        try:
            kids = ctrl.GetChildren()
        except Exception:
            kids = []
        for kid in kids:
            child = _node(kid, depth + 1, max_depth)
            if child is not None:
                node["children"].append(child)
    return node


def walk(ctrl, max_depth: int = None) -> list:
    """AX 子树 → 纯 dict 树（type/name/value/children），供 reader 离线解析。"""
    if max_depth is None:
        max_depth = _default_max_depth()
    out = []
    try:
        kids = ctrl.GetChildren()
    except Exception:
        return out
    for kid in kids:
        node = _node(kid, 0, max_depth)
        if node is not None:
            out.append(node)
    return out


SNAPSHOT_TTL = 0.5  # 一次回复流程里会连着取好几次快照，全树遍历每次 2~4 秒
_snapshot_cache = {"at": 0.0, "nodes": []}


def snapshot(max_depth: int = None) -> list:
    """客户端主窗口的 AX 快照；找不到窗口返回 []。

    max_depth 不传时取 AX_MAX_DEPTH 配置值。带半秒缓存：写一条消息要连着取好几次快照
    （当前会话 / 输入框 / 回读校验），不缓存的话光快照就要十几秒，这是「回复太慢」的主因。
    """
    if _snapshot_cache["nodes"] and time.time() - _snapshot_cache["at"] < SNAPSHOT_TTL:
        return _snapshot_cache["nodes"]
    win = find_client_window()
    if win is None:
        return []
    nodes = walk(win, max_depth)
    _snapshot_cache["at"] = time.time()
    _snapshot_cache["nodes"] = nodes
    return nodes


# ---------- 窗口定位与启动 ----------


def find_client_window():
    """定位可见的客户端主窗口。

    Electron 会为同一个应用创建多个同名 Chrome_WidgetWin_1 窗口（多数不可见），
    按 UIA 桌面树取第一个会抓到隐藏窗口，坐标全错，所以这里按 Win32 枚举取可见且面积最大的。

    匹配条件：窗口类 == CLIENT_WINDOW_CLASS，且（若配了 CLIENT_WINDOW_TITLE）标题精确相等，
    且窗口所属进程的 exe 名 == CLIENT_EXE 的 basename。
    """
    ensure_com()
    exe_name = _client_exe_name()
    title = _client_window_title()
    try:
        pids = {p.pid for p in auto.GetProcesses() if (p.exeName or "").lower() == exe_name} if exe_name else set()
    except Exception:
        pids = set()
    best = [None, 0]

    def cb(hwnd, _):
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if pids and pid not in pids:
                return True
            if win32gui.GetClassName(hwnd) != CLIENT_WINDOW_CLASS:
                return True
            if title and win32gui.GetWindowText(hwnd) != title:
                return True
            if not win32gui.IsWindowVisible(hwnd):
                return True
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            area = (right - left) * (bottom - top)
        except Exception:
            return True
        if area > best[1]:
            best[0], best[1] = hwnd, area
        return True

    win32gui.EnumWindows(cb, None)
    if best[0] is None:
        return None
    try:
        return auto.ControlFromHandle(best[0])
    except Exception:
        return None


def window_handle():
    win = find_client_window()
    if win is None:
        return None
    try:
        return int(win.NativeWindowHandle)
    except Exception:
        return None


def client_running() -> bool:
    return find_client_window() is not None


def launch_client(exe: str = None, wait_seconds: int = 30) -> bool:
    """带无障碍开关启动客户端并等待主窗口出现。

    已运行的实例不重启——重启会踢掉用户已登录的会话。
    """
    if client_running():
        return True
    exe = exe or config.get("CLIENT_EXE", r"C:\path\to\client.exe")
    if not os.path.exists(exe):
        return False
    subprocess.Popen([exe, ACCESSIBILITY_FLAG])
    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        if find_client_window() is not None:
            return True
        time.sleep(0.5)
    return False


# ---------- 交互原语 ----------


def set_focus(ctrl) -> bool:
    """把客户端窗口拉到前台。

    Windows 的前台锁会拒绝后台进程的 SetForegroundWindow，先敲一次 Alt 放开锁，
    再 SetForegroundWindow + BringWindowToTop。
    """
    try:
        hwnd = int(ctrl.NativeWindowHandle)
    except Exception:
        return False
    try:
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    except Exception:
        pass
    try:
        win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)
        win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0)
    except Exception:
        pass
    try:
        win32gui.BringWindowToTop(hwnd)
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        return False
    time.sleep(0.2)
    return foreground_hwnd() == hwnd


def foreground_hwnd() -> int:
    try:
        return int(win32gui.GetForegroundWindow())
    except Exception:
        return 0


def foreground_title() -> str:
    try:
        return win32gui.GetWindowText(foreground_hwnd())
    except Exception:
        return ""


def type_text(text: str, hwnd: int = None) -> bool:
    """逐字符把文本投进客户端窗口。

    本机 SendInput 合成键入不生效（客户端的 Chromium 收不到），PostMessage(WM_CHAR) 可以。
    """
    hwnd = hwnd or window_handle()
    if hwnd is None:
        return False
    for ch in text:
        code = ord(ch)
        if code > 0xFFFF:  # 非 BMP 字符按 UTF-16 代理对投递
            code -= 0x10000
            win32api.PostMessage(hwnd, WM_CHAR, 0xD800 + (code >> 10), 1)
            win32api.PostMessage(hwnd, WM_CHAR, 0xDC00 + (code & 0x3FF), 1)
        else:
            win32api.PostMessage(hwnd, WM_CHAR, code, 1)
    return True


def press_enter(hwnd: int = None) -> bool:
    hwnd = hwnd or window_handle()
    if hwnd is None:
        return False
    win32api.PostMessage(hwnd, WM_KEYDOWN, win32con.VK_RETURN, 0)
    win32api.PostMessage(hwnd, WM_CHAR, 13, 0)
    win32api.PostMessage(hwnd, WM_KEYUP, win32con.VK_RETURN, 0)
    return True


def post_char(code: int, hwnd: int = None) -> bool:
    hwnd = hwnd or window_handle()
    if hwnd is None:
        return False
    win32api.PostMessage(hwnd, WM_CHAR, code, 1)
    return True


def post_key(vk: int, hwnd: int = None) -> bool:
    """投递一次按键（PostMessage 的键盘事件在本机有效，合成键入无效）。"""
    hwnd = hwnd or window_handle()
    if hwnd is None:
        return False
    win32api.PostMessage(hwnd, WM_KEYDOWN, vk, 0)
    win32api.PostMessage(hwnd, WM_KEYUP, vk, 0)
    return True


def post_ctrl_key(vk: int, hwnd: int = None) -> bool:
    """Ctrl+键组合：PostMessage 的组合键 Chromium 不认（实测无效），仅作占位。"""
    return False


def click_at(x: int, y: int) -> None:
    """屏幕绝对坐标点击。"""
    win32api.SetCursorPos((int(x), int(y)))
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


def iter_controls(ctrl, max_depth: int = None):
    """深度优先遍历活控件对象（保留对象引用，供点击使用）。max_depth 不传时取 AX_MAX_DEPTH。"""
    if max_depth is None:
        max_depth = _default_max_depth()
    yield ctrl
    if max_depth <= 0:
        return
    try:
        kids = ctrl.GetChildren()
    except Exception:
        return
    for kid in kids:
        for item in iter_controls(kid, max_depth - 1):
            yield item


def find_control(name: str = None, control_type: str = None, exact: bool = True):
    """在客户端主窗口里按名字/控件类型找活控件；找不到返回 None。"""
    win = find_client_window()
    if win is None:
        return None
    for ctrl in iter_controls(win):
        try:
            if control_type is not None and ctrl.ControlTypeName != control_type:
                continue
            if name is not None:
                cname = ctrl.Name or ""
                if not (cname == name if exact else name in cname):
                    continue
            return ctrl
        except Exception:
            continue
    return None


def click_name(name: str) -> bool:
    """按控件名点击（切换会话用）。"""
    ctrl = find_control(name=name)
    if ctrl is None:
        return False
    try:
        ctrl.Click(simulateMove=False)
        return True
    except Exception:
        return False


def input_box():
    """支持 ValuePattern 的输入控件（EditControl / DocumentControl）。"""
    win = find_client_window()
    if win is None:
        return None
    for ctrl in iter_controls(win):
        try:
            if ctrl.ControlTypeName not in ("EditControl", "DocumentControl"):
                continue
            if ctrl.GetPattern(VALUE_PATTERN_ID) is not None:
                return ctrl
        except Exception:
            continue
    return None


def input_editor(conversation: str = None):
    """聊天输入框：ClassName 含配置的 CLIENT_EDITOR_CLASS 子串的 GroupControl。

    不用 AX Name 定位——输入框有内容后 Name 会变，conversation 参数只作校验用。
    """
    win = find_client_window()
    if win is None:
        return None
    editor_class = _editor_class_substring()
    for ctrl in iter_controls(win):
        try:
            if ctrl.ControlTypeName != "GroupControl":
                continue
            if editor_class not in (ctrl.ClassName or ""):
                continue
            if conversation is not None and ctrl.Name and ctrl.Name != conversation:
                continue
            return ctrl
        except Exception:
            continue
    return None


def find_chat_controls(conversation: str = None):
    """一次遍历同时取聊天输入框和「发送」按钮。

    分开找要各走一遍整棵树（各 2 秒以上），一次拿齐能省掉好几秒。
    """
    win = find_client_window()
    if win is None:
        return None, None
    editor_class = _editor_class_substring()
    editor = button = None
    for ctrl in iter_controls(win):
        try:
            ctype = ctrl.ControlTypeName
            if ctype == "GroupControl" and editor_class in (ctrl.ClassName or ""):
                if conversation is None or not ctrl.Name or ctrl.Name == conversation:
                    editor = ctrl
            elif ctype == "ButtonControl" and (ctrl.Name or "") == config.get("CLIENT_SEND_BUTTON_NAME", "发送"):
                button = ctrl
        except Exception:
            continue
        if editor is not None and button is not None:
            break
    return editor, button


def open_conversation(name: str, timeout: float = 5.0) -> bool:
    """在会话列表里点开会话。

    当前策略只用用户手动打开的会话，不主动切（自动在多群发言太像机器）。
    保留这个原语给以后的白名单驱动模式用。
    """
    pane = find_control(name=config.get("CLIENT_CONVERSATION_PANE_NAME", "会话列表"), control_type="PaneControl")
    if pane is None:
        return False
    target = None
    for ctrl in iter_controls(pane, 30):
        try:
            if ctrl.ControlTypeName == "TextControl" and ctrl.Name == name:
                target = ctrl
                break
        except Exception:
            continue
    if target is None:
        return False
    try:
        target.Click(simulateMove=False)
    except Exception:
        return False
    deadline = time.time() + timeout
    while time.time() < deadline:
        if input_editor(name) is not None:
            return True
        time.sleep(0.2)
    return False


def _profile_card_title() -> str:
    """资料卡窗口的标题（按客户端填）。留空则无法定位资料卡窗口。"""
    return config.get("CLIENT_PROFILE_CARD_TITLE", "").strip()


def find_profile_card():
    """定位资料卡窗口（点成员头像后会弹出）；没有返回 None。"""
    title = _profile_card_title()
    if not title:
        return None
    ensure_com()
    found = []

    def cb(hwnd, _):
        try:
            if win32gui.GetWindowText(hwnd) == title:
                found.append(hwnd)
        except Exception:
            pass
        return True

    win32gui.EnumWindows(cb, None)
    return found[0] if found else None


def read_profile_card_id(timeout: float = 4.0) -> str:
    """从已打开的资料卡里读号码；读不到返回空串。

    资料卡里号码标签后面跟的数字就是号码。调用方需自己先打开资料卡。
    """
    label = _id_label().rstrip()
    deadline = time.time() + timeout
    while time.time() < deadline:
        hwnd = find_profile_card()
        if hwnd:
            try:
                card = auto.ControlFromHandle(hwnd)
                pending_id = False
                for ctrl in iter_controls(card, 40):
                    try:
                        name = (ctrl.Name or "").strip()
                    except Exception:
                        continue
                    if name.rstrip() == label:
                        pending_id = True
                        continue
                    if pending_id and name.isdigit() and len(name) >= 6:
                        return name
            except Exception:
                pass
        time.sleep(0.2)
    return ""


def close_profile_card() -> None:
    """关掉资料卡窗口，避免残留遮挡。"""
    hwnd = find_profile_card()
    if not hwnd:
        return
    try:
        win32gui.PostMessage(hwnd, 0x0010, 0, 0)  # WM_CLOSE
    except Exception:
        pass


def window_rect():
    win = find_client_window()
    if win is None:
        return None
    return win.BoundingRectangle
