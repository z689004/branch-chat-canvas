# -*- coding: utf-8 -*-
"""桌面版启动器（独立窗口，不依赖浏览器）。

- 用 pywebview 创建原生窗口（Windows 下使用系统自带的 Edge WebView2 内核）
- 在后台线程启动 FastAPI/uvicorn，窗口指向本机回环地址
- 数据目录：exe 同级 data/（可用 BCC_DATA_DIR 覆盖），便携可迁移
- 全局悬浮球：无边框置顶小窗，支持原生拖拽、贴边吸附、右键菜单

环境变量：
    BCC_DATA_DIR   数据目录（默认 exe 同级 data/）
    BCC_PORT       指定端口（默认自动挑选空闲端口）
    BCC_DEBUG      "1" 时打开 DevTools

命令行：
    --minimized    启动时只显示悬浮球，不弹出主窗口（开机自启用）
"""
import ctypes
import json
import logging
import os
import socket
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path

# ---------- 常量 ----------
MAIN_TITLE = "分支对话画布"
BALL_TITLE = "悬浮球"
BALL_SIZE = 42
PANEL_SIZE = (420, 620)
PANEL_MIN = (320, 380)      # 快速面板可缩到的最小尺寸
PANEL_AXES = ("n", "s", "e", "w", "ne", "nw", "se", "sw")   # 可拖拽缩放的边 / 角
MENU_SIZE = (212, 306)      # 右键菜单展开时的窗口尺寸（球固定在右下角）
SNAP_THRESHOLD = 32         # 距工作区边缘多少像素内自动吸附
CLICK_TOLERANCE = 4         # 位移小于该值视为"点击"而非拖拽
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "BranchChatCanvas"

# ---------- 桌面配置（持久化在 data/desktop.json） ----------
DESKTOP_CFG = {
    "showBall": True,       # 是否显示悬浮球
    "autoStart": False,     # 是否开机自启
    "ballX": None,          # 上次悬浮球位置（None = 默认右下角）
    "ballY": None,
    "panelW": PANEL_SIZE[0],  # 快速面板尺寸（用户拖动缩放后记住）
    "panelH": PANEL_SIZE[1],
    "panelX": None,           # 上次快速面板位置（None = 贴着球展开）
    "panelY": None,
}

log = logging.getLogger("desktop")


def _user32():
    return ctypes.windll.user32


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


def _screen_size() -> tuple:
    """主屏分辨率（工作区取不到时兜底）。"""
    try:
        u = _user32()
        return int(u.GetSystemMetrics(0)), int(u.GetSystemMetrics(1))
    except Exception:  # noqa: BLE001
        return 1920, 1080


def work_area() -> _RECT:
    """主屏可用工作区（已扣除任务栏），吸附以此为边界。"""
    r = _RECT()
    try:
        if not _user32().SystemParametersInfoW(0x0030, 0, ctypes.byref(r), 0):  # SPI_GETWORKAREA
            raise OSError("SPI_GETWORKAREA failed")
        if r.right <= r.left or r.bottom <= r.top:
            raise OSError("empty work area")
    except Exception:  # noqa: BLE001
        sw, sh = _screen_size()
        r.left, r.top, r.right, r.bottom = 0, 0, sw, sh
    return r


def find_window(title: str) -> int:
    """按标题在**本进程**内查找顶层窗口句柄（不会命中其他程序的同名窗口）。"""
    try:
        user32 = _user32()
    except Exception:  # noqa: BLE001
        return 0
    pid = os.getpid()
    hits: list = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _enum(hwnd, _lparam):
        proc = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(proc))
        if proc.value == pid:
            n = user32.GetWindowTextLengthW(hwnd)
            if n > 0:
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                if buf.value == title:
                    hits.append(int(hwnd))
                    return False
        return True

    try:
        user32.EnumWindows(_enum, 0)
    except Exception:  # noqa: BLE001
        return 0
    return hits[0] if hits else 0


def window_rect(hwnd: int) -> _RECT:
    r = _RECT()
    if hwnd:
        _user32().GetWindowRect(hwnd, ctypes.byref(r))
    return r


def ui_scale(hwnd: int = 0) -> float:
    """物理像素 / 逻辑像素 的比例（系统 150% 缩放时为 1.5）。

    pywebview 的 move()/resize() 接收**逻辑像素**，而 GetWindowRect 与
    SystemParametersInfo 返回**物理像素**，混用会导致位置整体偏移。
    """
    try:
        u = _user32()
        dpi = int(u.GetDpiForWindow(hwnd)) if hwnd else int(u.GetDpiForSystem())
        return (dpi / 96.0) if dpi > 0 else 1.0
    except Exception:  # noqa: BLE001
        return 1.0


def work_area_ui(hwnd: int = 0) -> _RECT:
    """可用工作区，换算成逻辑像素（与 pywebview 的 move/resize 单位一致）。"""
    r = work_area()
    s = ui_scale(hwnd)
    if s != 1:
        return _RECT(int(r.left / s), int(r.top / s), int(r.right / s), int(r.bottom / s))
    return r


def window_rect_ui(hwnd: int) -> _RECT:
    """窗口矩形，换算成逻辑像素。"""
    r = window_rect(hwnd)
    s = ui_scale(hwnd)
    if s != 1:
        return _RECT(int(r.left / s), int(r.top / s), int(r.right / s), int(r.bottom / s))
    return r


