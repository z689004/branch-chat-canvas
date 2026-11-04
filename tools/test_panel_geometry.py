# -*- coding: utf-8 -*-
"""快速面板拖动 / 缩放回归测试：真实鼠标事件 + 窗口几何读取。"""
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
    send(0x0002)  # LEFTDOWN
    time.sleep(0.05)
    send(0x0004)  # LEFTUP
    time.sleep(0.4)


def drag(x1, y1, x2, y2, steps=24, hold=0.02):
    move_to(x1, y1)
    time.sleep(0.25)
    send(0x0002)
    time.sleep(0.12)
    for i in range(1, steps + 1):
        move_to(x1 + (x2 - x1) * i / steps, y1 + (y2 - y1) * i / steps)
        time.sleep(hold)
    time.sleep(0.2)
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
            res.append((h, r.left, r.top, r.right, r.bottom))
        return True

    CB = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    u.EnumWindows(CB(cb), 0)
    return res[0] if res else None


def rect_str(t):
    _, l, tp, r, b = t
    return f"{r - l}x{b - tp} @ ({l}, {tp})"


def main():
    t = find_ball()
    if not t:
        print("FAIL 未找到悬浮球窗口")
        return 1
    print("球窗口：", rect_str(t))
    _, l, tp, r, b = t
    click((l + r) // 2, (tp + b) // 2)
    time.sleep(1.0)

    t = find_ball()
    print("展开后：", rect_str(t))
    _, l, tp, r, b = t
    w, h = r - l, b - tp
    if w < 200:
        print("FAIL 面板没有展开")
        return 1

    # 1) 拖动标题栏：向左上移动 (-140, -80)
    drag(l + w // 2, tp + 20, l + w // 2 - 140, tp + 20 - 80)
    t2 = find_ball()
    print("拖动后：", rect_str(t2))
    dx, dy = t2[1] - l, t2[2] - tp
    print(f"  位移 = ({dx}, {dy})  期望 ≈ (-140, -80)")
    ok_drag = abs(dx + 140) <= 8 and abs(dy + 80) <= 8

    # 2) 右下角缩放：拉大 (+100, +90)
    l2, tp2, r2, b2 = t2[1], t2[2], t2[3], t2[4]
    drag(r2 - 8, b2 - 8, r2 - 8 + 100, b2 - 8 + 90)
    t3 = find_ball()
    print("放大后：", rect_str(t3))
    dw = (t3[3] - t3[1]) - (r2 - l2)
    dh = (t3[4] - t3[2]) - (b2 - tp2)
    print(f"  尺寸变化 = ({dw}, {dh})  期望 ≈ (+100, +90)")
    ok_grow = abs(dw - 100) <= 10 and abs(dh - 90) <= 10

    # 3) 缩到最小：往回拉很多，应被限制在最小值 320x380
    l3, tp3, r3, b3 = t3[1], t3[2], t3[3], t3[4]
    drag(r3 - 8, b3 - 8, r3 - 8 - 600, b3 - 8 - 600)
    t4 = find_ball()
    print("缩小后：", rect_str(t4))
    scale = ctypes.c_uint()
    dpi = u.GetDpiForSystem()
    scale = dpi / 96.0
    w4, h4 = (t4[3] - t4[1]) / scale, (t4[4] - t4[2]) / scale
    print(f"  逻辑尺寸 = {w4:.0f}x{h4:.0f}  期望 >= 320x380 且接近最小值")
    ok_min = 318 <= w4 <= 340 and 378 <= h4 <= 400

    print("\n结果：拖动", "OK" if ok_drag else "FAIL",
          "| 放大", "OK" if ok_grow else "FAIL",
          "| 最小尺寸", "OK" if ok_min else "FAIL")

    # 4) 收起再展开：应回到刚拖好的位置与尺寸
    l4, tp4, r4, b4 = t4[1], t4[2], t4[3], t4[4]
    click(r4 - 22, tp4 + 20)          # 头部「—」收起按钮
    time.sleep(0.9)
    tb = find_ball()
    print("收起后：", rect_str(tb))
    click((tb[1] + tb[3]) // 2, (tb[2] + tb[4]) // 2)
    time.sleep(1.2)
    t5 = find_ball()
    print("再次展开：", rect_str(t5), "期望 =", rect_str(t4))
    ok_restore = abs(t5[1] - l4) <= 8 and abs(t5[2] - tp4) <= 8 \
        and abs((t5[3] - t5[1]) - (r4 - l4)) <= 8 and abs((t5[4] - t5[2]) - (b4 - tp4)) <= 8
    print("| 记忆恢复", "OK" if ok_restore else "FAIL")
    return 0 if (ok_drag and ok_grow and ok_min and ok_restore) else 2


if __name__ == "__main__":
    sys.exit(main())
