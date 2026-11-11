"""Web 服务简单入口：python app.py（监听 host/port 读 configs/server.json，缺文件报错退出）。

打包形态（PyInstaller onedir，M14）：双击可执行文件启动后自动打开默认浏览器——
仅 ``sys.frozen`` 时启用；源码运行行为与 M10 一致（不开浏览器，手动访问）。
"""

from __future__ import annotations

import socket
import sys
import threading
import time
import webbrowser

import uvicorn

from typhoon_track.api.server_config import ServerConfig

_BROWSER_OPEN_TIMEOUT_S = 15.0
_POLL_INTERVAL_S = 0.2


def _display_host(host: str) -> str:
    """通配监听地址映射为本机回环（浏览器地址与端口就绪探测共用）。"""
    return "127.0.0.1" if host in ("0.0.0.0", "::") else host


def _browser_url(host: str, port: int) -> str:
    """浏览器访问地址：非通配 host 原样保留（如局域网地址）。"""
    return f"http://{_display_host(host)}:{port}/"


def _wait_port_open(host: str, port: int, timeout_s: float) -> bool:
    """轮询 TCP 端口直至可连接，超时返回 False（仅标准库 socket；httpx 属开发依赖不进运行时包）。"""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            time.sleep(_POLL_INTERVAL_S)
    return False


def _open_browser_when_ready(host: str, port: int, timeout_s: float = _BROWSER_OPEN_TIMEOUT_S) -> None:
    """后台线程体：等服务端口就绪后打开默认浏览器；无法打开时打印地址兜底，不抛出。"""
    url = _browser_url(host, port)
    if not _wait_port_open(_display_host(host), port, timeout_s):
        print(f"等待服务就绪超时（{timeout_s:.0f} 秒），请手动访问 {url}")
        return
    try:
        opened = webbrowser.open(url)
    except Exception:
        opened = False
    if not opened:
        print(f"未能自动打开浏览器，请手动访问 {url}")


def main() -> None:
    config = ServerConfig.load()
    if getattr(sys, "frozen", False):
        threading.Thread(
            target=_open_browser_when_ready, args=(config.host, config.port), daemon=True
        ).start()
    uvicorn.run("typhoon_track.api.app:app", host=config.host, port=config.port)


if __name__ == "__main__":
    main()
