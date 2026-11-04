"""复现两个用户报告的问题：
1. 主窗口最小化收托盘后，任务栏是否残留点不动的主窗口条目
2. 托盘右键菜单关掉悬浮球后，再点「显示悬浮球」球是否还能回来

用法：C:/develop/Python/python.exe tools/test_tray_menu.py
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import subprocess
import sys
import time

user32 = ctypes.WinDLL("user32", use_last_error=True)
SW_MINIMIZE = 6
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


def get_rect(hwnd: int) -> tuple[int, int, int, int]:
    r = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def click(x: int, y: int, right: bool = False) -> None:
    user32.SetCursorPos(x, y)
    time.sleep(0.3)
    down, up = (8, 16) if right else (2, 4)
    user32.mouse_event(down, 0, 0, 0, 0)
    time.sleep(0.07)
    user32.mouse_event(up, 0, 0, 0, 0)


def setup_uia():
    global clr
    import clr  # noqa: PLC0415
    clr.AddReference(r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\WPF\UIAutomationClient.dll")
    clr.AddReference(r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\WPF\UIAutomationTypes.dll")


def uia_find_under(root, name: str):
    """在指定 UIA 子树下找 Name 匹配的元素（限定范围避免全树超时）。"""
    from System.Windows.Automation import AutomationElement, PropertyCondition, TreeScope
    cond = PropertyCondition(AutomationElement.NameProperty, name)
    return root.FindFirst(TreeScope.Descendants, cond)


def main() -> int:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass
    setup_uia()
    from System.Windows.Automation import (AutomationElement, PropertyCondition,
                                           TreeScope, ControlType)
    import System

    root = AutomationElement.RootElement
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = dict(os.environ)
    env["BCC_DATA_DIR"] = os.path.join(os.environ.get("TEMP", "."), "bcc_menu_test")
    proc = subprocess.Popen([sys.executable, os.path.join(root_dir, "backend", "app_desktop.py")],
                            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"启动 pid={proc.pid}")
    try:
        deadline = time.time() + 45
        wins: dict = {}
        while time.time() < deadline:
            wins = find_windows(proc.pid)
            if all(t in wins for t in TITLES):
                break
            time.sleep(0.5)
        else:
            print("✗ 未等到窗口")
            return 1
        time.sleep(2)

        # ---------- 问题 1：最小化收托盘后，任务栏还有没有主窗口条目 ----------
        user32.ShowWindow(wins["分支对话画布"], SW_MINIMIZE)
        time.sleep(3)
        vis = bool(user32.IsWindowVisible(wins["分支对话画布"]))
        print(f"最小化 3 秒后主窗口 visible={vis}（应为 False，已收托盘）")

        taskbar_hwnd = user32.FindWindowW("Shell_TrayWnd", None)
        taskbar = AutomationElement.FromHandle(System.IntPtr(taskbar_hwnd))
        btn = uia_find_under(taskbar, "分支对话画布")
        if btn is None:
            print("✓ 任务栏没有残留主窗口条目")
        else:
            print(f"✗ 任务栏仍残留主窗口条目: {btn.Current.BoundingRectangle}")

        # ---------- 问题 2：托盘菜单真实点击链路 ----------
        # 任务栏是自动隐藏的：先把鼠标移到底部唤出来
        sw, sh = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
        user32.SetCursorPos(sw // 2, sh - 2)
        time.sleep(1.2)
        # chevron（^ 展开溢出区）：TrayNotifyWnd 下第一个可见 Button
        user32.SetCursorPos(2127, 1560)
        time.sleep(0.3)
        click(2127, 1560)
        time.sleep(1.5)

        appbtn = None
        for _ in range(8):
            flyout_hwnd = user32.FindWindowW("TopLevelWindowForOverflowXamlIsland", None)
            if flyout_hwnd:
                flyout = AutomationElement.FromHandle(System.IntPtr(flyout_hwnd))
                appbtn = uia_find_under(flyout, "分支对话画布")
                if appbtn is not None:
                    break
            # flyout 可能没弹出来，再点一次箭头
            user32.SetCursorPos(sw // 2, sh - 2)
            time.sleep(0.8)
            click(2127, 1560)
            time.sleep(1.2)
        if appbtn is None:
            print("✗ 溢出区里没找到应用图标")
            return 1
        ar = appbtn.Current.BoundingRectangle
        cx, cy = (int(ar.Left) + int(ar.Right)) // 2, (int(ar.Top) + int(ar.Bottom)) // 2
        print(f"溢出区应用图标中心: ({cx},{cy})")

        ball_hwnd = find_windows(proc.pid)["悬浮球"]

        def popup_menu_item(label: str):
            """右键后从 root 的直接子级里找弹出菜单项。"""
            menu_cond = PropertyCondition(AutomationElement.ControlTypeProperty, ControlType.Menu)
            for _ in range(12):
                menus = root.FindAll(TreeScope.Children, menu_cond)
                for m in menus:
                    it = uia_find_under(m, label)
                    if it is not None:
                        return it
                time.sleep(0.25)
            return None

        # 第一次：右键 → 点「显示悬浮球」（当前勾选，点击=取消 → 隐藏球）
        click(cx, cy, right=True)
        time.sleep(0.7)
        item = popup_menu_item("显示悬浮球")
        if item is None:
            print("✗ 右键菜单没弹出来")
            return 1
        mr = item.Current.BoundingRectangle
        click((int(mr.Left) + int(mr.Right)) // 2, (int(mr.Top) + int(mr.Bottom)) // 2)
        time.sleep(1.5)
        v1 = bool(user32.IsWindowVisible(ball_hwnd))
        print(f"① 菜单取消勾选后 悬浮球 visible={v1}（应为 False）")

        # 第二次：重新展开 flyout → 右键 → 点「显示悬浮球」（这次=勾上 → 显示球）
        user32.SetCursorPos(sw // 2, sh - 2)
        time.sleep(0.8)
        click(2127, 1560)
        time.sleep(1.5)
        click(cx, cy, right=True)
        time.sleep(0.7)
        item = popup_menu_item("显示悬浮球")
        if item is None:
            print("✗ 第二次右键菜单没弹出来")
            return 1
        mr = item.Current.BoundingRectangle
        click((int(mr.Left) + int(mr.Right)) // 2, (int(mr.Top) + int(mr.Bottom)) // 2)
        time.sleep(1.8)
        v2 = bool(user32.IsWindowVisible(ball_hwnd))
        print(f"② 菜单再次勾选后 悬浮球 visible={v2}（应为 True —— 用户报告此处没反应）")
        return 0
    finally:
        time.sleep(0.3)
        if proc.poll() is None:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
