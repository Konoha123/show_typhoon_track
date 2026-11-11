"""M14a：冻结感知路径与打包入口浏览器辅助函数。

覆盖 api 层 default_project_root（源码/frozen 两分支与模块常量一致性）
与根 app.py 的 _display_host/_browser_url/_wait_port_open/_open_browser_when_ready
（通配 host 映射、端口就绪探测成败两路、开浏览器失败兜底文案）。
"""

from __future__ import annotations

import importlib.util
import socket
import sys
import types
from collections.abc import Iterator
from pathlib import Path

import pytest

from typhoon_track.api.app import PROJECT_ROOT, default_project_root

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def entry() -> types.ModuleType:
    """按文件路径加载根入口 app.py（模块名隔离，避免与 conftest/包名冲突）。"""
    spec = importlib.util.spec_from_file_location("typhoon_entry_app", ROOT / "app.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def listening_port() -> Iterator[int]:
    """在回环地址起一个临时 TCP listener，返回其端口；用例结束即关闭。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        yield server.getsockname()[1]


@pytest.fixture
def closed_port() -> int:
    """绑定后立即关闭的端口：无 listener、连接必被拒（无 TIME_WAIT 监听）。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    return port


def test_project_root_source_branch_equals_repo_root() -> None:
    assert default_project_root() == ROOT


def test_project_root_frozen_branch_uses_executable_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    exe = tmp_path / "dist" / "typhoon-track" / "typhoon-track"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    assert default_project_root() == exe.parent


def test_module_constant_project_root_unchanged_in_source_run() -> None:
    """导入期非 frozen：PROJECT_ROOT 常量仍为仓库根（server_config 等既有消费方不受影响）。"""
    assert PROJECT_ROOT == ROOT


def test_display_host_maps_wildcards_to_loopback(entry: types.ModuleType) -> None:
    assert entry._display_host("0.0.0.0") == "127.0.0.1"
    assert entry._display_host("::") == "127.0.0.1"
    assert entry._display_host("127.0.0.1") == "127.0.0.1"
    assert entry._display_host("192.168.1.5") == "192.168.1.5"


def test_browser_url_format(entry: types.ModuleType) -> None:
    assert entry._browser_url("127.0.0.1", 9801) == "http://127.0.0.1:9801/"
    assert entry._browser_url("0.0.0.0", 8000) == "http://127.0.0.1:8000/"


def test_wait_port_open_immediate_success(entry: types.ModuleType, listening_port: int) -> None:
    assert entry._wait_port_open("127.0.0.1", listening_port, timeout_s=2.0) is True


def test_wait_port_open_times_out(entry: types.ModuleType, closed_port: int) -> None:
    assert entry._wait_port_open("127.0.0.1", closed_port, timeout_s=0.3) is False


def test_open_browser_when_ready_opens_url(
    entry: types.ModuleType,
    listening_port: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_open(url: str) -> bool:
        calls.append(url)
        return True

    monkeypatch.setattr(entry.webbrowser, "open", fake_open)
    entry._open_browser_when_ready("0.0.0.0", listening_port, timeout_s=2.0)
    assert calls == [f"http://127.0.0.1:{listening_port}/"]


def test_open_browser_when_ready_prints_fallback_when_open_fails(
    entry: types.ModuleType,
    listening_port: int,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fake_open(url: str) -> bool:
        return False

    monkeypatch.setattr(entry.webbrowser, "open", fake_open)
    entry._open_browser_when_ready("127.0.0.1", listening_port, timeout_s=2.0)
    assert "请手动访问" in capsys.readouterr().out


def test_open_browser_when_ready_timeout_prints_hint(
    entry: types.ModuleType, closed_port: int, capsys: pytest.CaptureFixture[str]
) -> None:
    entry._open_browser_when_ready("127.0.0.1", closed_port, timeout_s=0.3)
    assert "超时" in capsys.readouterr().out
