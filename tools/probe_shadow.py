# -*- coding: utf-8 -*-
"""阴影探针：验证哪种 DWM 属性组合能让 Win11 悬浮球窗口的阴影变小/消失。

在白色背景窗上摆 4 个 84x84 绿色球窗，各用不同 DWM 配置，截图对比：
  A  仅 ROUND                 —— 复现当前主程序状态（阴影基准）
  B  ROUND + NCRENDERING 禁用 —— 验证能否去阴影
  C  ROUND + BORDER_COLOR NONE + NCRENDERING 禁用
  D  DONOTROUND（对照组，应无圆角、看是否有阴影）
"""
import ctypes
import ctypes.wintypes as wt
import sys

user32 = ctypes.windll.user32
dwm = ctypes.windll.dwmapi

WS_POPUP = 0x80000000
WS_VISIBLE = 0x10000000
SW_SHOWNOACTIVATE = 4
COLOR_WINDOW = 10
WM_DESTROY = 2

DWMWA_NCRENDERING_POLICY = 2
DWMNCRP_DISABLED = 1
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWCP_DONOTROUND = 1
DWMWCP_ROUND = 2
DWMWCP_ROUNDSMALL = 3
DWMWA_BORDER_COLOR = 34
DWMWA_COLOR_NONE = 0xFFFFFFFE

S = 84  # 球尺寸
GAP = 60
BG_W, BG_H = 5 * S + 6 * GAP, S + 2 * GAP

WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_longlong, wt.HWND, ctypes.c_uint,
                             ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM)


user32.DefWindowProcW.argtypes = [wt.HWND, ctypes.c_uint, wt.WPARAM, wt.LPARAM]
user32.DefWindowProcW.restype = ctypes.c_longlong


def def_proc(hwnd, msg, wp, lp):
    if msg == WM_DESTROY:
        user32.PostQuitMessage(0)
    return user32.DefWindowProcW(hwnd, msg, wp, lp)


base_proc = WNDPROC(def_proc)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", ctypes.c_uint),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wt.HINSTANCE),
        ("hIcon", wt.HICON),
        ("hCursor", wt.HANDLE),
        ("hbrBackground", wt.HBRUSH),
        ("lpszMenuName", wt.LPCWSTR),
        ("lpszClassName", wt.LPCWSTR),
    ]


def register_class(name, color):
    wc = WNDCLASSW()
    wc.lpfnWndProc = base_proc
    wc.lpszClassName = name
    wc.hbrBackground = ctypes.c_void_p(color + 1)  # COLOR_x + 1
    wc.hInstance = ctypes.windll.kernel32.GetModuleHandleW(None)
    ctypes.windll.user32.RegisterClassW(ctypes.byref(wc))
    return wc.hInstance


def make_window(hinst, cls, title, x, y, w, h):
    hwnd = user32.CreateWindowExW(
        0, cls, title, WS_POPUP | WS_VISIBLE,
        x, y, w, h, None, None, hinst, None)
    user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
    return hwnd


def set_dword(hwnd, attr, value):
    v = wt.DWORD(value)
    dwm.DwmSetWindowAttribute(wt.HWND(hwnd), attr, ctypes.byref(v), 4)


def main():
    hinst = register_class("ProbeBG", 5)      # COLOR_WINDOW -> 系统白
    hinst_g = register_class("ProbeBall", 12)  # COLOR_BACKGROUND 黑?改用索引测试

    # 背景窗放屏幕左上角
    user32.SetProcessDPIAware()
    bg = make_window(hinst, "ProbeBG", "shadow-probe-bg", 0, 0, BG_W, BG_H)

    # 等背景画好
    import time
    time.sleep(0.4)
    user32.UpdateWindow(bg)

    x0, y0 = GAP, GAP
    wins = []
    for i in range(4):
        x = x0 + i * (S + GAP)
        hwnd = make_window(hinst_g, "ProbeBall", "shadow-probe-%d" % i,
                           x, y0, S, S)
        wins.append(hwnd)

    # A: 仅 ROUND（当前主程序状态）
    set_dword(wins[0], DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUND)

    # B: ROUND + NC rendering disabled
    set_dword(wins[1], DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUND)
    set_dword(wins[1], DWMWA_NCRENDERING_POLICY, DWMNCRP_DISABLED)

    # C: ROUND + 边框无色 + NC rendering disabled
    set_dword(wins[2], DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUND)
    set_dword(wins[2], DWMWA_BORDER_COLOR, DWMWA_COLOR_NONE)
    set_dword(wins[2], DWMWA_NCRENDERING_POLICY, DWMNCRP_DISABLED)

    # D: DONOTROUND 对照组
    set_dword(wins[3], DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_DONOTROUND)

    # E: ROUNDSMALL（小圆角，验证是否自带更小阴影）
    e = user32.CreateWindowExW(
        0, "ProbeBall", "shadow-probe-E", WS_POPUP | WS_VISIBLE,
        x0 + 4 * (S + GAP), y0, S, S, None, None, hinst, None)
    user32.ShowWindow(e, SW_SHOWNOACTIVATE)
    set_dword(e, DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUNDSMALL)

    print("PROBE_READY")
    sys.stdout.flush()

    # 消息循环保持存活，直到收到退出事件
    kernel32 = ctypes.windll.kernel32
    evt = kernel32.CreateEventW(None, True, False, "shadow_probe_exit")
    msg = wt.MSG()
    while True:
        r = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
        if r <= 0:
            break
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))
        if kernel32.WaitForSingleObject(evt, 50) == 0:
            break


if __name__ == "__main__":
    main()
