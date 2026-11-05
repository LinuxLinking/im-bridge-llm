"""bridge 侧的记忆客户端：只管发 HTTP 请求。

失败一律降级（返回空/0），绝不打断主流程回复——
记忆是加分项，不是主链路的依赖。
"""

from urllib.parse import quote

import httpx

from bridge import config


def _url(path: str) -> str:
    base = config.get("MEMORY_SERVICE_URL", "http://127.0.0.1:8079").rstrip("/")
    return base + path


def _timeout() -> float:
    return config.get_float("MEMORY_TIMEOUT", 2.0)


def enabled() -> bool:
    return config.get("MEMORY_ENABLED", "1") != "0"


def ingest(conversation: str, items: list) -> int:
    """归档一批消息。失败静默返回 0。"""
    if not enabled() or not items:
        return 0
    try:
        response = httpx.post(_url("/ingest"),
                              json={"conversation": conversation, "messages": items},
                              timeout=_timeout())
        return int(response.json().get("added", 0))
    except Exception:
        return 0


def people(speaker: str, uin: str = "") -> dict:
    """查某人档案。没有或出错都返回空 dict。"""
    if not enabled():
        return {}
    try:
        response = httpx.get(_url("/people/%s" % quote(speaker, safe="")),
                             params={"uin": uin or ""}, timeout=_timeout())
        return response.json() or {}
    except Exception:
        return {}


def summary(conversation: str) -> str:
    """查会话摘要。失败返回空串。"""
    if not enabled():
        return ""
    try:
        response = httpx.get(_url("/conversations/%s" % quote(conversation, safe="")),
                             timeout=_timeout())
        return response.json().get("summary", "") or ""
    except Exception:
        return ""


def all_people() -> list:
    """全部人的档案。失败返回空列表。"""
    if not enabled():
        return []
    try:
        response = httpx.get(_url("/people"), timeout=_timeout())
        return response.json().get("people", []) or []
    except Exception:
        return []
