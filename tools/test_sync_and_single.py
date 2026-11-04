"""回归：单实例唤起 + 托盘改配置后前端同步。

1. 起第一个实例（收进托盘状态）
2. 起第二个实例 → 应立即退出，且第一个实例的主窗口被唤到前台
3. CDP 调 show_ball(false)（等价托盘关球）→ 主窗口前端 el-switch 应自动变为未选中
4. 前端点击设置面板开关 → 后端状态正确翻转（不因本地状态错乱而发错方向）

用法：C:/develop/Python/python.exe tools/test_sync_and_single.py [--exe]
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
CDP_PORT = 9225


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


def cdp_ws():
    with urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json/list", timeout=3) as r:
        pages = json.loads(r.read().decode())
    for p in pages:
        if p.get("type") == "page" and "mini" not in (p.get("url") or ""):
            return p["webSocketDebuggerUrl"]
    return None


async def _eval(ws_url: str, expr: str):
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
                    raise RuntimeError(res["exceptionDetails"].get("text") or "JS error")
                return res.get("result", {}).get("value")


def ev(ws_url: str, expr: str, timeout: float = 15.0):
    async def _run():
        return await asyncio.wait_for(_eval(ws_url, expr), timeout=timeout)
    return asyncio.run(_run())


def main() -> int:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    use_exe = "--exe" in sys.argv
    env = dict(os.environ)
    env["BCC_DATA_DIR"] = os.path.join(os.environ.get("TEMP", "."), "bcc_sync_test")
    env["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = f"--remote-debugging-port={CDP_PORT}"
    cmd = ([os.path.join(root, "dist-exe", "BranchChatCanvas.exe")] if use_exe
           else [sys.executable, os.path.join(root, "backend", "app_desktop.py")])

    p1 = subprocess.Popen(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"实例1 pid={p1.pid}")
    deadline = time.time() + (90 if use_exe else 45)
    while time.time() < deadline:
        wins = find_windows(0 if use_exe else p1.pid)
        if all(t in wins for t in ("分支对话画布", "悬浮球")):
            break
        time.sleep(0.5)
    else:
        print("✗ 实例1 未就绪")
        p1.kill()
        return 1

    # 把主窗口最小化收托盘，制造"用户看不到窗口"的场景
    user32.ShowWindow(find_windows(0 if use_exe else p1.pid)["分支对话画布"], 6)
    time.sleep(2.5)

    # ---------- 单实例：第二个实例应立即退出并唤起主窗口 ----------
    p2 = subprocess.Popen(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"实例2 pid={p2.pid}（应自退）")
    t0 = time.time()
    while time.time() - t0 < 20 and p2.poll() is None:
        time.sleep(0.3)
    if p2.poll() is None:
        print("✗ 第二个实例 20 秒未退出")
        p2.kill()
        p1.kill()
        return 1
    if p2.returncode != 0:
        print(f"✗ 第二个实例异常退出：{p2.returncode}")
        p1.kill()
        return 1
    print(f"✓ 第二个实例 {time.time() - t0:.1f}s 内退出（退出码 {p2.returncode}）")

    main_hwnd = user32.FindWindowW(None, "分支对话画布")
    time.sleep(1.5)
    vis = bool(user32.IsWindowVisible(main_hwnd))
    fg = user32.GetForegroundWindow()
    if not vis:
        print("✗ 主窗口未被唤起")
        p1.kill()
        return 1
    print(f"✓ 主窗口已被唤起（visible=True，前台={'是' if fg == main_hwnd else '否'}）")

    # ---------- 配置推送：后端改状态 → 前端自动同步 ----------
    # 装 spy 记录推送
    ws = None
    deadline = time.time() + 40
    while time.time() < deadline:
        try:
            ws = cdp_ws()
        except Exception:
            ws = None
        if ws:
            try:
                if ev(ws, "!!(window.pywebview && window.pywebview.api)"):
                    break
            except Exception:
                pass
        time.sleep(1)
    else:
        print("✗ CDP 未就绪")
        p1.kill()
        return 1

    ev(ws, "window.__cfgPushes=[]; const __orig=window.__onDesktopCfgChanged; window.__onDesktopCfgChanged=(c)=>{window.__cfgPushes.push(c.showBall); __orig&&__orig(c)}; true")

    ev(ws, "window.pywebview.api.show_ball(false)")  # 等价于托盘菜单关掉悬浮球
    time.sleep(2.0)
    pushes = ev(ws, "window.__cfgPushes")
    sw_checked = ev(ws, "!!document.querySelector('.el-switch.is-checked')")
    print(f"后端关球后：前端收到推送={pushes}，设置面板开关显示为开={sw_checked}")
    if not pushes or pushes[-1] is not False:
        print("✗ 后端改状态后前端没有收到配置推送")
        p1.kill()
        return 1
    if sw_checked:
        print("✗ 前端开关仍显示为开，状态未同步")
        p1.kill()
        return 1
    print("✓ 托盘/球改状态后，主界面设置面板开关自动同步为关")

    # ---------- 开关方向：前端点击开关 → 球应显示 ----------
    ev(ws, "window.pywebview.api.set_desktop_config({showBall:false})")
    time.sleep(1.5)
    # 找设置面板里的开关：打开设置对话框再点
    ev(ws, "window.__openBallSettings ? window.__openBallSettings() : null")
    # 直接模拟点击对话框中的第一个 el-switch
    ev(ws, """
      (async () => {
        const dlg = document.querySelector('.el-dialog')
        if (!dlg) throw new Error('设置对话框未打开')
        const sw = dlg.querySelector('.el-switch')
        sw && sw.click()
        return true
      })()
    """)
    time.sleep(2.5)
    ball_hwnd = user32.FindWindowW(None, "悬浮球")
    v = bool(user32.IsWindowVisible(ball_hwnd))
    cfg = ev(ws, "window.pywebview.api.get_desktop_config()")
    print(f"点击开关后：球 visible={v}，后端 showBall={cfg.get('showBall')}")
    if not (v and cfg.get("showBall")):
        print("✗ 前端点击开关后球未显示（方向错乱仍在）")
        p1.kill()
        return 1
    print("✓ 前端开关点击方向正确：一次点击即显示悬浮球")
    p1.kill()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
