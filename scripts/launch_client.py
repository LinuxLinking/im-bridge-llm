"""带 --force-renderer-accessibility 启动客户端（AX 树必须靠这个开关才暴露）。

--restart 会先结束现有客户端实例再重启：缺开关的实例读不到 AX 树。
"""

import argparse
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bridge import client_uia, config  # noqa: E402


def kill_client() -> None:
    exe = config.get("CLIENT_EXE", r"C:\path\to\client.exe")
    name = os.path.basename(exe)
    subprocess.run(["taskkill", "/IM", name, "/F"], capture_output=True)
    time.sleep(2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--restart", action="store_true", help="结束现有客户端实例后重启")
    args = ap.parse_args()

    if args.restart:
        print("killing client ...")
        kill_client()
    elif client_uia.client_running():
        print("client already running (ax tree may be empty if it was started without %s)" % client_uia.ACCESSIBILITY_FLAG)
        return 0

    print("launching client with %s ..." % client_uia.ACCESSIBILITY_FLAG)
    if not client_uia.launch_client():
        print("launch failed: no client window within timeout")
        return 1
    rect = client_uia.window_rect()
    print("client window up:", rect)
    print("named nodes:", len([n for n in client_uia.snapshot() if n.get("name")]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
