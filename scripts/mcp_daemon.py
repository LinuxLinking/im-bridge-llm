"""常驻守护：MCP server 挂了就重启，保证 harness 随时能调。

用法（项目根目录）：
    .venv\Scripts\python.exe scripts\mcp_daemon.py
"""

import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main():
    env = dict(os.environ, MCP_TRANSPORT="streamable-http", PYTHONIOENCODING="utf-8")
    while True:
        proc = subprocess.Popen([sys.executable, "-m", "bridge.mcp_server"], cwd=ROOT, env=env)
        code = proc.wait()
        print("mcp_server 退出（code=%s），3 秒后重启" % code, flush=True)
        time.sleep(3)


if __name__ == "__main__":
    main()
