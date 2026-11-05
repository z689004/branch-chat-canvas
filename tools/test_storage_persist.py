"""WebView2 localStorage 跨启动持久化验证。

pywebview 默认 private_mode=True，WebView2 跑 InPrivate 模式，窗口关闭时
clear_user_data() 会 rmtree 整个用户数据目录 → localStorage 全丢。
本脚本用两种配置各跑一次「写 → 关窗 → 再启动读」，证明修复方向正确。

用法（由外层脚本连续调用，模拟两次启动）：
  python test_storage_persist.py --phase write --mode private
  python test_storage_persist.py --phase read  --mode private     # 期望 None
  python test_storage_persist.py --phase write --mode persist --profile <dir>
  python test_storage_persist.py --phase read  --mode persist --profile <dir>  # 期望保留
"""
import argparse
import http.server
import os
import socketserver
import sys
import tempfile
import threading
import time

KEY = "bcc:probe"


def serve_static(root: str, port: int) -> int:
    """起一个只读静态服务：localStorage 需要真实 http origin（about:blank 是 opaque）。

    端口必须固定：localStorage 按 origin（含端口）隔离，两次启动端口不同就必然读不到，
    那是测试自身的假阴性，与持久化配置无关。
    """
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=root, **kw)

        def log_message(self, *a):  # 静音
            pass

    httpd = socketserver.TCPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True, name="http").start()
    return httpd.server_address[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=["write", "read"], required=True)
    ap.add_argument("--mode", choices=["private", "persist"], required=True)
    ap.add_argument("--profile", default="")
    ap.add_argument("--tag", default="v1")
    ap.add_argument("--port", type=int, default=47913, help="固定端口：origin 一变 localStorage 就隔离了")
    args = ap.parse_args()

    import webview

    web_root = tempfile.mkdtemp(prefix="bcc_probe_")
    with open(os.path.join(web_root, "index.html"), "w", encoding="utf-8") as f:
        f.write("<!doctype html><html><body>probe</body></html>")
    port = serve_static(web_root, args.port)

    win = webview.create_window("probe", f"http://127.0.0.1:{port}/",
                               width=360, height=260, hidden=False)

    result = {"value": None, "error": None}

    def worker() -> None:
        try:
            # 等首屏加载完再操作存储
            try:
                win.events.loaded.wait(20)
            except Exception:  # noqa: BLE001
                pass
            time.sleep(0.8)
            if args.phase == "write":
                win.evaluate_js(f"localStorage.setItem({KEY!r}, 'kept-{args.tag}')")
                time.sleep(1.2)  # 等 LevelDB 落盘，别刚写完就杀窗口
                result["value"] = win.evaluate_js(f"localStorage.getItem({KEY!r})")
            else:
                result["value"] = win.evaluate_js(f"localStorage.getItem({KEY!r})")
        except Exception as exc:  # noqa: BLE001
            result["error"] = repr(exc)
        finally:
            time.sleep(0.2)
            try:
                win.destroy()
            except Exception:  # noqa: BLE001
                pass

    kwargs = {"debug": False}
    if args.mode == "persist":
        if not args.profile:
            print("--mode persist 需要 --profile", file=sys.stderr)
            return 2
        os.makedirs(args.profile, exist_ok=True)
        kwargs["private_mode"] = False
        kwargs["storage_path"] = args.profile

    webview.start(worker, **kwargs)

    if result["error"]:
        print(f"ERROR {result['error']}")
        return 1
    print(f"RESULT phase={args.phase} mode={args.mode} value={result['value']!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
