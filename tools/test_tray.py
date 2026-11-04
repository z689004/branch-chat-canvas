"""回归：系统托盘驻留。

覆盖：
1. 启动后托盘图标就绪（get_desktop_config().trayVisible）
2. 主窗口最小化 → 收进托盘（窗口隐藏，任务栏不留空壳）
3. 托盘「打开主界面」 → 窗口还原可见
4. 悬浮球开关（托盘菜单同款 API）正常
5. 退出软件 → 进程结束

用法：C:/develop/Python/python.exe tools/test_tray.py [--exe]
"""
from __future__ import annotations

import asyncio
import ctypes
import ctypes.wintypes as wt
import json
import os
import subprocess
import sys
import time
import urllib.request

user32 = ctypes.WinDLL("user32", use_last_error=True)
SW_MINIMIZE = 6
CDP_PORT = 9223
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


def cdp_target():
    with urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json/list", timeout=3) as r:
        pages = json.loads(r.read().decode())
    for p in pages:
        if p.get("type") == "page" and "mini" not in (p.get("url") or ""):
            return p["webSocketDebuggerUrl"]
    return None


async def _evaluate(ws_url: str, expr: str):
    import websockets

    async with websockets.connect(ws_url, max_size=8 * 1024 * 1024) as ws:
        await ws.send(json.dumps({
            "id": 1, "method": "Runtime.evaluate",
            "params": {"expression": expr, "awaitPromise": True, "returnByValue": True},
        }))
        while True:
            msg = json.loads(await ws.recv())
            if msg.get("id") == 1:
                res = msg.get("result", {})
                if "exceptionDetails" in res:
                    raise RuntimeError(res["exceptionDetails"].get("text") or "JS 执行异常")
                return res.get("result", {}).get("value")


def evaluate(ws_url: str, expr: str):
    return asyncio.run(_evaluate(ws_url, expr))


def main() -> int:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    use_exe = "--exe" in sys.argv
    env = dict(os.environ)
    env["BCC_DATA_DIR"] = os.path.join(os.environ.get("TEMP", "."), "bcc_tray_test")
    env["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = f"--remote-debugging-port={CDP_PORT}"
    cmd = ([os.path.join(root, "dist-exe", "BranchChatCanvas.exe")] if use_exe
           else [sys.executable, os.path.join(root, "backend", "app_desktop.py")])
    proc = subprocess.Popen(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"启动 pid={proc.pid}（{'exe' if use_exe else '源码'}）")

    try:
        deadline = time.time() + (90 if use_exe else 45)
        wins: dict[str, int] = {}
        while time.time() < deadline:
            wins = find_windows(0 if use_exe else proc.pid)
            if all(t in wins for t in TITLES):
                break
            time.sleep(0.5)
        else:
            print("✗ 未等到窗口", list(wins))
            return 1

        # 等 CDP 与 pywebview API 就绪
        ws_url = None
        deadline = time.time() + 40
        while time.time() < deadline:
            try:
                ws_url = cdp_target()
            except Exception:
                ws_url = None
            if ws_url:
                try:
                    ok = evaluate(ws_url, "!!(window.pywebview && window.pywebview.api)")
                    if ok:
                        break
                except Exception:
                    pass
            time.sleep(1)
        else:
            print("✗ CDP 未就绪")
            return 1

        cfg = evaluate(ws_url, "window.pywebview.api.get_desktop_config()")
        if not cfg or not cfg.get("trayVisible"):
            print(f"✗ 托盘图标未就绪：{cfg}")
            return 1
        print("✓ 托盘图标已就绪（trayVisible=True）")

        main_hwnd = find_windows(0 if use_exe else proc.pid)["分支对话画布"]
        user32.ShowWindow(main_hwnd, SW_MINIMIZE)
        time.sleep(2.5)
        vis = bool(user32.IsWindowVisible(main_hwnd))
        if vis:
            print("✗ 最小化后窗口仍然可见，没有收进托盘")
            return 1
        print("✓ 最小化后窗口已隐藏（收进托盘，任务栏不留空壳）")

        evaluate(ws_url, "window.pywebview.api.activate_main()")
        time.sleep(1.5)
        vis = bool(user32.IsWindowVisible(main_hwnd))
        iconic = bool(user32.IsIconic(main_hwnd))
        if not vis or iconic:
            print(f"✗ 唤起失败：visible={vis} iconic={iconic}")
            return 1
        print("✓ 托盘「打开主界面」把窗口还原并激活")

        evaluate(ws_url, "window.pywebview.api.show_ball(false)")
        time.sleep(1.2)
        if "悬浮球" in find_windows(0 if use_exe else proc.pid):
            ball_win = find_windows(0 if use_exe else proc.pid)["悬浮球"]
            if user32.IsWindowVisible(ball_win):
                print("✗ 关闭悬浮球后仍然可见")
                return 1
        print("✓ 托盘菜单「显示悬浮球」关闭生效")

        evaluate(ws_url, "window.pywebview.api.show_ball(true)")
        time.sleep(1.2)
        wins2 = find_windows(0 if use_exe else proc.pid)
        if "悬浮球" not in wins2 or not user32.IsWindowVisible(wins2["悬浮球"]):
            print("✗ 重新显示悬浮球失败")
            return 1
        print("✓ 再次打开悬浮球生效")

        evaluate(ws_url, "window.pywebview.api.show_ball(true)")
        time.sleep(0.3)
        if os.getenv("BCC_TRAY_KEEP") != "1":
            evaluate(ws_url, "window.pywebview.api.quit_app()")
            for _ in range(20):
                time.sleep(0.5)
                if proc.poll() is not None:
                    print("✓ 退出软件：进程已结束")
                    return 0
            print("✗ 退出软件后进程仍在")
            return 1
        print("（已按 BCC_TRAY_KEEP=1 保留进程，手动检查托盘）")
        return 0
    finally:
        time.sleep(0.3)
        if proc.poll() is None:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
