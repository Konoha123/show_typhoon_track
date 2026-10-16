"""UI E2E（Playwright 无头浏览器）：地图工作台核心交互回归。

覆盖成员线持久选中状态机：点线选中、鼠标离开保持、点空白取消、点其它线切换；
M5d 概率特征：统计图表渲染、p 默认 100%、应用按钮确认、堆叠层级次序、
低分母虚线、单成员模式隐藏统计卡。
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

# 4 成员、lead 48 仅剩 1 名（25% < 30%）：触发低分母降权
LOW_DENOM_CSV = (
    "track_id,ensemble_member,init_time,valid_time,lead_time_hours,lat,lon,"
    "maximum_sustained_wind_speed_knots,minimum_sea_level_pressure_hpa\n"
    "LOW001,01,2026-07-01T00:00:00Z,2026-07-01T00:00:00Z,0,17.5,132.0,35,1000\n"
    "LOW001,02,2026-07-01T00:00:00Z,2026-07-01T00:00:00Z,0,17.8,132.4,30,1004\n"
    "LOW001,03,2026-07-01T00:00:00Z,2026-07-01T00:00:00Z,0,17.2,131.8,40,996\n"
    "LOW001,04,2026-07-01T00:00:00Z,2026-07-01T00:00:00Z,0,17.6,132.2,33,1002\n"
    "LOW001,01,2026-07-01T00:00:00Z,2026-07-02T00:00:00Z,24,19.0,129.6,55,985\n"
    "LOW001,02,2026-07-01T00:00:00Z,2026-07-02T00:00:00Z,24,18.9,129.9,52,988\n"
    "LOW001,03,2026-07-01T00:00:00Z,2026-07-02T00:00:00Z,24,19.1,129.4,58,982\n"
    "LOW001,01,2026-07-01T00:00:00Z,2026-07-03T00:00:00Z,48,20.8,127.0,70,972\n"
)


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@pytest.fixture
def live_url(tmp_path: Path) -> Iterator[str]:
    yield from _start_server(tmp_path, MEMBERS.read_bytes())


@pytest.fixture
def live_url_low(tmp_path: Path) -> Iterator[str]:
    yield from _start_server(tmp_path, LOW_DENOM_CSV.encode())


def _start_server(tmp_path: Path, csv: bytes) -> Iterator[str]:
    store = DatasetStore(tmp_path)
    store.create(filename="ens.csv", content=csv, kind="forecast")
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


def _open_stats(page, live_url: str) -> None:
    page.goto(live_url)
    page.wait_for_selector("#storm option", state="attached")
    page.wait_for_selector('path[data-mean-track]')
    page.wait_for_selector("#map[data-current-circle]")
    for chart_id in ("#radius-chart", "#stack-chart", "#pressure-chart"):
        page.wait_for_selector(f"{chart_id} canvas")


def test_stats_charts_render_with_p_default_100(page, live_url: str) -> None:
    _open_stats(page, live_url)
    assert page.locator("#p-select").input_value() == "100"
    # Canvas 圆的锚点挂 #map 容器：当前圆 "p|radiusKm"
    current = page.locator("#map").get_attribute("data-current-circle")
    assert current is not None and current.startswith("100|")
    assert page.locator("#stack-wrap").get_attribute("data-n-total") == "2"
    # 左栏图例扩充"已消散"（与堆叠图底层灰带同源同色）
    assert "已消散" in page.locator("#legend").inner_text()


def test_p_change_requires_apply_confirmation(page, live_url: str) -> None:
    _open_stats(page, live_url)
    page.select_option("#p-select", "50")
    page.wait_for_timeout(200)
    # 未点"应用"：地图圆与半径图保持旧 p（100）
    assert page.locator("#map").get_attribute("data-current-circle").startswith("100|")
    assert page.locator("#radius-wrap").get_attribute("data-p") == "100"
    page.click("#p-apply")
    page.wait_for_function("document.getElementById('map').getAttribute('data-current-circle')?.startsWith('50|')")
    assert page.locator("#radius-wrap").get_attribute("data-p") == "50"


def test_stack_order_config_wiring(page, live_url: str) -> None:
    _open_stats(page, live_url)
    order = page.evaluate("window.STATS_CONFIG.stackBottomUp")
    assert order[0] == "DISSIPATED" and order[-1] == "H5"
    assert order[1] == "TD" and order[-2] == "H4"  # 已消散只邻 TD，H5 只邻 H4


def test_single_member_mode_hides_stats(page, live_url: str) -> None:
    _open_stats(page, live_url)
    page.select_option("#member", "01")
    page.wait_for_timeout(300)
    for card in ("#stack-wrap", "#radius-wrap", "#pressure-wrap"):
        assert "hidden" in (page.locator(card).get_attribute("class") or "")
    assert page.locator('path[data-mean-track]').count() == 0


def test_low_denominator_dashed_series(page, live_url_low: str) -> None:
    page.goto(live_url_low)
    page.wait_for_selector("#storm option", state="attached")
    page.wait_for_selector("#radius-chart canvas")
    # LOW001 lead 48 仅 1/4 成员在场（25% < 30%）→ 低分母时次数 = 1（虚线序列启用）
    assert page.locator("#radius-wrap").get_attribute("data-low-count") == "1"


def test_key_circles_and_labels_at_24h_steps(page, live_url: str) -> None:
    # members 样本 leads=0/24/48 无低分母：mean 线不截断；关键圆=0/24（48 为滑块当前时次）
    _open_stats(page, live_url)
    assert page.locator('path[data-mean-cut]').count() == 0
    key_leads = set((page.locator("#map").get_attribute("data-key-leads") or "").split(","))
    assert key_leads == {"0", "24"}
    labels = page.locator("[data-mean-label]")
    assert labels.count() == 2
    texts = {labels.nth(i).inner_text() for i in range(2)}
    assert any(t.startswith("0h·") for t in texts) and any(t.startswith("24h·") for t in texts)


def test_mean_track_cut_after_low_denominator(page, live_url_low: str) -> None:
    # LOW001 lead 48 低分母（1/4 在场）：mean 线截断于 48h，关键圆止于截断点（0/24）
    page.goto(live_url_low)
    page.wait_for_selector("#storm option", state="attached")
    page.wait_for_selector("#radius-chart canvas")
    cut = page.locator('path[data-mean-cut]')
    assert cut.count() == 1
    assert cut.first.get_attribute("data-mean-cut") == "48"
    key_leads = set((page.locator("#map").get_attribute("data-key-leads") or "").split(","))
    assert key_leads == {"0", "24"}


def test_stack_chart_bands_render_distinct_colors(page, live_url: str) -> None:
    # 防整图单色回归（R1 bug：不透明填充下数组末位带覆盖整图）：
    # members 样本仅 TD/TS 两带——应存在浅蓝(TD)与绿(TS)带色，且无 H5 紫
    _open_stats(page, live_url)
    counts = page.evaluate(
        """() => {
          const canvas = document.querySelector('#stack-chart canvas');
          const ctx = canvas.getContext('2d');
          const data = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
          const near = (r, g, b, R, G, B) => Math.abs(r - R) < 25 && Math.abs(g - G) < 25 && Math.abs(b - B) < 25;
          let green = 0, blue = 0, purple = 0, gray = 0;
          for (let i = 0; i < data.length; i += 4) {
            const r = data[i], g = data[i + 1], b = data[i + 2];
            if (data[i + 3] < 10) continue;
            if (near(r, g, b, 0x66, 0xc2, 0xa5)) green++;
            else if (near(r, g, b, 0x6f, 0xb7, 0xe0)) blue++;
            else if (near(r, g, b, 0x9d, 0x4e, 0xdd)) purple++;
            else if (near(r, g, b, 0x9c, 0xa3, 0xaf)) gray++;
          }
          return { green, blue, purple, gray };
        }"""
    )
    assert counts["green"] > 50, "未检测到 TS 绿带"
    assert counts["blue"] > 50, "未检测到 TD 浅蓝带"
    assert counts["purple"] == 0, "members 样本不应出现 H5 紫带"


def test_key_label_selection_highlights_circle(page, live_url: str) -> None:
    # 引线存在（0h/24h 两个关键标签各一条）
    _open_stats(page, live_url)
    page.wait_for_selector('[data-mean-label="24"] .mean-label-tag')
    assert page.locator('path[data-mean-leader]').count() == 2
    # 点击标签：对应概率圆高亮（#map 容器锚点）+ 标签选中态
    page.click('[data-mean-label="24"] .mean-label-tag')
    page.wait_for_function("document.getElementById('map').getAttribute('data-key-selected') === '24'")
    klass = page.locator('[data-mean-label="24"] .mean-label-tag').get_attribute("class") or ""
    assert "selected" in klass
    # 点击另一标签切换选中
    page.click('[data-mean-label="0"] .mean-label-tag')
    page.wait_for_function("document.getElementById('map').getAttribute('data-key-selected') === '0'")
    # 再点同一标签取消
    page.click('[data-mean-label="0"] .mean-label-tag')
    page.wait_for_timeout(200)
    assert page.locator("#map").get_attribute("data-key-selected") is None
    # 选中后点击地图空白海域取消（与成员选中同型）
    page.click('[data-mean-label="24"] .mean-label-tag')
    page.wait_for_function("document.getElementById('map').getAttribute('data-key-selected') === '24'")
    page.locator("#map").click(position={"x": 50, "y": 330})
    page.wait_for_timeout(250)
    assert page.locator("#map").get_attribute("data-key-selected") is None


def test_cursor_tooltip_shows_lead_and_mean(page, live_url: str) -> None:
    # 十字光标提示：全部成员模式显示时次 + 自算均值；单成员模式显示时次 + 风/压
    _open_stats(page, live_url)
    tip = page.locator("#chart .cursor-tip")
    page.hover("#chart", position={"x": 200, "y": 160})
    page.wait_for_timeout(400)
    text = tip.inner_text()
    assert "h · 均值" in text and " kt" in text, text
    page.hover("#pressure-chart", position={"x": 200, "y": 160})
    page.wait_for_timeout(400)
    assert "h · 均值气压" in page.locator("#pressure-chart .cursor-tip").inner_text()
    page.select_option("#member", "01")
    page.wait_for_timeout(400)
    page.hover("#chart", position={"x": 200, "y": 160})
    page.wait_for_timeout(400)
    single = page.locator("#chart .cursor-tip").inner_text()
    assert "h · 风" in single and "压" in single, single


def test_chart_titles_concise(page, live_url: str) -> None:
    # 标题不含开发指导性文字与重复的成员数信息
    _open_stats(page, live_url)
    titles = page.evaluate(
        "() => [...document.querySelectorAll('.u-title')].map(el => el.textContent)"
    )
    joined = " ".join(titles)
    assert "配色与地图一致" not in joined
    assert "自底向上" not in joined
    assert "成员，" not in joined


def test_mean_line_stays_visible_when_member_hovered(page, live_url: str) -> None:
    # 复现用户场景：hover 地图成员线触发 focus 淡出时，风速图均值线必须保持可见
    #（修复前 focus.alpha=0.12 作用于全部非聚焦 series，均值线被淡化到不可见）
    _open_stats(page, live_url)

    def mean_dark_cols() -> int:
        return page.evaluate("""() => {
          const c = document.querySelector('#chart canvas');
          if (!c) return -1;
          const ctx = c.getContext('2d');
          const W = c.width, H = c.height;
          const img = ctx.getImageData(0, 0, W, H).data;
          let cols = 0;
          for (let x = 40; x < W - 40; x += 8) {
            for (let y = 20; y < H - 20; y++) {
              const i = (y * W + x) * 4;
              if (img[i+3] > 200 && img[i] < 45 && img[i+1] < 50 && img[i+2] < 75) { cols++; break; }
            }
          }
          return cols;
        }""")

    before = mean_dark_cols()
    assert before > 5, "初始应可见均值线"
    _widen_line_for_click(page, "01")
    page.hover('path[data-member="01"]')
    page.wait_for_timeout(400)
    during = mean_dark_cols()
    assert during > 5, f"hover 成员时均值线被淡化（{before} -> {during}）"
    page.mouse.move(30, 600)  # 移出地图
    page.wait_for_timeout(300)
    after = mean_dark_cols()
    assert after > 5
