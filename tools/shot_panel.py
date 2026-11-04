# -*- coding: utf-8 -*-
"""面板视觉检查：指定尺寸截图。"""
import ctypes, sys, time
from ctypes import wintypes

ctypes.windll.shcore.SetProcessDpiAwareness(2)
u = ctypes.windll.user32
from PIL import ImageGrab


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long), ("mouseData", ctypes.c_ulong),
                ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class INPUT(ctypes.Structure):
    class _I(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT)]
    _anonymous_ = ("_i",)
    _fields_ = [("type", ctypes.c_ulong), ("_i", _I)]


def send(flags):
    i = INPUT(); i.type = 0; i.mi.dwFlags = flags
    u.SendInput(1, ctypes.byref(i), ctypes.sizeof(INPUT))


def drag(x1, y1, x2, y2, steps=26):
    u.SetCursorPos(int(x1), int(y1)); time.sleep(0.25)
    send(0x0002); time.sleep(0.12)
    for i in range(1, steps + 1):
        u.SetCursorPos(int(x1 + (x2 - x1) * i / steps), int(y1 + (y2 - y1) * i / steps))
        time.sleep(0.02)
    time.sleep(0.2); send(0x0004); time.sleep(0.6)


def find_ball():
    res = []

    def cb(h, l):
        if not u.IsWindowVisible(h):
            return True
        n = ctypes.create_unicode_buffer(256); u.GetWindowTextW(h, n, 256)
        if n.value == "悬浮球":
            r = wintypes.RECT(); u.GetWindowRect(h, ctypes.byref(r))
            res.append((r.left, r.top, r.right, r.bottom))
        return True

    CB = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    u.EnumWindows(CB(cb), 0)
    return res[0] if res else None


def shot(path, pad=12):
    l, t, r, b = find_ball()
    im = ImageGrab.grab(bbox=(l - pad, t - pad, r + pad, b + pad), all_screens=True)
    im.save(path)
    print(path, im.size, f"win={(r-l)}x{(b-t)}")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "small"
    if mode == "grow":
        l, t, r, b = find_ball()
        drag(r - 8, b - 8, r - 8 + 380, b - 8 + 620)
    shot(f"C:/Users/liuzhijun/AppData/Local/Temp/mini_{mode}.png")
