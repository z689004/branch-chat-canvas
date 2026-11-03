# -*- coding: utf-8 -*-
"""桌面版启动器：打包成 exe 后双击运行。

行为：
1. 数据目录 = exe 同级 data/（便携，卸载即可带走对话记录）
2. 自动挑选空闲端口（8000 起）
3. 启动内置服务并自动打开默认浏览器
4. 关闭本窗口即退出程序
"""
import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)


def resource_dir() -> Path:
    """打包后的资源目录（_MEIPASS）或源码目录。"""
    if FROZEN:
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def app_dir() -> Path:
    """exe 所在目录（或源码项目根目录）。"""
    if FROZEN:
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


# 数据目录与静态资源目录须在 import main 之前设置
DATA_DIR = app_dir() / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("BCC_DATA_DIR", str(DATA_DIR))

STATIC_DIR = resource_dir() / "frontend" / "public"
if STATIC_DIR.exists():
    os.environ.setdefault("BCC_STATIC_DIR", str(STATIC_DIR))

sys.path.insert(0, str(Path(__file__).resolve().parent))

import uvicorn  # noqa: E402

import main as app_main  # noqa: E402


def find_free_port(start: int = 8000, tries: int = 60) -> int:
    """绑定 0.0.0.0 探测，确保该端口没有任何程序占用（避免与已有服务抢同端口）。"""
    for port in range(start, start + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("0.0.0.0", port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"{start}-{start + tries} 端口都被占用，请关闭占用程序后重试")


def open_browser(url: str) -> None:
    if os.getenv("BCC_NO_BROWSER"):
        return
    time.sleep(1.2)
    try:
        webbrowser.open(url)
    except Exception:
        pass


def main() -> None:
    port = find_free_port()
    url = f"http://127.0.0.1:{port}"
    print("=" * 56)
    print("  分支对话 AI 画布 已启动")
    print(f"  访问地址：{url}")
    print(f"  数据目录：{DATA_DIR}")
    print("  关闭本窗口即退出程序")
    print("=" * 56)

    threading.Thread(target=open_browser, args=(url,), daemon=True).start()
    try:
        uvicorn.run(app_main.app, host="127.0.0.1", port=port, log_level="warning")
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
