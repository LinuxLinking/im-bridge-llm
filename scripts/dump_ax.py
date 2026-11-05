"""dump 客户端的 AX 树到 tests/fixtures/ax_snapshot.json，并打印具名节点概览。"""

import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bridge import qq_uia  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests", "fixtures", "ax_snapshot.json")


def named(nodes):
    out = []

    def rec(items, depth):
        for n in items:
            if n["name"]:
                out.append((depth, n["type"], n["name"][:80], n["value"][:80]))
            rec(n["children"], depth + 1)

    rec(nodes, 0)
    return out


def main():
    nodes = qq_uia.snapshot()
    rows = named(nodes)
    print("named nodes: %d" % len(rows))
    for depth, ctype, name, value in rows[:120]:
        print("%s[%s] %s%s" % ("  " * min(depth, 12), ctype, name, (" | " + value) if value else ""))
    if not nodes:
        print("AX tree empty: 客户端未运行，或启动时缺少 %s" % qq_uia.ACCESSIBILITY_FLAG)
        return 1
    os.makedirs(os.path.dirname(FIXTURE), exist_ok=True)
    with open(FIXTURE, "w", encoding="utf-8") as f:
        json.dump(nodes, f, ensure_ascii=False, indent=1)
    print("fixture -> %s" % FIXTURE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
