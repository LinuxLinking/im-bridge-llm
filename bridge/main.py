"""编排层：FastAPI 接口 + 后台轮询线程。"""

import sys
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel

from bridge import config, core

# 控制台默认 GBK，打印群消息里的生僻字会抛 UnicodeEncodeError，
# 把轮询线程打断成 error 状态（mcp_server.py 同样处理）
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

bridge = core.Bridge(poll=True)


@asynccontextmanager
async def lifespan(app):
    marked = bridge.baseline_all()
    print("baseline: %d 条历史消息标记为已处理" % marked)
    thread = threading.Thread(target=_poll_loop, daemon=True)
    thread.start()
    yield


app = FastAPI(title="IM Bridge", lifespan=lifespan)


def _poll_loop():
    interval = config.get_float("POLL_INTERVAL", 1.5)
    while True:
        bridge.poll_once()
        time.sleep(interval)


class MessageIn(BaseModel):
    conversation: str
    text: str


@app.get("/health")
def health():
    return bridge.health()


@app.get("/conversations")
def conversations():
    return [
        {"name": c.name, "time": c.time, "preview": c.preview, "unread": c.unread}
        for c in bridge.conversations()
    ]


@app.post("/message")
def message(payload: MessageIn):
    """手动问一句，让助手直接回。"""
    if not bridge.lock.acquire(blocking=False):
        return {"replied": False, "reason": "正在处理其他消息"}
    try:
        return bridge.handle(payload.conversation, payload.text)
    except Exception as exc:
        bridge.last_error = str(exc)
        return {"replied": False, "reason": str(exc)}
    finally:
        bridge.lock.release()
