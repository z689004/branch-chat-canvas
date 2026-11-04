"""回归：`--minimized`（开机自启）启动后，程序不能被关窗守卫误判退出。

主窗口在 hidden 状态创建，守卫只应在窗口**句柄被销毁**时才退出；
这个用例确认隐藏启动 20 秒后进程与悬浮球都还在。
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import subprocess
import sys
import time

user32 = ctypes.WinDLL("user32", use_last_error=True)


def find_windows(pid: int) -> dict[str, int]:
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
    env["BCC_DATA_DIR"] = os.path.join(os.environ.get("TEMP", "."), "bcc_min_test")
    proc = subprocess.Popen([os.path.join(root, "dist-exe", "BranchChatCanvas.exe"), "--minimized"],
                            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + 90
    while time.time() < deadline:
        if "悬浮球" in find_windows(0):
            break
        time.sleep(0.5)
    else:
        print("✗ 未等到悬浮球窗口")
        proc.kill()
        return 1

    print("✓ 已隐藏主窗口启动，悬浮球出现；观察 22 秒…")
    for _ in range(22):
        time.sleep(1)
        if proc.poll() is not None:
            print(f"✗ 启动约 {int(time.time() - deadline + 90)} 秒后进程自行退出")
            return 1

    wins = find_windows(0)
    if "悬浮球" not in wins:
        print("✗ 悬浮球消失了")
        proc.kill()
        return 1

    print("✓ 22 秒后进程仍在、悬浮球仍在（隐藏启动不会被误杀）")
    if "分支对话画布" in wins:
        user32.PostMessageW(wins["分支对话画布"], 0x0010, 0, 0)  # WM_CLOSE
        time.sleep(3)
    if proc.poll() is None:
        proc.kill()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
