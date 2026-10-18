"""UI E2E（Playwright 无头浏览器）：地图工作台核心交互回归。

覆盖成员线持久选中状态机：点线选中、鼠标离开保持、点空白取消、点其它线切换；
M5d 概率特征：统计图表渲染、p 默认 100%、应用按钮确认、堆叠层级次序、
低分母虚线、单成员模式隐藏统计卡；
M6 目标地点：预存地点下拉/坐标输入/地图点选、标记与参考圆、影响概率卡片
（含缺风圈列的显式不可用提示）；
M7a 参考圆分级配色：左栏图例与 Canvas 像素级可见性；
M7b 接口调用轻量加载提示：状态栏 busy 文案与上传按钮禁用；
M7c 位置概率半径图表暂隐藏：渲染停用但锚点与数据链路保留；
M7f 反经线（跨 180° 经线）绘制：成员线/均值轨迹/观测叠加走最短方向
（zoom 无关形状比断言，合成数据 signed 口径 179.0 -> -178.1 跳变）。
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

_RADIUS_COLS = ",".join(
    f"radius_{speed}_knot_winds_{quad}_km"
    for speed in (34, 50, 64)
    for quad in ("ne", "se", "sw", "nw")
)

# M6：2 成员 × 2 时效，含风圈列（成员 01 lead 0 的 NE 象限可命中构造点 17.8,132.4）
IMPACT_CSV = (
    "track_id,ensemble_member,init_time,valid_time,lead_time_hours,lat,lon,"
    "maximum_sustained_wind_speed_knots,minimum_sea_level_pressure_hpa,"
    f"{_RADIUS_COLS}\n"
    "SYN202601,01,2026-07-01T00:00:00Z,2026-07-01T00:00:00Z,0,17.5,132.0,35,1000,"
    "100,0,0,0,60,0,0,0,30,0,0,0\n"
    "SYN202601,01,2026-07-01T00:00:00Z,2026-07-02T00:00:00Z,24,18.5,132.5,34,999,"
    "80,0,0,0,50,0,0,0,0,0,0,0\n"
    "SYN202601,02,2026-07-01T00:00:00Z,2026-07-01T00:00:00Z,0,17.0,131.5,30,1002,"
    "0,0,0,0,0,0,0,0,0,0,0,0\n"
    "SYN202601,02,2026-07-01T00:00:00Z,2026-07-02T00:00:00Z,24,18.0,132.0,31,1001,"
    "0,0,0,0,0,0,0,0,0,0,0,0\n"
)

PLACES_CSV = "name,lat,lon,note\n那霸,26.2124,127.6809,冲绳\n"

# 跨 180° 经线（反经线）合成用例：0–360° 约定 lon 176.5 -> 184.5，signed 口径在
# lead 24->48 出现 179.0 -> -178.1 跳变（Leaflet 折线无反经线感知，需组内展开）。
# 轨迹取转向（recurve）形态带明显曲率：保证任意视图缩放下顶点都不被 smoothFactor
# 简化丢弃（近似直线的轨迹在贴合视图下会塌缩成 2 顶点，形状比探针失效）
AMERIDIAN_CSV = (
    "track_id,ensemble_member,init_time,valid_time,lead_time_hours,lat,lon,"
    "maximum_sustained_wind_speed_knots,minimum_sea_level_pressure_hpa\n"
    "AMER001,01,2026-10-14T00:00:00Z,2026-10-14T00:00:00Z,0,16.0,176.5,45,992\n"
    "AMER001,01,2026-10-14T00:00:00Z,2026-10-15T00:00:00Z,24,20.0,179.0,55,984\n"
    "AMER001,01,2026-10-14T00:00:00Z,2026-10-16T00:00:00Z,48,22.5,181.9,65,975\n"
    "AMER001,01,2026-10-14T00:00:00Z,2026-10-17T00:00:00Z,72,22.8,184.5,75,965\n"
    "AMER001,02,2026-10-14T00:00:00Z,2026-10-14T00:00:00Z,0,15.4,175.8,40,996\n"
    "AMER001,02,2026-10-14T00:00:00Z,2026-10-15T00:00:00Z,24,19.4,178.3,50,988\n"
    "AMER001,02,2026-10-14T00:00:00Z,2026-10-16T00:00:00Z,48,21.9,181.2,60,979\n"
    "AMER001,02,2026-10-14T00:00:00Z,2026-10-17T00:00:00Z,72,22.3,184.0,70,969\n"
)

# 同气旋观测参考轨迹（ensemble_member 列对观测无语义，保留表头一致便于复用）
AMERIDIAN_OBS_CSV = (
    "track_id,ensemble_member,init_time,valid_time,lead_time_hours,lat,lon,"
    "maximum_sustained_wind_speed_knots,minimum_sea_level_pressure_hpa\n"
    "AMER001,00,2026-10-14T00:00:00Z,2026-10-14T00:00:00Z,0,15.7,176.1,43,994\n"
    "AMER001,00,2026-10-14T00:00:00Z,2026-10-15T00:00:00Z,24,19.7,178.6,52,986\n"
    "AMER001,00,2026-10-14T00:00:00Z,2026-10-16T00:00:00Z,48,22.2,181.5,63,977\n"
    "AMER001,00,2026-10-14T00:00:00Z,2026-10-17T00:00:00Z,72,22.6,184.2,73,967\n"
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


@pytest.fixture
def live_url_impact(tmp_path: Path) -> Iterator[str]:
    yield from _start_server(tmp_path, IMPACT_CSV.encode(), places_csv=PLACES_CSV.encode())


@pytest.fixture
def live_url_antimeridian(tmp_path: Path) -> Iterator[str]:
    yield from _start_server(
        tmp_path, AMERIDIAN_CSV.encode(), obs_csv=AMERIDIAN_OBS_CSV.encode(),
    )


def _start_server(
    tmp_path: Path,
    csv: bytes,
    places_csv: bytes | None = None,
    obs_csv: bytes | None = None,
) -> Iterator[str]:
    store = DatasetStore(tmp_path)
    store.create(filename="ens.csv", content=csv, kind="forecast")
    if obs_csv is not None:
        store.create(filename="obs.csv", content=obs_csv, kind="observation")
    places_path = None
    if places_csv is not None:
        places_path = tmp_path / "places" / "places.csv"
        places_path.parent.mkdir(parents=True, exist_ok=True)
        places_path.write_bytes(places_csv)
    config = Config(
        create_app(store, places_path=places_path),
        host="127.0.0.1", port=_free_port(), log_level="warning",
    )
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
    for chart_id in ("#stack-chart", "#pressure-chart"):
        page.wait_for_selector(f"{chart_id} canvas")
    # M7c：位置概率半径图表暂隐藏（数据链路与 data-p/data-low-count 锚点保留）
    assert "hidden" in (page.locator("#radius-wrap").get_attribute("class") or "")
    assert page.locator("#radius-chart canvas").count() == 0


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
    page.wait_for_selector("#stack-chart canvas")
    # LOW001 lead 48 仅 1/4 成员在场（25% < 30%）→ 低分母时次数 = 1（虚线序列启用；
    # M7c 半径图隐藏后，低分母事实经解耦锚点 data-low-count 锁定）
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
    page.wait_for_selector("#stack-chart canvas")
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


# ---------- M6 目标地点与影响概率 ----------


def _set_target_by_inputs(page, live_url: str, lat: str = "17.8", lon: str = "132.4") -> None:
    page.goto(live_url)
    page.wait_for_selector("#storm option", state="attached")
    page.fill("#target-lat", lat)
    page.fill("#target-lon", lon)
    page.click("#target-apply")


def test_target_by_inputs_renders_marker_circles_and_impact(page, live_url_impact: str) -> None:
    _set_target_by_inputs(page, live_url_impact)
    page.wait_for_selector("[data-target-marker]", state="attached")
    assert page.locator("#map").get_attribute("data-target-circles") == "100,200,400,800"
    legend = page.locator("#target-circle-legend .item")
    assert legend.count() == 4
    assert legend.all_inner_texts() == ["100 km", "200 km", "400 km", "800 km"]
    page.wait_for_selector("#impact-wrap:not(.hidden)")
    text = page.locator("#impact-body").inner_text()
    # 成员 01 lead 0 NE 象限 ~52km：烈风/暴风 1/2，飓风 0/2；最近接近 lead 24（NNW）；
    # M7d 第四行核心强风区：IMPACT_CSV 无 rmw 列 → 0/2（不命中留在分母）
    assert "烈风（风速≥34 kt）" in text and "50.0%" in text and "1/2 成员" in text
    assert "飓风（风速≥64 kt）" in text and "0.0%" in text
    assert "核心强风区（距离≤RMW）" in text
    assert "最近接近（mean 口径）" in text and "24 h" in text and "NNW" in text
    assert page.locator("#impact-wrap").get_attribute("data-impact-total") == "2"


def test_target_reference_circles_colored_and_visible(page, live_url_impact: str) -> None:
    # M7a：四圈分级配色（玫红/橙/金/紫）真实绘制在 Canvas 上（像素级可见性抽检）；
    # 色距阈值 1500 已与强度色阶（如 H4 红 #d62828）、成员色、概率圆蓝相互分离
    _set_target_by_inputs(page, live_url_impact)
    page.wait_for_selector("[data-target-marker]", state="attached")
    # 视图默认贴合轨迹范围：逐级缩小直至最大参考圆（800 km，紫色）进入视口
    violet_probe = """
      () => {
        let n = 0;
        for (const canvas of document.querySelectorAll('#map canvas')) {
          const ctx = canvas.getContext('2d');
          if (!ctx || !canvas.width || !canvas.height) continue;
          const img = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
          for (let y = 0; y < canvas.height; y += 2) {
            for (let x = 0; x < canvas.width; x += 2) {
              const i = (y * canvas.width + x) * 4;
              if (img[i + 3] < 150) continue;
              if ((img[i]-109)**2 + (img[i+1]-40)**2 + (img[i+2]-217)**2 < 1500) n++;
            }
          }
        }
        return n;
      }"""
    for _ in range(10):
        if page.evaluate(violet_probe) > 3:
            break
        page.click(".leaflet-control-zoom-out")
        page.wait_for_timeout(400)
    page.wait_for_timeout(400)  # 等 zoom 动画与 Canvas 重绘稳定
    counts = page.evaluate("""
      () => {
        const targets = [[219,39,119],[234,88,12],[202,138,4],[109,40,217]];
        const counts = new Array(targets.length).fill(0);
        for (const canvas of document.querySelectorAll('#map canvas')) {
          const ctx = canvas.getContext('2d');
          if (!ctx || !canvas.width || !canvas.height) continue;
          const img = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
          for (let y = 0; y < canvas.height; y += 2) {
            for (let x = 0; x < canvas.width; x += 2) {
              const i = (y * canvas.width + x) * 4;
              if (img[i + 3] < 150) continue;
              for (let k = 0; k < targets.length; k++) {
                const [r, g, b] = targets[k];
                const d = (img[i]-r)**2 + (img[i+1]-g)**2 + (img[i+2]-b)**2;
                if (d < 1500) { counts[k] += 1; break; }
              }
            }
          }
        }
        return counts;
      }""")
    assert all(c > 3 for c in counts), counts


def test_target_clear_removes_layers_and_card(page, live_url_impact: str) -> None:
    _set_target_by_inputs(page, live_url_impact)
    page.wait_for_selector("[data-target-marker]", state="attached")
    page.click("#target-clear")
    page.wait_for_timeout(300)
    assert page.locator("[data-target-marker]").count() == 0
    assert page.locator("#map").get_attribute("data-target-circles") is None
    assert page.locator("#target-lat").input_value() == ""
    assert "hidden" in (page.locator("#impact-wrap").get_attribute("class") or "")


def test_places_dropdown_selects_target(page, live_url_impact: str) -> None:
    page.goto(live_url_impact)
    page.wait_for_selector("#storm option", state="attached")
    page.select_option("#place-select", "那霸")
    page.wait_for_selector("[data-target-marker]", state="attached")
    assert page.locator("#target-lat").input_value() == "26.2124"
    assert page.locator("#target-lon").input_value() == "127.6809"
    page.wait_for_selector("#impact-wrap:not(.hidden)")
    text = page.locator("#impact-body").inner_text()
    assert "那霸" in text  # 目标行显示预存地名
    assert text.count("0.0%") == 4  # 远离气旋：三级概率与核心强风区均为 0（M7d 后共 4 行）


def test_invalid_target_coordinates_rejected(page, live_url_impact: str) -> None:
    page.goto(live_url_impact)
    page.wait_for_selector("#storm option", state="attached")
    page.fill("#target-lat", "120")
    page.fill("#target-lon", "132")
    page.click("#target-apply")
    page.wait_for_timeout(300)
    assert page.locator("[data-target-marker]").count() == 0
    assert "目标坐标无效" in page.locator("#status").inner_text()


def test_pick_mode_map_click_sets_target(page, live_url_impact: str) -> None:
    page.goto(live_url_impact)
    page.wait_for_selector("#storm option", state="attached")
    page.wait_for_timeout(500)  # 等 fitBounds 稳定后先缩小视图，确保点击处为空白海域
    page.click(".leaflet-control-zoom-out")
    page.click(".leaflet-control-zoom-out")
    page.wait_for_timeout(400)
    page.click("#target-pick")
    assert page.locator("#map").get_attribute("data-pick-mode") == "1"
    page.locator("#map").click(position={"x": 60, "y": 320})
    page.wait_for_selector("[data-target-marker]", state="attached")
    assert page.locator("#map").get_attribute("data-pick-mode") is None
    assert page.locator("#target-pick").inner_text() == "地图点选"


def test_impact_card_shows_missing_radius_error(page, live_url: str) -> None:
    # MEMBERS 样本无风圈列：显式展示不可用原因，不提供距离回退
    page.goto(live_url)
    page.wait_for_selector("#storm option", state="attached")
    page.fill("#target-lat", "17.5")
    page.fill("#target-lon", "132.0")
    page.click("#target-apply")
    page.wait_for_selector("#impact-wrap:not(.hidden)")
    text = page.locator("#impact-body").inner_text()
    assert "缺少风圈字段" in text and "不提供距离回退" in text


# ---------- M7b 接口调用加载提示（轻量：状态栏 busy 文案 + 上传按钮禁用） ----------


def test_loading_status_during_slow_api(page, live_url_impact: str) -> None:
    # 耗时接口期间状态栏显示"查询中/计算中/加载中"，结束后恢复非忙碌文案。
    # goto 用 domcontentloaded：默认 load 会等远程瓦片，可能错过短暂的 busy 窗口
    def delay(route):
        time.sleep(0.8)
        route.continue_()

    page.route("**/tracks*", delay)
    page.goto(live_url_impact, wait_until="domcontentloaded")
    page.wait_for_function(
        "() => /(查询中|计算中|加载中)/.test(document.getElementById('status').textContent)"
    )
    page.wait_for_function(
        "() => !/(查询中|计算中|加载中)/.test(document.getElementById('status').textContent)"
    )
    page.wait_for_selector('path[data-member="01"]')


def test_upload_button_disabled_while_parsing(page, live_url: str) -> None:
    # 上传解析期间按钮禁用，完成后恢复可用并显示导入成功
    def delay(route):
        time.sleep(0.8)
        route.continue_()

    page.route("**/api/datasets", delay)
    page.goto(live_url, wait_until="domcontentloaded")
    page.wait_for_selector("#storm option", state="attached")
    page.set_input_files("#upload-file", MEMBERS)
    submit = page.locator("#upload-form button[type=submit]")
    submit.click()
    assert submit.is_disabled()
    page.wait_for_timeout(2500)  # 0.8s 延迟 + 数据集列表刷新与 storm 链路
    assert not submit.is_disabled()
    # 上传链路完成：预报数据集下拉增至 2 项，且状态栏被后续行数文案接管（导入成功已被覆盖，属既有行为）
    assert page.locator("#fc-dataset option").count() == 2
    assert "行 / 成员" in page.locator("#status").inner_text()


# ---------- 反经线（跨 180° 经线）绘制：连线走最短方向，不横穿整幅地图 ----------


def _max_path_wrap_ratio(page) -> float:
    """地图全部折线路径的「相邻顶点最大步长 / 总跨度」（zoom 无关的形状比）。

    未展开 ±180 跳变时，跨经线段一步即几乎横跨整个 bbox（比值 ≈ 1.0，
    实测修复前 ≈ 0.993，占世界宽 99.3%）；正常逐时次推进的轨迹相邻步长
    远小于总跨度（本用例 ≈ 0.34）。只解析纯 M/L 折线（圆类 path 含 a/m 弧
    命令，数值无步长语义，跳过）；引线（data-mean-leader，两点连线）天然
    比值为 1，排除。
    """
    return page.evaluate(
        """() => {
          const paths = [...document.querySelectorAll('#map svg path[d]:not([data-mean-leader])')];
          let worst = 0;
          for (const p of paths) {
            const d = p.getAttribute('d');
            if (!/^M[-\\d.,\\s]+(?:L[-\\d.,\\s]+)*$/.test(d)) continue;
            const nums = (d.match(/-?\\d+(?:\\.\\d+)?/g) || []).map(Number);
            const xs = [];
            for (let i = 0; i + 1 < nums.length; i += 2) xs.push(nums[i]);
            if (xs.length < 2) continue;
            let maxStep = 0;
            for (let i = 1; i < xs.length; i += 1) {
              maxStep = Math.max(maxStep, Math.abs(xs[i] - xs[i - 1]));
            }
            const span = Math.max(...xs) - Math.min(...xs);
            if (span > 0) worst = Math.max(worst, maxStep / span);
          }
          return worst;
        }"""
    )


def test_antimeridian_member_and_mean_lines_follow_shortest_path(
    page, live_url_antimeridian: str,
) -> None:
    # 修复前：179.0 -> -178.1 的 signed 跳变被 Leaflet 连成经 0° 绕行 ~356° 的横穿线，
    # fitBounds 同步被拉到近全球尺度（复现与修复记录见 docs/反经线绘制缺陷修复验收记录_20261018.md）
    page.goto(live_url_antimeridian)
    page.wait_for_selector('path[data-member="01"]')
    page.wait_for_selector('path[data-mean-track]')
    page.wait_for_timeout(600)  # 等 fitBounds 视图与路径几何稳定
    ratio = _max_path_wrap_ratio(page)
    assert ratio < 0.6, f"存在横穿世界的路径段（最大步长/总跨度 = {ratio}）"


def test_antimeridian_observation_overlay_follows_shortest_path(
    page, live_url_antimeridian: str,
) -> None:
    # 观测叠加（虚线）与观测点同样按组展开：不因叠加引入横穿线
    page.goto(live_url_antimeridian)
    page.wait_for_selector('path[data-member="01"]')
    page.select_option("#obs-dataset", index=1)  # 唯一观测数据集
    page.wait_for_selector('#map svg path[stroke-dasharray]')
    page.wait_for_timeout(600)
    ratio = _max_path_wrap_ratio(page)
    assert ratio < 0.6, f"观测叠加存在横穿世界的路径段（最大步长/总跨度 = {ratio}）"
