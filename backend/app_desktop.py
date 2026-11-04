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
BALL_SIZE = 84
PANEL_SIZE = (420, 620)
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

    def attach(self, win) -> None:
        self._win = win

    def attach_ball(self, ball) -> None:
        self._ball = ball

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
        except Exception:  # noqa: BLE001
            log.exception("展开悬浮球菜单失败")
            return {"ok": False}
        log.info("右键菜单展开 → %dx%d @ (%d, %d)", w, h, x, y)
        return {"ok": True, "x": int(x), "y": int(y)}

    def collapse_menu(self) -> dict:
        """从菜单/面板恢复到圆球。"""
        if not self._ball:
            return {"ok": False}
        try:
            self._ball.resize(BALL_SIZE, BALL_SIZE)
            x, y = initial_ball_pos()
            self._ball.move(int(x), int(y))
        except Exception:  # noqa: BLE001
            log.exception("收起伏悬浮球失败")
            return {"ok": False}
        return {"ok": True}

    def toggle_mini(self, expanded: bool) -> bool:
        """快速对话：把悬浮球展开成迷你对话面板，收起时回到球。"""
        if not self._ball:
            return False
        work = work_area_ui(0)
        try:
            log.info("迷你面板 %s", "展开" if expanded else "收起")
            if expanded:
                w, h = PANEL_SIZE
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
            else:
                self._ball.resize(BALL_SIZE, BALL_SIZE)
                x, y = initial_ball_pos()
                self._ball.move(int(x), int(y))
        except Exception:  # noqa: BLE001
            log.exception("调整悬浮窗尺寸失败")
            return False
        return True

    # ---------------- 主窗口 ----------------

    def _main_visible(self) -> bool:
        hwnd = find_window(MAIN_TITLE)
        if not hwnd:
            return False
        u = _user32()
        return bool(u.IsWindowVisible(hwnd)) and not u.IsIconic(hwnd)

    def toggle_main(self) -> dict:
        """点击悬浮球：唤起 / 收起主窗口。"""
        if not self._win:
            return {"visible": False}
        try:
            if self._main_visible():
                self._win.hide()
                visible = False
            else:
                self._win.show()
                try:
                    self._win.restore()
                except Exception:  # noqa: BLE001
                    pass  # 未最小化时 restore 会抛错，可忽略
                visible = True
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
        try:
            self._win.show()
            try:
                self._win.restore()
            except Exception:  # noqa: BLE001
                pass
        except Exception:  # noqa: BLE001
            log.exception("显示主窗口失败")
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
        log.info("用户从悬浮球选择退出程序")
        threading.Timer(0.3, os._exit, [0]).start()
        return True

    # ---------------- 桌面配置 ----------------

    def get_desktop_config(self) -> dict:
        return {
            "available": True,
            "showBall": bool(DESKTOP_CFG.get("showBall", True)),
            "autoStart": bool(DESKTOP_CFG.get("autoStart", False)),
            "ballVisible": self._ball_visible(),
            "canAutoStart": bool(getattr(sys, "frozen", False)),
        }

    def _ball_visible(self) -> bool:
        hwnd = find_window(BALL_TITLE)
        if not hwnd:
            return False
        u = _user32()
        return bool(u.IsWindowVisible(hwnd)) and not u.IsIconic(hwnd)

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
                else:
                    self._ball.hide()
                log.info("悬浮球已%s", "显示" if visible else "隐藏")
            except Exception:  # noqa: BLE001
                log.exception("切换悬浮球显示失败")
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

    # 悬浮球：无边框、置顶、透明，位置取上次保存值（默认右下角）
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
        transparent=True,
        resizable=False,
        easy_drag=False,
        shadow=False,
        min_size=(BALL_SIZE, BALL_SIZE),
        js_api=api,
    )
    api.attach_ball(ball)

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
        if not DESKTOP_CFG.get("showBall", True):
            try:
                ball.hide()
            except Exception:  # noqa: BLE001
                log.exception("按配置隐藏悬浮球失败")

    # 兜底：允许 WebView2 自带下载 UI（万一有网页式下载场景）
    webview.settings["ALLOW_DOWNLOADS"] = True
    webview.start(_after_start, debug=os.getenv("BCC_DEBUG") == "1")
    # 窗口关闭后退出：先停后端，再结束进程
    log.info("窗口关闭，退出")
    server.should_exit = True
    os._exit(0)


if __name__ == "__main__":
    main()