def app_root() -> Path:
    """打包后为 PyInstaller 解包目录；源码运行为仓库根目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)  # noqa: SLF001
    return Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    env = os.getenv("BCC_DATA_DIR")
    if env:
        p = Path(env)
    else:
        exe = Path(sys.executable)
        base = exe.parent if getattr(sys, "frozen", False) else app_root()
        p = base / "data"
    p.mkdir(parents=True, exist_ok=True)
    return p


def config_file() -> Path:
    return data_dir() / "desktop.json"


def load_desktop_config() -> dict:
    try:
        raw = json.loads(config_file().read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            for k in list(DESKTOP_CFG):
                if k in raw:
                    DESKTOP_CFG[k] = raw[k]
    except FileNotFoundError:
        pass
    except Exception:  # noqa: BLE001
        log.exception("读取桌面配置失败，使用默认值")
    return dict(DESKTOP_CFG)


def save_desktop_config() -> None:
    try:
        config_file().write_text(
            json.dumps(DESKTOP_CFG, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001
        log.exception("保存桌面配置失败")


def apply_autostart(on: bool) -> bool:
    """写入/删除 HKCU 开机启动项（无需管理员权限）。仅打包后的 exe 有意义。"""
    if not getattr(sys, "frozen", False):
        log.warning("源码运行模式不支持开机启动（请使用打包后的 exe）")
        return False
    try:
        import winreg

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            if on:
                cmd = f'"{sys.executable}" --minimized'
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, cmd)
                log.info("已设置开机启动：%s", cmd)
            else:
                try:
                    winreg.DeleteValue(key, APP_NAME)
                    log.info("已取消开机启动")
                except FileNotFoundError:
                    pass
        return True
    except Exception:  # noqa: BLE001
        log.exception("设置开机启动失败")
        return False


def initial_ball_pos() -> tuple:
    """悬浮球初始位置（逻辑像素）：优先上次保存值，否则贴右下角，并保证在工作区内。"""
    r = work_area_ui(0)
    x = DESKTOP_CFG.get("ballX")
    y = DESKTOP_CFG.get("ballY")
    if x is None or y is None:
        x = r.right - BALL_SIZE - 24
        y = r.bottom - BALL_SIZE - 96
    x = min(max(int(x), r.left), max(r.left, r.right - BALL_SIZE))
    y = min(max(int(y), r.top), max(r.top, r.bottom - BALL_SIZE))
    return x, y


def panel_size() -> tuple:
    """快速面板尺寸（逻辑像素）：优先上次用户拖出来的尺寸，并夹在合理范围内。"""
    work = work_area_ui(0)
    try:
        w = int(DESKTOP_CFG.get("panelW") or PANEL_SIZE[0])
        h = int(DESKTOP_CFG.get("panelH") or PANEL_SIZE[1])
    except Exception:  # noqa: BLE001
        w, h = PANEL_SIZE
    w = max(PANEL_MIN[0], min(w, max(PANEL_MIN[0], work.right - work.left)))
    h = max(PANEL_MIN[1], min(h, max(PANEL_MIN[1], work.bottom - work.top)))
    return w, h


def resized_rect(axis: str, st: dict, dx: int, dy: int, work: tuple) -> tuple:
    """按拖拽的边 / 角计算新的 (x, y, w, h)。

    位移始终相对"按下瞬间"的几何计算，而不是逐帧累加——
    这样即使某一帧被工作区或最小尺寸夹住，也不会产生累积漂移。
    axis 里的 n/s 表示上下边，e/w 表示左右边，角是两个字母组合。
    """
    west, east = "w" in axis, "e" in axis
    north, south = "n" in axis, "s" in axis
    x, y, w, h = st["x"], st["y"], st["w"], st["h"]

    if east:
        w = st["w"] + dx
    elif west:
        w = st["w"] - dx
    if south:
        h = st["h"] + dy
    elif north:
        h = st["h"] - dy

    # 顶到最小尺寸时，被拖的边停住，对边保持不动
    w = max(PANEL_MIN[0], w)
    h = max(PANEL_MIN[1], h)
    if west:
        x = st["x"] + st["w"] - w
    if north:
        y = st["y"] + st["h"] - h

    # 越过工作区边界时同样保持对边不动（把拖拽方向"顶住"）
    wl, wt, _wr, _wb = work
    if west and x < wl:
        x = wl
        w = st["x"] + st["w"] - wl
    if north and y < wt:
        y = wt
        h = st["y"] + st["h"] - wt
    return x, y, w, h


def find_free_port(start: int = 8765, tries: int = 80) -> int:
    """从 start 起找一个空闲端口。绑定 0.0.0.0 探测，避免与已监听 127.0.0.1 的服务抢同一端口。"""
    forced = os.getenv("BCC_PORT")
    if forced:
        return int(forced)
    for port in range(start, start + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("0.0.0.0", port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"{start}-{start + tries} 端口都被占用，请关闭占用程序后重试")


def setup_logging(data_path: Path) -> None:
    """窗口模式下无控制台，日志写入文件便于排障。"""
    log_file = data_path / "desktop.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(log_file, encoding="utf-8")],
    )


class NativeApi:
    """暴露给前端 JS 的原生能力（window.pywebview.api.xxx）。

    pywebview 默认拦截网页下载，因此导出走原生"另存为"对话框。
    """

    def __init__(self) -> None:
        self._win = None
        self._ball = None
        self._tray = None             # TrayIcon，启动后挂上
        self._in_tray = False         # 主窗口是否已收进托盘
        self._menu_watch = False
        self._panel_op = None          # 进行中的面板拖动/缩放
        self._panel_dragging = False

    def attach(self, win) -> None:
        self._win = win

    def attach_ball(self, ball) -> None:
        self._ball = ball

    def attach_tray(self, tray) -> None:
        self._tray = tray

    @property
    def tray_ready(self) -> bool:
        return bool(self._tray and self._tray.visible)

    # ---------------- 悬浮球：拖拽 / 吸附 ----------------

    def get_ball_pos(self) -> dict:
        """当前球位置（逻辑像素），供前端拖拽时计算偏移基准。"""
        hwnd = find_window(BALL_TITLE)
        if not hwnd:
            return {"x": 0, "y": 0}
        r = window_rect_ui(hwnd)
        return {"x": int(r.left), "y": int(r.top)}

    def move_ball(self, x: float, y: float) -> bool:
        """拖拽过程中移动球（逻辑像素，由前端按屏幕坐标差值计算）。"""
        if not self._ball:
            return False
        try:
            self._ball.move(int(x), int(y))
            return True
        except Exception:  # noqa: BLE001
            return False

    def end_drag(self) -> dict:
        """拖拽结束：兜底拉回工作区 + 贴边吸附 + 记住位置。"""
        hwnd = find_window(BALL_TITLE)
        if not hwnd:
            return {"snapped": False}
        r = window_rect_ui(hwnd)
        work = work_area_ui(hwnd)
        w, h = r.right - r.left, r.bottom - r.top
        x, y = r.left, r.top
        # 兜底：允许拖出屏幕一半，但不能完全消失
        x = max(work.left - w // 2, min(x, work.right - w // 2))
        y = max(work.top, min(y, work.bottom - h))
        if (x, y) != (r.left, r.top):
            try:
                self._ball.move(int(x), int(y))
                time.sleep(0.06)
            except Exception:  # noqa: BLE001
                pass
        return self._snap_ball()

    def _remember_ball(self, rect: _RECT) -> None:
        if rect.right > rect.left:
            DESKTOP_CFG["ballX"] = int(rect.left)
            DESKTOP_CFG["ballY"] = int(rect.top)
            save_desktop_config()

    def _snap_ball(self) -> dict:
        """贴边吸附：拖到距边缘阈值内自动贴齐工作区边界。"""
        hwnd = find_window(BALL_TITLE)
        if not hwnd:
            return {"snapped": False}
        r = window_rect_ui(hwnd)
        work = work_area_ui(hwnd)
        w, h = r.right - r.left, r.bottom - r.top
        x, y = r.left, r.top
        snapped = False
        if x - work.left <= SNAP_THRESHOLD:
            x, snapped = work.left, True
        elif work.right - (x + w) <= SNAP_THRESHOLD:
            x, snapped = work.right - w, True
        if y - work.top <= SNAP_THRESHOLD:
            y, snapped = work.top, True
        elif work.bottom - (y + h) <= SNAP_THRESHOLD:
            y, snapped = work.bottom - h, True
        if snapped:
            try:
                self._ball.move(int(x), int(y))
            except Exception:  # noqa: BLE001
                log.exception("吸附悬浮球失败")
        self._remember_ball(window_rect_ui(hwnd) if snapped else r)
        return {"snapped": snapped, "x": int(x), "y": int(y)}

    def _ball_pos(self) -> tuple:
        """当前球位置（窗口可能正展开成菜单，此时按保存值算）。"""
        hwnd = find_window(BALL_TITLE)
        if hwnd:
            r = window_rect_ui(hwnd)
            if r.right - r.left <= BALL_SIZE + 4 and r.bottom - r.top <= BALL_SIZE + 4:
                return int(r.left), int(r.top)
        return initial_ball_pos()

    # ---------------- 悬浮球：右键菜单 / 面板尺寸 ----------------

    def expand_menu(self, width: int = 0, height: int = 0) -> dict:
        """右键菜单需要比球更大的窗口：向左上扩展，保持球在屏幕上的位置不变。"""
        if not self._ball:
            return {"ok": False}
        hwnd = find_window(BALL_TITLE)
        if not hwnd:
            return {"ok": False}
        r = window_rect_ui(hwnd)
        w = int(width) if width else MENU_SIZE[0]
        h = int(height) if height else MENU_SIZE[1]
        work = work_area_ui(hwnd)
        x = r.left - (w - BALL_SIZE)
        y = r.top - (h - BALL_SIZE)
        x = max(work.left, min(x, work.right - w))
        y = max(work.top, min(y, work.bottom - h))
        try:
            self._ball.resize(w, h)
            self._ball.move(int(x), int(y))
            self._ensure_round_corners()
        except Exception:  # noqa: BLE001
            log.exception("展开悬浮球菜单失败")
            return {"ok": False}
        log.info("右键菜单展开 → %dx%d @ (%d, %d)", w, h, x, y)
        # 窗口即菜单，页面里没有"外部区域"可点，改由全局鼠标轮询实现点外部关闭
        if not self._menu_watch:
            self._menu_watch = True
            threading.Thread(target=self._watch_menu_outside_click, daemon=True).start()
        return {"ok": True, "x": int(x), "y": int(y)}

    def collapse_menu(self) -> dict:
        """从菜单/面板恢复到圆球。"""
        self._menu_watch = False
        if not self._ball:
            return {"ok": False}
        try:
            self._ball.resize(BALL_SIZE, BALL_SIZE)
            x, y = initial_ball_pos()
            self._ball.move(int(x), int(y))
            self._ensure_round_corners()
        except Exception:  # noqa: BLE001
            log.exception("收起伏悬浮球失败")
            return {"ok": False}
        return {"ok": True}

    # ---------------- 菜单"点击外部关闭" ----------------

    def _watch_menu_outside_click(self) -> None:
        """菜单展开期间轮询全局鼠标：在窗口外按下左键 → 自动收起菜单。

        悬浮球窗口本身就是菜单（尺寸 = 菜单尺寸），页面里不存在"外部区域"，
        只能靠 GetAsyncKeyState 监听窗口外的点击。
        """
        u = _user32()
        VK_LBUTTON = 0x01
        time.sleep(0.35)  # 避开打开菜单的那次点击
        while self._menu_watch:
            try:
                if u.GetAsyncKeyState(VK_LBUTTON) & 0x8000:
                    hwnd = find_window(BALL_TITLE)
                    if not hwnd:
                        return
                    pt = wintypes.POINT()
                    u.GetCursorPos(ctypes.byref(pt))
                    r = window_rect(hwnd)  # 物理像素，与 GetCursorPos 同一坐标系
                    inside = r.left <= pt.x < r.right and r.top <= pt.y < r.bottom
                    if not inside:
                        log.info("在菜单外点击，自动收起悬浮球菜单")
                        self._menu_watch = False
                        self.collapse_menu()
                        self._notify_menu_closed()
                        return
            except Exception:  # noqa: BLE001
                log.exception("菜单外部点击监听异常")
                return
            time.sleep(0.05)

    def _notify_menu_closed(self) -> None:
        """让前端把菜单视图收起来，否则球仍是隐藏状态、窗口只剩一块底色。"""
        if not self._ball:
            return
        try:
            self._ball.evaluate_js("window.__closeBallMenu && window.__closeBallMenu()")
        except Exception:  # noqa: BLE001
            log.exception("通知前端收起菜单失败")

    def toggle_mini(self, expanded: bool) -> bool:
        """快速对话：把悬浮球展开成迷你对话面板，收起时回到球。"""
        if not self._ball:
            return False
        self._menu_watch = False  # 面板状态下不再监听"菜单外点击"
        work = work_area_ui(0)
        try:
            log.info("迷你面板 %s", "展开" if expanded else "收起")
            if expanded:
                w, h = panel_size()
                px, py = DESKTOP_CFG.get("panelX"), DESKTOP_CFG.get("panelY")
                if isinstance(px, (int, float)) and isinstance(py, (int, float)):
                    # 沿用上次手动摆放的位置（分辨率变化导致越界时夹回工作区）
                    x, y = int(px), int(py)
                    x = max(work.left, min(x, max(work.left, work.right - w)))
                    y = max(work.top, min(y, max(work.top, work.bottom - h)))
                else:
                    bx, by = self._ball_pos()
                    # 面板向球的内侧展开（球贴右侧时向左长），并限制在工作区内
                    x = bx + BALL_SIZE - w
                    if x < work.left:
                        x = bx
                    x = max(work.left, min(x, work.right - w))
                    y = by + BALL_SIZE - h
                    if y < work.top:
                        y = by
                    y = max(work.top, min(y, work.bottom - h))
                self._ball.resize(w, h)
                self._ball.move(int(x), int(y))
                self._ensure_round_corners()
            else:
                self._ball.resize(BALL_SIZE, BALL_SIZE)
                x, y = initial_ball_pos()
                self._ball.move(int(x), int(y))
                self._ensure_round_corners()
        except Exception:  # noqa: BLE001
            log.exception("调整悬浮窗尺寸失败")
            return False
        return True

    # ---------------- 快速面板：拖动 / 自由缩放 ----------------

    def get_panel_rect(self) -> dict:
        """当前快速面板几何（逻辑像素），供前端计算拖动 / 缩放基准。"""
        hwnd = find_window(BALL_TITLE)
        if not hwnd:
            w, h = panel_size()
            return {"x": 0, "y": 0, "w": w, "h": h}
        r = window_rect_ui(hwnd)
        return {
            "x": int(r.left), "y": int(r.top),
            "w": int(r.right - r.left), "h": int(r.bottom - r.top),
        }

    def set_panel_geometry(self, x: float = 0, y: float = 0, w: float = 0, h: float = 0,
                           persist: bool = False) -> dict:
        """拖动 / 缩放面板：统一按逻辑像素设置位置与尺寸，并保证整块留在工作区内。

        persist=True 时把结果写进 desktop.json，下次展开沿用。
        """
        if not self._ball:
            return {"ok": False}
        hwnd = find_window(BALL_TITLE)
        if not hwnd:
            return {"ok": False}
        work = work_area_ui(hwnd)
        max_w = max(PANEL_MIN[0], work.right - work.left)
        max_h = max(PANEL_MIN[1], work.bottom - work.top)
        try:
            w = max(PANEL_MIN[0], min(int(w), max_w))
            h = max(PANEL_MIN[1], min(int(h), max_h))
            x = max(work.left, min(int(x), max(work.left, work.right - w)))
            y = max(work.top, min(int(y), max(work.top, work.bottom - h)))
            cur = window_rect_ui(hwnd)
            cur_w, cur_h = cur.right - cur.left, cur.bottom - cur.top
            if cur_w != w or cur_h != h:
                self._ball.resize(w, h)
            if int(cur.left) != x or int(cur.top) != y:
                self._ball.move(x, y)
        except Exception:  # noqa: BLE001
            log.exception("调整快速面板几何失败")
            return {"ok": False}
        if persist:
            DESKTOP_CFG["panelX"] = x
            DESKTOP_CFG["panelY"] = y
            DESKTOP_CFG["panelW"] = w
            DESKTOP_CFG["panelH"] = h
            save_desktop_config()
            log.info("快速面板几何已记住：%dx%d @ (%d, %d)", w, h, x, y)
        return {"ok": True, "x": x, "y": y, "w": w, "h": h}

    def begin_panel_drag(self, mode: str = "move", axis: str = "se") -> dict:
        """开始面板拖动 / 缩放（由后端线程跟随鼠标）。

        为什么不用前端的 pointermove：把面板往光标外侧拉大时，光标会跑到窗口之外，
        WebView 收不到 mousemove，缩放立刻断掉。后端轮询 GetCursorPos 更可靠，
        和「点菜单外部关闭」用的是同一套思路。

        mode: move（整块拖动）/ resize（缩放）
        axis: n / s / e / w / ne / nw / se / sw —— 对应按下的是哪条边或哪个角
        """
        if not self._ball:
            return {"ok": False}
        hwnd = find_window(BALL_TITLE)
        if not hwnd:
            return {"ok": False}
        if self._panel_op:
            return {"ok": False, "reason": "busy"}
        r = window_rect_ui(hwnd)
        work = work_area_ui(hwnd)
        pt = wintypes.POINT()
        _user32().GetCursorPos(ctypes.byref(pt))   # 物理像素
        self._panel_op = {
            "mode": "resize" if mode == "resize" else "move",
            "axis": axis if axis in PANEL_AXES else "se",
            "start": {"x": int(r.left), "y": int(r.top),
                      "w": int(r.right - r.left), "h": int(r.bottom - r.top)},
            "work": (int(work.left), int(work.top), int(work.right), int(work.bottom)),
            "scale": ui_scale(hwnd) or 1.0,
            "cx": int(pt.x), "cy": int(pt.y),
        }
        threading.Thread(target=self._run_panel_drag, daemon=True).start()
        return {"ok": True, **self._panel_op["start"]}

    def _run_panel_drag(self) -> None:
        """跟随鼠标调整窗口位置 / 尺寸，直到左键松开。"""
        u = _user32()
        VK_LBUTTON = 0x01
        op = self._panel_op
        if not op:
            return
        self._panel_dragging = True
        st, scale = op["start"], op["scale"] or 1.0
        moved = False
        try:
            while self._panel_op is not None:
                if not (u.GetAsyncKeyState(VK_LBUTTON) & 0x8000):
                    break
                pt = wintypes.POINT()
                u.GetCursorPos(ctypes.byref(pt))
                dx = int((pt.x - op["cx"]) / scale)
                dy = int((pt.y - op["cy"]) / scale)
                if not moved and abs(dx) < 2 and abs(dy) < 2:
                    time.sleep(0.016)
                    continue
                moved = True
                if op["mode"] == "move":
                    x, y, w, h = st["x"] + dx, st["y"] + dy, st["w"], st["h"]
                else:
                    x, y, w, h = resized_rect(op["axis"], st, dx, dy, op["work"])
                res = self.set_panel_geometry(x, y, w, h, False)
                if res.get("ok"):
                    op["geo"] = res      # 以最后一次生效的几何为准
                time.sleep(0.016)
        except Exception:  # noqa: BLE001
            log.exception("面板拖动/缩放异常")
        finally:
            self._panel_op = None
            self._panel_dragging = False
            geo = op.get("geo")
            if moved and geo:
                # 记住最后一次生效的几何（不回读窗口：resize 生效有延迟，回读会偏几像素）
                DESKTOP_CFG["panelX"] = int(geo["x"])
                DESKTOP_CFG["panelY"] = int(geo["y"])
                DESKTOP_CFG["panelW"] = int(geo["w"])
                DESKTOP_CFG["panelH"] = int(geo["h"])
                save_desktop_config()
                log.info("快速面板几何已记住：%dx%d @ (%d, %d)",
                         int(geo["w"]), int(geo["h"]), int(geo["x"]), int(geo["y"]))
            self._notify_panel_drag_end()

    def _notify_panel_drag_end(self) -> None:
        """通知前端收尾（清全局抓手光标）——光标离开窗口后 pointerup 可能收不到。"""
        if not self._ball:
            return
        try:
            self._ball.evaluate_js("window.__panelDragEnd && window.__panelDragEnd()")
        except Exception:  # noqa: BLE001
            log.exception("通知前端面板操作结束失败")

    # ---------------- 主窗口 ----------------

    def _main_visible(self) -> bool:
        hwnd = find_window(MAIN_TITLE)
        if not hwnd:
            return False
        u = _user32()
        return bool(u.IsWindowVisible(hwnd)) and not u.IsIconic(hwnd)

    def _reveal_main(self) -> bool:
        """显示主窗口（从最小化 / 托盘 / 普通隐藏都能还原），并尽量置前。"""
        if not self._win:
            return False
        try:
            self._win.show()
        except Exception:  # noqa: BLE001
            log.exception("显示主窗口失败")
            return False
        hwnd = find_window(MAIN_TITLE)
        if hwnd:
            u = _user32()
            try:
                u.ShowWindow(hwnd, 9)  # SW_RESTORE
            except Exception:  # noqa: BLE001
                log.exception("还原主窗口失败")
            try:
                u.SetForegroundWindow(hwnd)
            except Exception:  # noqa: BLE001
                pass  # 系统可能拒绝抢前台，静默即可
        else:
            try:
                self._win.restore()
            except Exception:  # noqa: BLE001
                pass
        self._in_tray = False
        return True

    def activate_main(self) -> bool:
        """托盘图标单击 / 菜单「打开主界面」。"""
        ok = self._reveal_main()
        if ok:
            log.info("从托盘唤起主窗口")
        return ok

    def minimize_to_tray(self) -> bool:
        """主窗口被最小化时收进托盘：隐藏窗口，任务栏不留空壳。"""
        if not self._win or self._in_tray:
            return False
        try:
            self._win.hide()
        except Exception:  # noqa: BLE001
            log.exception("最小化到托盘失败")
            return False
        self._in_tray = True
        log.info("主窗口已最小化到托盘")
        return True

    def toggle_main(self) -> dict:
        """点击悬浮球：唤起 / 收起主窗口。"""
        if not self._win:
            return {"visible": False}
        try:
            if self._main_visible():
                self._win.hide()
                visible = False
            else:
                visible = self._reveal_main()
        except Exception:  # noqa: BLE001
            log.exception("切换主窗口失败")
            return {"visible": self._main_visible()}
        log.info("主窗口 %s", "唤起" if visible else "收起")
        return {"visible": visible}

    def show_main(self) -> bool:
        return self.open_main("")

    def open_main(self, tree_id: str = "") -> bool:
        """显示主窗口，并可选地切换到指定画布。"""
        if not self._win:
            return False
        if not self._reveal_main():
            return False
        if tree_id:
            try:
                self._win.evaluate_js(
                    f"window.__openTreeFromMini && window.__openTreeFromMini({json.dumps(tree_id)})")
            except Exception:  # noqa: BLE001
                log.exception("主窗口切换画布失败")
        return True

    # ---------------- 程序控制 ----------------

    def quit_app(self) -> bool:
        """退出整个程序（后端一并停止）。"""
        log.info("用户选择退出程序")
        try:
            if self._tray:
                self._tray.stop()
        except Exception:  # noqa: BLE001
            log.exception("移除托盘图标失败")
        threading.Timer(0.3, os._exit, [0]).start()
        return True

    # ---------------- 桌面配置 ----------------

    def get_desktop_config(self) -> dict:
        return {
            "available": True,
            "showBall": bool(DESKTOP_CFG.get("showBall", True)),
            "autoStart": bool(DESKTOP_CFG.get("autoStart", False)),
            "ballVisible": self._ball_visible(),
            "trayVisible": self.tray_ready,
            "canAutoStart": bool(getattr(sys, "frozen", False)),
        }

    def _ball_visible(self) -> bool:
        hwnd = find_window(BALL_TITLE)
        if not hwnd:
            return False
        u = _user32()
        return bool(u.IsWindowVisible(hwnd)) and not u.IsIconic(hwnd)

    # ---------------- 窗口形状（Win11 原生圆角，去掉不透明底色方块） ----------------
    # pywebview 的 transparent 在 Windows/WebView2 下不生效，窗口四角会露出
    # 不透明底色；SetWindowRgn / LWA_COLORKEY 在 WebView2 的 DWM 合成下同样
    # 失效。最终方案：App 图标式的圆角方形悬浮球 + DWMWA_WINDOW_CORNER_
    # PREFERENCE 系统级圆角（Win11 对所有应用通用，WebView2 内容也会被裁），
    # 窗口底色与球/面板同色，肉眼无缝。

    def _ensure_round_corners(self) -> None:
        """给悬浮球窗口应用 Win11 系统圆角（幂等，resize/move 不影响）。"""
        hwnd = find_window(BALL_TITLE)
        if not hwnd:
            return
        try:
            dwm = ctypes.windll.dwmapi
            DWMWA_WINDOW_CORNER_PREFERENCE = 33
            DWMWCP_ROUND = 2  # 系统默认圆角（Win10 不支持则静默保持直角）
            pref = ctypes.c_int(DWMWCP_ROUND)
            dwm.DwmSetWindowAttribute(
                ctypes.wintypes.HWND(hwnd), DWMWA_WINDOW_CORNER_PREFERENCE,
                ctypes.byref(pref), ctypes.sizeof(pref))
        except Exception:  # noqa: BLE001
            log.exception("应用悬浮球窗口圆角失败")

    def set_desktop_config(self, patch: dict = None) -> dict:  # noqa: RUF013
        patch = patch or {}
        if "showBall" in patch:
            self.show_ball(bool(patch["showBall"]))
        if "autoStart" in patch:
            want = bool(patch["autoStart"])
            ok = apply_autostart(want)
            DESKTOP_CFG["autoStart"] = bool(want and ok)
            save_desktop_config()
        return self.get_desktop_config()

    def show_ball(self, visible: bool = True) -> dict:
        """显示 / 隐藏悬浮球，并记住开关状态。

        显示前先恢复成标准球（84x84、回到记住的位置），避免球窗口
        此前停留在右键菜单 / 迷你面板的展开尺寸，show 出来是一块
        残缺窗口、看起来像"开关没反应"。
        """
        DESKTOP_CFG["showBall"] = bool(visible)
        save_desktop_config()
        if self._ball:
            try:
                if visible:
                    self._ball.resize(BALL_SIZE, BALL_SIZE)
                    bx, by = self._ball_pos()
                    self._ball.move(int(bx), int(by))
                    self._ball.show()
                    self._ensure_round_corners()
                else:
                    self._ball.hide()
                log.info("悬浮球已%s", "显示" if visible else "隐藏")
            except Exception:  # noqa: BLE001
                log.exception("切换悬浮球显示失败")
        if self._tray:
            self._tray.refresh()  # 菜单里的「显示悬浮球」勾选状态跟着变
        return self.get_desktop_config()

    def hide_ball(self) -> bool:
        """兼容旧调用：隐藏悬浮球。"""
        self.show_ball(False)
        return True

    def reset_ball_pos(self) -> dict:
        """把悬浮球移回默认的右下角位置。"""
        DESKTOP_CFG["ballX"] = None
        DESKTOP_CFG["ballY"] = None
        save_desktop_config()
        if self._ball:
            try:
                if not self._ball_visible():
                    self._ball.show()
                self._ball.resize(BALL_SIZE, BALL_SIZE)
                x, y = initial_ball_pos()
                self._ball.move(int(x), int(y))
                self._ensure_round_corners()
            except Exception:  # noqa: BLE001
                log.exception("重置悬浮球位置失败")
                return {"ok": False}
        return {"ok": True}

    # ---------------- 文件导出 ----------------

    def save_text(self, filename: str, content: str) -> str:
        """原生保存对话框：返回保存路径；用户取消返回空字符串。"""
        import webview

        if not self._win:
            return ""
        result = self._win.create_file_dialog(
            webview.SAVE_DIALOG,
            directory=str(data_dir()),
            save_filename=filename,
        )
        if not result:
            return ""
        path = result if isinstance(result, str) else result[0]
        Path(path).write_text(content, encoding="utf-8")
        log.info("导出保存：%s（%d 字符）", path, len(content))
        return path


class TrayIcon:
    """Windows 通知区域（右下角托盘）图标。

    程序一启动就常驻：主窗口最小化时收进这里，点图标或菜单「打开主界面」
    唤回；右键菜单还能切换悬浮球显示与退出软件。
    """

    def __init__(self, api: "NativeApi") -> None:
        self._api = api
        self._icon = None
        self._thread = None

    # ---- 状态 ----
    @property
    def visible(self) -> bool:
        try:
            return bool(self._icon and self._icon.visible)
        except Exception:  # noqa: BLE001
            return False

    def _icon_image(self):
        """优先用应用图标，读不到就画一个纯色圆角块兜底。"""
        from PIL import Image

        for name in ("icon.png", "icon-256.png", "icon.ico"):
            path = app_root() / "assets" / name
            try:
                if path.exists():
                    img = Image.open(path)
                    img.load()
                    return img.convert("RGBA")
            except Exception:  # noqa: BLE001
                log.exception("加载托盘图标失败：%s", path)
        log.warning("未找到托盘图标资源，使用兜底色块")
        return Image.new("RGBA", (64, 64), (15, 180, 126, 255))

    # ---- 生命周期 ----
    def start(self) -> bool:
        if self._icon is not None:
            return True
        try:
            import pystray
        except Exception:  # noqa: BLE001
            log.warning("未安装 pystray，托盘功能不可用")
            return False
        try:
            image = self._icon_image()
            menu = pystray.Menu(
                pystray.MenuItem("打开主界面", self._on_open, default=True),
                pystray.MenuItem(
                    "显示悬浮球",
                    self._on_toggle_ball,
                    checked=lambda _item: bool(DESKTOP_CFG.get("showBall", True)),
                ),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("退出软件", self._on_quit),
            )
            self._icon = pystray.Icon("branch-chat-canvas", image, MAIN_TITLE, menu)
        except Exception:  # noqa: BLE001
            log.exception("创建托盘图标失败")
            return False

        self._thread = threading.Thread(target=self._run, daemon=True, name="tray-icon")
        self._thread.start()
        log.info("托盘图标已启动")
        return True

    def _run(self) -> None:
        try:
            self._icon.run()
        except Exception:  # noqa: BLE001
            log.exception("托盘图标消息循环异常退出")

    def stop(self) -> None:
        try:
            if self._icon:
                self._icon.stop()
                log.info("托盘图标已移除")
        except Exception:  # noqa: BLE001
            log.exception("移除托盘图标失败")

    def refresh(self) -> None:
        """菜单勾选状态变化后刷新（pystray 的 checked 是惰性回调，需显式刷新）。"""
        try:
            if self._icon:
                self._icon.update_menu()
        except Exception:  # noqa: BLE001
            log.exception("刷新托盘菜单失败")

    # ---- 菜单动作（回调在托盘线程，动作尽量轻） ----
    def _on_open(self, _icon=None, _item=None) -> None:
        threading.Thread(target=self._api.activate_main, daemon=True).start()

    def _on_toggle_ball(self, _icon=None, _item=None) -> None:
        want = not bool(DESKTOP_CFG.get("showBall", True))
        threading.Thread(target=self._api.show_ball, args=(want,), daemon=True).start()

    def _on_quit(self, _icon=None, _item=None) -> None:
        threading.Thread(target=self._api.quit_app, daemon=True).start()


def watch_main_window(api: "NativeApi", grace: float = 15.0) -> None:
    """盯着主窗口：被最小化就收进托盘，被真正关闭就整体退出。

    1) 关闭（×）：pywebview 的 GUI 循环要等**所有**窗口销毁才返回，主窗口
       关了而悬浮球还在，进程会一直挂着、球留在桌面——这里主动收尾。
    2) 最小化：窗口不可见地收进托盘，任务栏不留空壳；点托盘图标唤回。
    判断都基于窗口**句柄是否存在**：`hide()` 收起（球菜单点球）时句柄仍在，
    `IsIconic` 为 False，不会被误当成关闭或最小化。
    """
    started = time.time()
    seen_main = False
    while True:
        time.sleep(0.6)
        hwnd = find_window(MAIN_TITLE)
        if hwnd:
            seen_main = True
            if _user32().IsIconic(hwnd):
                api.minimize_to_tray()
            elif api._in_tray and _user32().IsWindowVisible(hwnd):
                api._in_tray = False  # 用户自己把窗口还原了，状态复位
            continue
        if not seen_main and time.time() - started < grace:
            continue  # 启动初期窗口还没建出来，先等一等
        log.info("检测到主窗口已关闭，联动退出悬浮球与后端")
        try:
            api._tray and api._tray.stop()
        except Exception:  # noqa: BLE001
            log.exception("移除托盘图标失败")
        try:
            if api._ball:
                api._ball.destroy()
        except Exception:  # noqa: BLE001
            log.exception("销毁悬浮球窗口失败")
        threading.Timer(0.4, os._exit, [0]).start()
        return


def main() -> None:
    root = app_root()
    dpath = data_dir()
    setup_logging(dpath)
    load_desktop_config()

    start_minimized = "--minimized" in sys.argv

    # 在导入后端模块前固定环境，storage/llm_client/main 均读取这些变量
    os.environ["BCC_DATA_DIR"] = str(dpath)
    os.environ.setdefault("BCC_STATIC_DIR", str(root / "frontend" / "public"))

    try:
        import uvicorn
        import webview

        from main import app  # noqa: E402  依赖上面的环境变量
    except Exception:
        log.exception("导入依赖失败")
        raise

    port = find_free_port()
    url = f"http://127.0.0.1:{port}"

    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning",
                       log_config=None, access_log=False)
    )
    threading.Thread(target=server.run, daemon=True, name="uvicorn").start()

    # 等服务就绪再开窗口，避免首屏空白
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                break
        except OSError:
            time.sleep(0.1)
    else:
        log.error("后端服务启动超时")
        return
    log.info("服务就绪 %s，数据目录 %s", url, dpath)

    api = NativeApi()

    # 窗口/任务栏图标来自 exe 自身资源（--icon 打包），此处无需再设置
    win = webview.create_window(
        MAIN_TITLE,
        url,
        width=1440,
        height=900,
        min_size=(960, 620),
        background_color="#F7F8FA",
        hidden=start_minimized,
        js_api=api,
    )
    api.attach(win)

    # 悬浮球：无边框、置顶，位置取上次保存值（默认右下角）。
    # 注意：不能用 transparent=True（pywebview 该路径在 WebView2 下渲染异常，
    # 四角露出黑色方块）；SetWindowRgn / LWA_COLORKEY 也均被 WebView2 的
    # DWM 合成绕过。最终方案：App 图标式圆角方形球 + Win11 系统圆角
    # （_ensure_round_corners），窗口底色与球同色系，视觉无缝。
    ball_x, ball_y = initial_ball_pos()
    ball = webview.create_window(
        BALL_TITLE,
        f"{url}/?mini=1",
        width=BALL_SIZE,
        height=BALL_SIZE,
        x=ball_x,
        y=ball_y,
        frameless=True,
        on_top=True,
        background_color="#0FB47E",  # 与悬浮球图标边缘主色一致，加载瞬间无缝
        resizable=False,
        easy_drag=False,
        shadow=False,
        min_size=(BALL_SIZE, BALL_SIZE),
        js_api=api,
    )
    api.attach_ball(ball)

    tray = TrayIcon(api)
    api.attach_tray(tray)

    def _after_start() -> None:
        """GUI 起来后再校正悬浮球（创建时窗口尺寸/位置不一定精确）。"""
        log.info("GUI 就绪：悬浮球显示=%s，主窗口最小化启动=%s",
                 DESKTOP_CFG.get("showBall"), start_minimized)
        try:
            # 无边框窗口创建时的初始尺寸会带上系统余量，这里显式校正为 84x84
            ball.resize(BALL_SIZE, BALL_SIZE)
            bx, by = initial_ball_pos()
            ball.move(bx, by)
            log.info("悬浮球尺寸/位置已校正为 %dx%d @ (%d, %d)", BALL_SIZE, BALL_SIZE, bx, by)
        except Exception:  # noqa: BLE001
            log.exception("校正悬浮球失败")
        try:
            api._ensure_round_corners()  # Win11 系统圆角，窗口与球视觉无缝
        except Exception:  # noqa: BLE001
            log.exception("应用悬浮球色键透明失败")
        if not DESKTOP_CFG.get("showBall", True):
            try:
                ball.hide()
            except Exception:  # noqa: BLE001
                log.exception("按配置隐藏悬浮球失败")
        # 托盘常驻：主窗口最小化后收进这里
        try:
            tray.start()
        except Exception:  # noqa: BLE001
            log.exception("启动托盘图标失败")
        # 盯住主窗口：最小化 → 收托盘；关闭 → 连同悬浮球一起退出
        threading.Thread(target=watch_main_window, args=(api,), daemon=True,
                         name="main-window-watch").start()

    # 兜底：允许 WebView2 自带下载 UI（万一有网页式下载场景）
    webview.settings["ALLOW_DOWNLOADS"] = True
    webview.start(_after_start, debug=os.getenv("BCC_DEBUG") == "1")
    # 窗口关闭后退出：先停后端，再结束进程
    log.info("窗口关闭，退出")
    tray.stop()
    server.should_exit = True
    os._exit(0)


if __name__ == "__main__":
    main()
