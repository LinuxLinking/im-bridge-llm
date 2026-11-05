"""记忆服务：FastAPI + SQLite + 后台抽取线程。

独立进程（默认 :8079）。bridge 把窗口消息归档进来，
后台线程定期调模型抽出「人物事实 + 会话摘要」。
这个服务挂了不影响主链路——bridge 侧一律降级。
"""

import os
import sys
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from bridge import config, memory_extract, memory_store

config.load_env()

_store = None
_failures = 0


def get_store() -> memory_store.Store:
    """懒建 store：测试可以替换这个函数指向 tmp 目录的库。"""
    global _store
    if _store is None:
        _store = memory_store.Store(config.get("MEMORY_DB", "memory.db"))
    return _store


class MessageIn(BaseModel):
    speaker: str
    text: str
    time: str = ""
    is_self: bool = False
    uin: str = ""


class IngestIn(BaseModel):
    conversation: str
    messages: list[MessageIn] = []


def run_once(store) -> int:
    """跑一轮抽取。返回处理了多少条消息。

    模型失败或输出解析失败 → 整批不标记 scanned，下轮重试。
    """
    global _failures
    items = store.pending(limit=config.get_int("MEMORY_BATCH", 40),
                          older_than=config.get_int("MEMORY_MIN_AGE", 30))
    if not items:
        return 0

    conversation = items[0]["conversation"]
    batch = [i for i in items if i["conversation"] == conversation]
    existing = [p for p in store.all_people()
                if p["speaker"] in {i["speaker"] for i in batch}]
    uin_of = {}
    for item in batch:
        if item.get("uin"):
            uin_of[item["speaker"]] = item["uin"]

    try:
        result = memory_extract.extract(batch, existing, store.summary(conversation), uin_of)
    except Exception as exc:
        _failures += 1
        print("[memory] 抽取失败（第 %d 次）：%s" % (_failures, exc), flush=True)
        return 0

    for person in result.get("people", []):
        store.upsert_person(person["speaker"], person.get("uin", ""),
                            person.get("bio", ""), person.get("facts", []))
    if result.get("conv_summary"):
        store.set_summary(conversation, result["conv_summary"])
    store.mark_scanned([i["id"] for i in batch])
    _failures = 0
    print("[memory] %s 抽取 %d 条，档案 %d 人" % (conversation, len(batch),
                                                len(result.get("people", []))), flush=True)
    return len(batch)


def _extract_loop():
    while True:
        try:
            run_once(get_store())
        except Exception as exc:
            print("[memory] 抽取线程异常: %s" % exc, flush=True)
        time.sleep(config.get_float("MEMORY_INTERVAL", 120.0))


@asynccontextmanager
async def lifespan(app):
    if config.get("MEMORY_ENABLED", "1") != "0":
        thread = threading.Thread(target=_extract_loop, daemon=True)
        thread.start()
    yield


app = FastAPI(title="Bridge Memory", lifespan=lifespan)


@app.get("/health")
def health():
    return {"ok": True, "db": get_store().path}


@app.post("/ingest")
def ingest(payload: IngestIn):
    items = [m.model_dump() for m in payload.messages]
    return {"added": get_store().ingest(payload.conversation, items)}


@app.get("/people")
def all_people():
    return {"people": get_store().all_people()}


@app.get("/people/{speaker}")
def one_person(speaker: str, uin: str = ""):
    return get_store().people(speaker, uin)


@app.get("/conversations/{conversation}")
def one_summary(conversation: str):
    return {"conversation": conversation, "summary": get_store().summary(conversation)}


@app.get("/stats")
def stats():
    return get_store().stats()


@app.post("/forget/{speaker}")
def forget(speaker: str):
    return {"removed": get_store().forget(speaker)}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8079)
