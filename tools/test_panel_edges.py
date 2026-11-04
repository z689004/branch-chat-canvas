# -*- coding: utf-8 -*-
"""快速面板八方向缩放回归：逐个拖四条边与四个角，验证「被拖的边跟着走、对边不动」."""
import ctypes, time, sys
from ctypes import wintypes

ctypes.windll.shcore.SetProcessDpiAwareness(2)
u = ctypes.windll.user32
BALL_TITLE = "悬浮球"


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long), ("mouseData", ctypes.c_ulong),
                ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class INPUT(ctypes.Structure):
    class _I(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT)]
    _anonymous_ = ("_i",)
    _fields_ = [("type", ctypes.c_ulong), ("_i", _I)]


def send(flags, x=0, y=0):
    i = INPUT()
    i.type = 0
    i.mi.dx, i.mi.dy = int(x), int(y)
    i.mi.dwFlags = flags
    u.SendInput(1, ctypes.byref(i), ctypes.sizeof(INPUT))


def move_to(x, y):
    u.SetCursorPos(int(x), int(y))


def click(x, y):
    move_to(x, y)
    time.sleep(0.2)
    send(0x0002)
    time.sleep(0.05)
    send(0x0004)
    time.sleep(0.45)


def drag(x1, y1, x2, y2, steps=24, hold=0.02):
    move_to(x1, y1)
    time.sleep(0.22)
    send(0x0002)
    time.sleep(0.12)
    for i in range(1, steps + 1):
        move_to(x1 + (x2 - x1) * i / steps, y1 + (y2 - y1) * i / steps)
        time.sleep(hold)
    time.sleep(0.18)
    send(0x0004)
    time.sleep(0.5)


def find_ball():
    res = []

    def cb(h, l):
        if not u.IsWindowVisible(h):
            return True
        n = ctypes.create_unicode_buffer(256)
        u.GetWindowTextW(h, n, 256)
        if n.value == BALL_TITLE:
            r = wintypes.RECT()
            u.GetWindowRect(h, ctypes.byref(r))
            res.append((r.left, r.top, r.right, r.bottom))
        return True

    CB = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    u.EnumWindows(CB(cb), 0)
    return res[0] if res else None


def work_area():
    r = wintypes.RECT()
    u.SystemParametersInfoW(0x0030, 0, ctypes.byref(r), 0)
    return r.left, r.top, r.right, r.bottom


def fmt(t):
    return f"{t[2] - t[0]}x{t[3] - t[1]} @ ({t[0]}, {t[1]})"


def main():
    t = find_ball()
    if not t:
        print("FAIL 未找到悬浮球窗口")
        return 1
    # 确保面板处于展开态
    if t[2] - t[0] < 200:
        click((t[0] + t[2]) // 2, (t[1] + t[3]) // 2)
        time.sleep(1.2)
        t = find_ball()
    if not t or t[2] - t[0] < 200:
        print("FAIL 面板未展开")
        return 1

    wl, wt, wr, wb = work_area()
    # 挪到工作区中部，避免贴边被夹
    l, tp, r, b = t
    drag((l + r) // 2, tp + 20, 700, 220)
    t = find_ball()
    print("起始：", fmt(t))

    results = []

    def check(name, before, after, moved_edges, still_edges, dx, dy, tol=14):
        """moved_edges: 应该跟着位移的边；still_edges: 应保持不动的边"""
        idx = {"l": 0, "t": 1, "r": 2, "b": 3}
        exp = {"l": dx, "t": dy, "r": 0, "b": 0}
        # 被拖的边位移 = 鼠标位移；对边位移 = 0
        ok = True
        detail = []
        for e in moved_edges:
            got = after[idx[e]] - before[idx[e]]
            want = {"l": dx, "t": dy, "r": dx, "b": dy}[e]
            detail.append(f"{e}:{got}(期望{want})")
            ok = ok and abs(got - want) <= tol
        for e in still_edges:
            got = after[idx[e]] - before[idx[e]]
            detail.append(f"{e}:{got}(期望0)")
            ok = ok and abs(got) <= tol
        results.append((name, ok))
        print(f"  {name}: {'OK' if ok else 'FAIL'}  " + " ".join(detail))

    # 1) 左边缘 w：向左拉 90
    l, tp, r, b = t
    drag(l + 4, (tp + b) // 2, l + 4 - 90, (tp + b) // 2)
    t2 = find_ball()
    check("左边缘 w", t, t2, ["l"], ["r"], -90, 0)

    # 2) 上边缘 n：向上拉 80
    l, tp, r, b = t2
    drag((l + r) // 2, tp + 4, (l + r) // 2, tp + 4 - 80)
    t3 = find_ball()
    check("上边缘 n", t2, t3, ["t"], ["b"], 0, -80)

    # 3) 左上角 nw：向左上 60
    l, tp, r, b = t3
    drag(l + 6, tp + 6, l + 6 - 60, tp + 6 - 60)
    t4 = find_ball()
    check("左上角 nw", t3, t4, ["l", "t"], ["r", "b"], -60, -60)

    # 4) 右上角 ne：向右上 60
    l, tp, r, b = t4
    drag(r - 6, tp + 6, r - 6 + 60, tp + 6 - 60)
    t5 = find_ball()
    check("右上角 ne", t4, t5, ["r", "t"], ["l", "b"], 60, -60)

    # 5) 左下角 sw：向左下 60
    l, tp, r, b = t5
    drag(l + 6, b - 6, l + 6 - 60, b - 6 + 60)
    t6 = find_ball()
    check("左下角 sw", t5, t6, ["l", "b"], ["r", "t"], -60, 60)

    # 6) 右下角 se：向右下 60
    l, tp, r, b = t6
    drag(r - 6, b - 6, r - 6 + 60, b - 6 + 60)
    t7 = find_ball()
    check("右下角 se", t6, t7, ["r", "b"], ["l", "t"], 60, 60)

    bad = [n for n, ok in results if not ok]
    print("\n结果：", "全部通过" if not bad else "失败项 " + ", ".join(bad))
    return 0 if not bad else 2


if __name__ == "__main__":
    sys.exit(main())
