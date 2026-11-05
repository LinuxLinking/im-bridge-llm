"""常驻守护：记忆服务挂了自动重启。

用法（项目根目录）：
    .venv\Scripts\python.exe scripts\memory_daemon.py
"""

import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main():
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    while True:
        proc = subprocess.Popen([sys.executable, "-m", "bridge.memory_service"], cwd=ROOT, env=env)
        code = proc.wait()
        print("memory_service 退出（code=%s），3 秒后重启" % code, flush=True)
        time.sleep(3)


if __name__ == "__main__":
    main()
