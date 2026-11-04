"""反向验证：主窗口只是隐藏（球菜单"收起"）时，程序不能退出。"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import subprocess
import sys
import time

user32 = ctypes.WinDLL("user32", use_last_error=True)
SW_HIDE = 0
SW_SHOW = 5
WM_CLOSE = 0x0010
TITLES = ("分支对话画布", "悬浮球")


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
    env["BCC_DATA_DIR"] = os.path.join(os.environ.get("TEMP", "."), "bcc_close_test")
    proc = subprocess.Popen([os.path.join(root, "dist-exe", "BranchChatCanvas.exe")],
                            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + 90
    wins: dict[str, int] = {}
    while time.time() < deadline:
        wins = find_windows(0)
        if all(t in wins for t in TITLES):
            break
        time.sleep(0.5)
    else:
        print("✗ 未等到窗口", list(wins))
        proc.kill()
        return 1

    main_hwnd = wins[TITLES[0]]
    user32.ShowWindow(main_hwnd, SW_HIDE)
    print("已隐藏主窗口（等价于球菜单收起），等 6 秒…")
    time.sleep(6)

    if proc.poll() is not None:
        print("✗ 仅隐藏主窗口，程序就退出了，收起逻辑被误判")
        return 1
    if "悬浮球" not in find_windows(0):
        print("✗ 隐藏主窗口后悬浮球不见了")
        proc.kill()
        return 1

    print("✓ 仅隐藏：进程存活、悬浮球仍在（收起不受影响）")
    user32.ShowWindow(main_hwnd, SW_SHOW)
    time.sleep(2)
    print("恢复可见：", bool(user32.IsWindowVisible(main_hwnd)))
    ok = user32.PostMessageW(main_hwnd, WM_CLOSE, 0, 0)
    print("发送 WM_CLOSE，返回值 =", ok)
    for i in range(24):
        time.sleep(0.5)
        if proc.poll() is not None:
            print("✓ 随后关闭主窗口：进程正常退出")
            return 0
        if i == 11:
            print("  6 秒后仍未退出，当前窗口：", list(find_windows(0)))
    print("✗ 关闭主窗口后进程仍未退出")
    proc.kill()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
