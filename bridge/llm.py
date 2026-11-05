"""模型通道抽象：harness 网关（Anthropic 协议）或 DashScope（OpenAI 兼容）。

两个 provider 对上层只暴露 chat(system, messages) -> str。
换 provider 只改 .env 的 MODEL_PROVIDER，不改调用方。
"""

import json
import os
import time

import httpx

from bridge import config

MAX_COMPLETION_TOKENS = 2048
RETRY_DELAYS = (1, 3)  # 秒：第 1 次失败等 1s，第 2 次等 3s


def data_dir() -> str:
    return os.environ.get("MINIMAX_DATA_DIR") or os.path.expanduser("~/.minimax")


def auth_token() -> str:
    """从本地 auth store 取 accessToken。"""
    root = os.path.join(data_dir(), "auth")
    for dirpath, _, files in os.walk(root):
        if "auth.json" not in files:
            continue
        try:
            with open(os.path.join(dirpath, "auth.json"), "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        for record in (data.get("records") or {}).values():
            token = record.get("accessToken")
            if token:
                return token
    raise RuntimeError("没找到 harness 登录凭证：%s" % root)


def _text_of(data) -> str:
    """只取 text 块，thinking 块丢掉。"""
    parts = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
    return "".join(parts).strip()


def _post(url: str, headers: dict, body: dict) -> dict:
    timeout = config.get_float("HARNESS_TIMEOUT", 120.0)
    with httpx.Client(timeout=timeout) as client:
        response = client.post(url, headers=headers, json=body)
    if response.status_code != 200:
        raise RuntimeError("%s %s: %s" % (url, response.status_code, response.text[:200]))
    return response.json()


def _chat_harness(system: str, messages: list, max_tokens: int) -> str:
    body = {
        "model": config.get("HARNESS_MODEL"),
        "max_tokens": max_tokens,
        "system": system,
        "messages": messages,
        "reasoning_effort": "low",
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer %s" % auth_token(),
    }
    url = config.get("HARNESS_BASE_URL").rstrip("/") + "/messages"
    return _text_of(_post(url, headers, body))


def _chat_dashscope(system: str, messages: list, max_tokens: int) -> str:
    body = {
        "model": config.get("DASHSCOPE_MODEL", "qwen-plus"),
        "messages": [{"role": "system", "content": system}] + list(messages),
        "max_tokens": max_tokens,
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer %s" % config.get("DASHSCOPE_API_KEY"),
    }
    url = config.get("DASHSCOPE_BASE_URL").rstrip("/") + "/chat/completions"
    data = _post(url, headers, body)
    try:
        return (data["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("dashscope 响应结构不对: %s" % str(data)[:200]) from exc


def chat(system: str, messages: list, max_tokens: int = MAX_COMPLETION_TOKENS) -> str:
    """调模型拿纯文本。失败按 1s、3s 退避重试两次，仍失败抛错。"""
    provider = (config.get("MODEL_PROVIDER", "harness") or "harness").strip().lower()
    call = _chat_dashscope if provider == "dashscope" else _chat_harness

    last = None
    for attempt in range(3):
        try:
            return call(system, messages, max_tokens)
        except Exception as exc:
            last = exc
            # 敏感判定不是瞬时故障，重试没有意义
            if "output_sensitive" in str(exc):
                raise RuntimeError("模型回复被判定敏感，不发送") from exc
            if attempt < 2:
                time.sleep(RETRY_DELAYS[attempt])
    raise RuntimeError("模型调用失败: %s" % last)
