"""状态与去重：会话指纹记录在 state.json，成功或最终失败都记，避免无限重试。"""

import hashlib
import json
import os
from collections import deque

MAX_KEPT = 50


def fingerprint(time: str, preview: str) -> str:
    return hashlib.sha1((time + "|" + preview).encode("utf-8")).hexdigest()


class State:
    def __init__(self, data=None):
        self._data = data or {}

    @classmethod
    def load(cls, path: str) -> "State":
        try:
            with open(path, "r", encoding="utf-8") as f:
                return cls(json.load(f))
        except (OSError, ValueError):
            return cls({})

    def to_dict(self) -> dict:
        return self._data

    def _conv(self, name: str) -> dict:
        return self._data.setdefault("conversations", {}).setdefault(
            name, {"fingerprint": "", "processed": [], "failed": []}
        )

    def fingerprint_of(self, name: str) -> str:
        return self._conv(name).get("fingerprint", "")

    def set_fingerprint(self, name: str, fp: str) -> None:
        self._conv(name)["fingerprint"] = fp

    def processed(self, name: str) -> list:
        return self._conv(name).get("processed", [])

    def is_processed(self, name: str, fp: str) -> bool:
        return fp in self.processed(name)

    def mark_processed(self, name: str, fp: str) -> None:
        conv = self._conv(name)
        processed = deque(conv.get("processed", []), maxlen=MAX_KEPT)
        if fp not in processed:
            processed.append(fp)
        conv["processed"] = list(processed)

    def failed(self, name: str) -> list:
        return self._conv(name).get("failed", [])

    def mark_failed(self, name: str, fp: str) -> None:
        conv = self._conv(name)
        failed = deque(conv.get("failed", []), maxlen=MAX_KEPT)
        if fp not in failed:
            failed.append(fp)
        conv["failed"] = list(failed)

    def save(self, path: str) -> None:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
