"""记忆数据层：SQLite。归档消息、人物档案、会话摘要。

只有数据，没有模型调用——抽取逻辑在 memory_extract.py。
"""

import json
import os
import sqlite3
import time
from contextlib import closing

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
  id          INTEGER PRIMARY KEY,
  conversation TEXT NOT NULL,
  ts          TEXT NOT NULL,
  speaker     TEXT NOT NULL,
  uin         TEXT,
  text        TEXT NOT NULL,
  is_self     INTEGER NOT NULL DEFAULT 0,
  scanned     INTEGER NOT NULL DEFAULT 0,
  created_at  REAL NOT NULL DEFAULT 0,
  UNIQUE(conversation, ts, speaker, text)
);
CREATE INDEX IF NOT EXISTS idx_messages_pending ON messages(scanned) WHERE scanned = 0;
CREATE TABLE IF NOT EXISTS people (
  key        TEXT PRIMARY KEY,
  speaker    TEXT NOT NULL,
  uin        TEXT,
  bio        TEXT DEFAULT '',
  facts      TEXT DEFAULT '[]',
  updated_at TEXT
);
CREATE TABLE IF NOT EXISTS conv_summary (
  conversation TEXT PRIMARY KEY,
  summary      TEXT DEFAULT '',
  updated_at   TEXT
);
"""


def key_for(speaker: str, uin: str) -> str:
    """人物档案的键：号码已知用 qq:<uin>，否则用 nick:<昵称>。"""
    return ("qq:%s" % uin) if uin else ("nick:%s" % speaker)


def merge_facts(old, new) -> list:
    """事实追加去重，顺序保留。"""
    out = []
    for fact in list(old or []) + list(new or []):
        text = (fact or "").strip()
        if text and text not in out:
            out.append(text)
    return out


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


class Store:
    def __init__(self, path: str):
        self.path = path
        directory = os.path.dirname(os.path.abspath(path))
        if directory:
            os.makedirs(directory, exist_ok=True)
        with closing(self._connect()) as conn:
            conn.executescript(SCHEMA)
            conn.commit()

    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    # ---- 消息归档 ----

    def ingest(self, conversation: str, items: list) -> int:
        """写入一批消息，按 (会话, 时间, 说话人, 正文) 去重。返回新增条数。"""
        added = 0
        with closing(self._connect()) as conn:
            for item in items or []:
                text = (item.get("text") or "").strip()
                speaker = (item.get("speaker") or "").strip()
                if not text or not speaker:
                    continue
                cursor = conn.execute(
                    "INSERT OR IGNORE INTO messages(conversation, ts, speaker, uin, text, is_self,"
                    " created_at) VALUES(?,?,?,?,?,?,?)",
                    (conversation, item.get("time") or "", speaker, item.get("uin") or None,
                     text, 1 if item.get("is_self") else 0, time.time()),
                )
                added += cursor.rowcount if cursor.rowcount > 0 else 0
            conn.commit()
        return added

    def pending(self, limit: int = 40, older_than: int = 30) -> list:
        """待抽取的消息：scanned=0 且入库超过 older_than 秒。"""
        cutoff = time.time() - max(0, older_than)
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT id, conversation, ts, speaker, uin, text, is_self, created_at"
                " FROM messages WHERE scanned = 0 ORDER BY id LIMIT ?",
                (limit,),
            ).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            created = item.pop("created_at", None) or 0
            if created and created > cutoff:
                continue
            out.append(item)
        return out

    def mark_scanned(self, ids: list) -> None:
        if not ids:
            return
        with closing(self._connect()) as conn:
            conn.executemany("UPDATE messages SET scanned = 1 WHERE id = ?",
                             [(i,) for i in ids])
            conn.commit()

    # ---- 人物档案 ----

    def _row_to_person(self, row) -> dict:
        return {
            "key": row["key"],
            "speaker": row["speaker"],
            "uin": row["uin"] or "",
            "bio": row["bio"] or "",
            "facts": json.loads(row["facts"] or "[]"),
            "updated_at": row["updated_at"] or "",
        }

    def people(self, speaker: str, uin: str = "") -> dict:
        key = key_for(speaker, uin)
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM people WHERE key = ?", (key,)).fetchone()
            if row is None and uin:
                row = conn.execute("SELECT * FROM people WHERE key = ?",
                                   ("nick:%s" % speaker,)).fetchone()
        return self._row_to_person(row) if row is not None else {}

    def all_people(self) -> list:
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT * FROM people ORDER BY updated_at DESC").fetchall()
        return [self._row_to_person(row) for row in rows]

    def upsert_person(self, speaker: str, uin: str, bio: str, facts: list) -> str:
        """写档案：facts 追加去重，bio 已有则保留旧的（保持稳定）。

        uin 之前未知、现在知道了 → 把 nick:<昵称> 的旧档案迁移到 qq:<uin>，
        不留下重复档案。
        """
        key = key_for(speaker, uin)
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM people WHERE key = ?", (key,)).fetchone()
            if row is None and uin:
                legacy = conn.execute("SELECT * FROM people WHERE key = ?",
                                       ("nick:%s" % speaker,)).fetchone()
                if legacy is not None:
                    facts = merge_facts(json.loads(legacy["facts"] or "[]"), facts)
                    conn.execute("DELETE FROM people WHERE key = ?", ("nick:%s" % speaker,))
                    row = legacy
            old_facts = json.loads(row["facts"] or "[]") if row is not None else []
            old_bio = (row["bio"] or "") if row is not None else ""
            all_facts = merge_facts(old_facts, facts)
            conn.execute(
                "INSERT INTO people(key, speaker, uin, bio, facts, updated_at) VALUES(?,?,?,?,?,?)"
                " ON CONFLICT(key) DO UPDATE SET speaker=excluded.speaker, uin=excluded.uin,"
                " bio=excluded.bio, facts=excluded.facts, updated_at=excluded.updated_at",
                (key, speaker, uin or None, old_bio or (bio or ""),
                 json.dumps(all_facts, ensure_ascii=False), _now()),
            )
            conn.commit()
        return key

    def forget(self, speaker: str) -> int:
        with closing(self._connect()) as conn:
            cursor = conn.execute(
                "DELETE FROM people WHERE key = ?",
                ("nick:%s" % speaker,),
            )
            conn.commit()
            return cursor.rowcount if cursor.rowcount > 0 else 0

    # ---- 会话摘要 ----

    def summary(self, conversation: str) -> str:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT summary FROM conv_summary WHERE conversation = ?",
                               (conversation,)).fetchone()
        return (row["summary"] if row else "") or ""

    def set_summary(self, conversation: str, summary: str) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                "INSERT INTO conv_summary(conversation, summary, updated_at) VALUES(?,?,?)"
                " ON CONFLICT(conversation) DO UPDATE SET summary=excluded.summary,"
                " updated_at=excluded.updated_at",
                (conversation, summary or "", _now()),
            )
            conn.commit()

    def stats(self) -> dict:
        with closing(self._connect()) as conn:
            messages = conn.execute("SELECT COUNT(*) AS n FROM messages").fetchone()["n"]
            pending = conn.execute(
                "SELECT COUNT(*) AS n FROM messages WHERE scanned = 0").fetchone()["n"]
            people = conn.execute("SELECT COUNT(*) AS n FROM people").fetchone()["n"]
        return {"messages": messages, "pending": pending, "people": people}
