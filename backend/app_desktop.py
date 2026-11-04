# -*- coding: utf-8 -*-
"""桌面版启动器（独立窗口，不依赖浏览器）。

- 用 pywebview 创建原生窗口（Windows 下使用系统自带的 Edge WebView2 内核）
- 在后台线程启动 FastAPI/uvicorn，窗口指向本机回环地址
- 数据目录：exe 同级 data/（可用 BCC_DATA_DIR 覆盖），便携可迁移
- 环境变量：
    BCC_DATA_DIR   数据目录（默认 exe 同级 data/）
    BCC_PORT       指定端口（默认自动挑选空闲端口）
    BCC_DEBUG      "1" 时打开 DevTools
"""
import logging
import os
import socket
import sys
import threading
import time
from pathlib import Path


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

    def attach(self, win) -> None:
        self._win = win

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
        logging.getLogger("desktop").info("导出保存：%s（%d 字符）", path, len(content))
        return path


def main() -> None:
    root = app_root()
    dpath = data_dir()
    setup_logging(dpath)
    log = logging.getLogger("desktop")

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

    # 窗口/任务栏图标来自 exe 自身资源（--icon 打包），此处无需再设置
    api = NativeApi()
    win = webview.create_window(
        "分支对话画布",
        url,
        width=1440,
        height=900,
        min_size=(960, 620),
        background_color="#F7F8FA",
        js_api=api,
    )
    api.attach(win)
    # 兜底：允许 WebView2 自带下载 UI（万一有网页式下载场景）
    webview.settings["ALLOW_DOWNLOADS"] = True
    webview.start(
        debug=os.getenv("BCC_DEBUG") == "1",
    )
    # 窗口关闭后退出：先停后端，再结束进程
    log.info("窗口关闭，退出")
    server.should_exit = True
    os._exit(0)


if __name__ == "__main__":
    main()
