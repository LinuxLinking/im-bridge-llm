"""MCP 服务：把客户端的固定动作暴露成工具，供 Agent 调用。

工具都是「读」或「受控写」：写入受白名单 + 限频约束，避免异常刷屏。
"""

import os
import sys
from urllib.parse import quote

import httpx

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)  # .env / state.json 按项目目录解析，harness 从任意 cwd 拉起都一致
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from mcp.server.mcpserver import MCPServer

from bridge import config, core, guard, identity, memory

config.load_env()

server = MCPServer("qq-bridge")
bridge = core.Bridge(poll=False)


@server.tool()
def qq_list_conversations() -> list:
    """列出客户端会话（会话名、时间、最后一条消息预览、未读数）。"""
    config.load_env()
    return [
        {"name": c.name, "time": c.time, "preview": c.preview, "unread": c.unread}
        for c in bridge.conversations()
    ]


@server.tool()
def qq_read_messages(conversation: str, limit: int = 10) -> list:
    """读当前打开的会话最近的消息（sender / text / time）。

    不切会话：只能读用户当前打开的那个会话。
    """
    config.load_env()
    try:
        messages = bridge.messages(conversation)
    except RuntimeError as exc:
        return [{"error": str(exc)}]
    return [
        {"sender": m.sender, "text": m.text, "time": m.time}
        for m in messages[-limit:]
    ]


@server.tool()
def qq_send_text(conversation: str, text: str) -> dict:
    """往当前打开的会话发一条文本。

    只允许发到当前打开的会话，且该会话要在白名单里；
    两次发送之间有最小间隔；发送后会回读聊天区校验是否真的发出。
    """
    config.load_env()
    current = bridge.current_conversation()
    if current != conversation:
        return {"sent": False, "reason": "只能发到当前打开的会话：当前是 %s" % (current or "（未识别）")}
    # 出口筛查：群里的话是不可信输入，模型自己写的话也一样要过筛
    text = guard.screen_reply(text, guard.untrusted_text(bridge.messages(conversation)))
    if not text:
        return {"sent": False, "reason": "回复被安全筛查拦下（太长／含注入内容／泄露配置）"}
    if guard.is_controversial(text):
        # 这条路是模型自己写的文字，同样不能碰争议话题
        return {"sent": False, "reason": "争议话题不回复：%s" % guard.REFUSAL}
    denied = bridge.can_send(conversation)
    if denied:
        return {"sent": False, "reason": denied}
    sent = core.writer.send(conversation, text)
    if sent:
        bridge._mark_sent()
    return {"sent": sent, "conversation": conversation, "text": text}


@server.tool()
def qq_reply_last(conversation: str) -> dict:
    """对当前打开的会话里最后一条他人消息自动生成回复并发回去。

    回复由 bridge 直接调模型生成（不经子 agent：子 agent 一轮要几十秒）。
    """
    config.load_env()
    current = bridge.current_conversation()
    if current != conversation:
        return {"replied": False, "reason": "只能回复当前打开的会话：当前是 %s" % (current or "（未识别）")}
    if not bridge.lock.acquire(blocking=False):
        return {"replied": False, "reason": "正在处理其他消息"}
    try:
        return bridge.handle(conversation)
    except Exception as exc:
        return {"replied": False, "reason": str(exc)}
    finally:
        bridge.lock.release()


@server.tool()
def qq_identity(nickname: str) -> dict:
    """查某个昵称对应的号码（uin），用于区分同名的不同人。

    昵称可改、可撞名，号码才是真实身份。
    首次查会打开该成员的资料卡读一次，之后走缓存，不再打扰界面。
    """
    config.load_env()
    path = config.get("IDENTITY_FILE")
    cached = identity.known(nickname, path)
    if cached:
        return {"nickname": nickname, "qqid": cached, "source": "cache"}
    uin = identity.resolve(nickname, path)
    return {
        "nickname": nickname,
        "qqid": uin,
        "source": "profile_card" if uin else "not_found",
        "verification": identity.verify(nickname, path),
    }


@server.tool()
def qq_whitelist(action: str = "list", conversation: str = "") -> dict:
    """查看或修改白名单会话（只有白名单里的群才允许自动回复）。

    action=list 看当前白名单；action=add 加一个群；action=remove 删一个群。
    修改会写回 .env 并立即生效，不用重启服务。
    """
    config.load_env()
    names = config.whitelist()
    if action == "list":
        return {"whitelist": sorted(names)}
    if action not in ("add", "remove"):
        return {"error": "action 只能是 list / add / remove"}
    name = (conversation or "").strip()
    if not name:
        return {"error": "缺少 conversation 参数"}
    if action == "add":
        names.add(name)
    else:
        names.discard(name)
    config.set_whitelist(sorted(names))
    return {"whitelist": sorted(config.whitelist())}


@server.tool()
def qq_memory(nickname: str = "") -> dict:
    """查记忆里关于某人的档案：是谁、偏好、提过什么事。

    不传昵称则返回所有人的档案列表。
    """
    config.load_env()
    if not nickname:
        return {"people": memory.all_people()}
    path = config.get("IDENTITY_FILE", "identity.json")
    profile = memory.people(nickname, uin=identity.known(nickname, path))
    return profile or {"speaker": nickname, "bio": "", "facts": [],
                       "note": "还没有这个人的记忆"}


@server.tool()
def qq_forget(nickname: str) -> dict:
    """删掉某人的记忆档案（记错了就删掉，删了重新学）。

    只删人物档案，不删消息归档。
    """
    config.load_env()
    if not nickname:
        return {"removed": 0, "note": "缺少 nickname 参数"}
    url = (config.get("MEMORY_SERVICE_URL", "http://127.0.0.1:8079").rstrip("/")
           + "/forget/" + quote(nickname, safe=""))
    try:
        return httpx.post(url, timeout=config.get_float("MEMORY_TIMEOUT", 2.0)).json()
    except Exception as exc:
        return {"removed": 0, "note": str(exc)}


@server.tool()
def qq_status() -> dict:
    """客户端与 bridge 的当前状态。"""
    config.load_env()
    return bridge.health()


if __name__ == "__main__":
    if os.environ.get("MCP_TRANSPORT") == "streamable-http":
        # 常驻模式：后台常驻进程对外提供 HTTP 端点，harness 不用每次拉起进程
        # stateless：服务端不记会话，进程重启后客户端不用重新握手
        server.run(transport="streamable-http", host="127.0.0.1", port=8078, stateless_http=True)
    else:
        server.run()
