"""UI E2E（Playwright 无头浏览器）：地图工作台核心交互回归。

覆盖成员线持久选中状态机：点线选中、鼠标离开保持、点空白取消、点其它线切换。
依赖：requirements-dev 中的 pytest-playwright；首次使用需
`python -m playwright install chromium`。未安装 Playwright 的环境整文件自动跳过。
"""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from uvicorn import Config, Server

from typhoon_track.api.app import create_app
from typhoon_track.service.datasets import DatasetStore

pytest.importorskip("playwright", reason="未安装 Playwright，跳过 UI E2E")

ROOT = Path(__file__).resolve().parents[1]
MEMBERS = ROOT / "demo_src" / "sample_synthetic_ensemble.csv"


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@pytest.fixture
def live_url(tmp_path: Path) -> Iterator[str]:
    store = DatasetStore(tmp_path)
    store.create(filename="ens.csv", content=MEMBERS.read_bytes(), kind="forecast")
    config = Config(create_app(store), host="127.0.0.1", port=_free_port(), log_level="warning")
    server = Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    else:
        pytest.fail("uvicorn 测试服务启动超时")
    yield f"http://{config.host}:{config.port}"
    server.should_exit = True
    thread.join(timeout=5)


def _open_workbench(page, live_url: str) -> None:
    page.goto(live_url)
    page.wait_for_selector("#storm option", state="attached")  # 下拉项填充即数据就绪
    page.wait_for_selector('path[data-member="01"]')
    page.wait_for_selector('path[data-member="02"]')


def _widen_line_for_click(page, member: str) -> None:
    """加宽线宽提高 SVG stroke 命中区（等价真实点击，避免 1.4px 命不中）。"""
    page.eval_on_selector(
        f'path[data-member="{member}"]',
        "el => el.setAttribute('stroke-width', '20')",
    )


def test_member_line_selected_and_kept_after_mouse_leaves(page, live_url: str) -> None:
    _open_workbench(page, live_url)
    _widen_line_for_click(page, "01")
    page.click('path[data-member="01"]')
    page.wait_for_selector('path[data-highlight="01"]')
    page.mouse.move(30, 600)  # 移出地图（左侧面板），模拟鼠标离开
    page.wait_for_timeout(250)
    assert page.locator('path[data-highlight="01"]').count() == 1  # 光晕保持（持久选中）


def test_member_line_deselected_by_blank_map_click(page, live_url: str) -> None:
    _open_workbench(page, live_url)
    _widen_line_for_click(page, "01")
    page.click('path[data-member="01"]')
    page.wait_for_selector('path[data-highlight="01"]')
    page.mouse.move(30, 600)
    page.wait_for_timeout(250)
    # 点击地图左下空白海域（避开左上缩放控件与右下 attribution）
    page.locator("#map").click(position={"x": 50, "y": 330})
    page.wait_for_timeout(250)
    assert page.locator('path[data-highlight="01"]').count() == 0  # 光晕消失（选中取消）


def test_member_line_selection_switches_to_other_line(page, live_url: str) -> None:
    _open_workbench(page, live_url)
    _widen_line_for_click(page, "01")
    page.click('path[data-member="01"]')
    page.wait_for_selector('path[data-highlight="01"]')
    _widen_line_for_click(page, "02")
    page.click('path[data-member="02"]')
    page.wait_for_selector('path[data-highlight="02"]')
    assert page.locator('path[data-highlight="01"]').count() == 0  # 旧选中光晕已移除
    assert page.locator('path[data-highlight="02"]').count() == 1
