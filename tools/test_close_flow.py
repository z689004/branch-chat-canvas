"""回归：关闭主窗口后，悬浮球与后端进程必须一起退出。

用法：
    C:/develop/Python/python.exe tools/test_close_flow.py        # 跑源码版
    C:/develop/Python/python.exe tools/test_close_flow.py --exe  # 跑打包后的 exe
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import subprocess
import sys
import time

user32 = ctypes.WinDLL("user32", use_last_error=True)

MAIN_TITLE = "分支对话画布"
BALL_TITLE = "悬浮球"
WM_CLOSE = 0x0010
WM_QUIT = 0x0012


def find_windows(pid: int) -> dict[str, int]:
    """按标题找顶层窗口；pid=0 表示不按进程过滤（onefile exe 的窗口属于子进程）。"""
    hits: dict[str, int] = {}

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def _enum(hwnd, _lparam):
        proc = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(proc))
        if pid == 0 or proc.value == pid:
            n = user32.GetWindowTextLengthW(hwnd)
            if n > 0:
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                hits[buf.value] = int(hwnd)
        return True

    user32.EnumWindows(_enum, 0)
    return hits


def main() -> int:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = dict(os.environ)
    env["BCC_DATA_DIR"] = os.path.join(os.environ.get("TEMP", "."), "bcc_close_test")
    if "--exe" in sys.argv:
        cmd = [os.path.join(root, "dist-exe", "BranchChatCanvas.exe")]
        launch_wait = 90
    else:
        cmd = [sys.executable, os.path.join(root, "backend", "app_desktop.py")]
        launch_wait = 40
    proc = subprocess.Popen(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"启动 pid={proc.pid}（{'exe' if '--exe' in sys.argv else '源码'}）")

    deadline = time.time() + launch_wait
    wins: dict[str, int] = {}
    scan_pid = 0 if "--exe" in sys.argv else proc.pid
    while time.time() < deadline:
        wins = find_windows(scan_pid)
        if MAIN_TITLE in wins and BALL_TITLE in wins:
            break
        time.sleep(0.5)
    else:
        print("✗ 40 秒内未看到主窗口与悬浮球窗口", wins)
        proc.kill()
        return 1

    print(f"✓ 两个窗口都已创建：主窗口 hwnd={wins[MAIN_TITLE]}，悬浮球 hwnd={wins[BALL_TITLE]}")
    time.sleep(1.5)

    # 只关闭主窗口（等价于点标题栏 ×）
    user32.PostMessageW(wins[MAIN_TITLE], WM_CLOSE, 0, 0)
    print("已向主窗口发送 WM_CLOSE")

    gone_at = None
    deadline = time.time() + 15
    while time.time() < deadline:
        if proc.poll() is not None:
            gone_at = time.time()
            break
        time.sleep(0.3)

    if gone_at is None:
        alive = find_windows(scan_pid)
        print(f"✗ 主窗口关闭 15 秒后进程仍在运行，残留窗口：{list(alive)}")
        proc.kill()
        return 1

    left = find_windows(scan_pid)
    if BALL_TITLE in left:
        print(f"✗ 进程已退出但悬浮球窗口仍在：{left}")
        return 1

    print(f"✓ 进程随之退出（退出码 {proc.returncode}），悬浮球窗口同时消失")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
