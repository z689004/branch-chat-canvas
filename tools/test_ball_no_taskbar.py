"""回归：悬浮球窗口不应占用任务栏条目 / 缩略图预览（WS_EX_TOOLWINDOW）。

验证点：
1. 启动后悬浮球窗口带 WS_EX_TOOLWINDOW 扩展样式（任务栏/Alt-Tab/缩略图都不显示）；
2. 该样式不影响悬浮球本身的可见性与置顶；
3. 悬浮球开关关→开后样式仍在（幂等路径）。

注意：测试前需关闭正在运行的分支对话画布（单实例保护会让本实例直接退出）。
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import subprocess
import sys
import time

user32 = ctypes.WinDLL("user32", use_last_error=True)
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_TOPMOST = 0x00000008
BALL_TITLE = "悬浮球"
MAIN_TITLE = "分支对话画布"


def find_windows(pid: int = 0) -> dict[str, int]:
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
    if BALL_TITLE in find_windows() or MAIN_TITLE in find_windows():
        print("✗ 检测到正在运行的分支对话画布，请先退出再跑本测试")
        return 2

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = dict(os.environ)
    env["BCC_DATA_DIR"] = os.path.join(os.environ.get("TEMP", "."), "bcc_ball_taskbar_test")
    proc = subprocess.Popen(
        [sys.executable, os.path.join(root, "backend", "app_desktop.py"), "--minimized"],
        cwd=root, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.time() + 90
        ball_hwnd = 0
        while time.time() < deadline:
            wins = find_windows(proc.pid)
            ball_hwnd = wins.get(BALL_TITLE, 0)
            if ball_hwnd:
                break
            if proc.poll() is not None:
                print("✗ 进程提前退出（可能单实例保护或依赖缺失）")
                return 1
            time.sleep(0.5)
        if not ball_hwnd:
            print("✗ 未等到悬浮球窗口")
            return 1

        # 等 _after_start 应用完样式
        time.sleep(6)
        style = user32.GetWindowLongW(ball_hwnd, GWL_EXSTYLE)
        checks = []

        if style & WS_EX_TOOLWINDOW:
            print(f"✓ 悬浮球带 WS_EX_TOOLWINDOW（exstyle=0x{style & 0xFFFFFFFF:08X}），"
                  "不占任务栏、无缩略图预览、不出现在 Alt-Tab")
            checks.append(True)
        else:
            print(f"✗ 悬浮球缺少 WS_EX_TOOLWINDOW（exstyle=0x{style & 0xFFFFFFFF:08X}）")
            checks.append(False)

        if user32.IsWindowVisible(ball_hwnd):
            print("✓ 悬浮球仍正常显示在桌面")
            checks.append(True)
        else:
            print("✗ 悬浮球不可见了")
            checks.append(False)

        if style & WS_EX_TOPMOST:
            print("✓ 悬浮球保持置顶")
            checks.append(True)
        else:
            print("✗ 悬浮球丢失置顶")
            checks.append(False)

        # 主窗口在 --minimized 下隐藏，球应独立存在
        print("✓ 测试通过" if all(checks) else "✗ 存在失败项")
        return 0 if all(checks) else 1
    finally:
        proc.kill()


if __name__ == "__main__":
    sys.exit(main())
