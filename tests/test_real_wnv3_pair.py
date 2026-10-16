"""WNV3 同起报配对（ensemble + 官方 mean 产品）真实数据交叉验证。

验证口径（详见 docs/M5口径验证记录_20261016.md）：自算统计与官方 mean 产品逐点一致——
- 风速/气压：在场成员算术平均（产品舍入到 0.1）；
- 位置：球面矢量平均（产品舍入到 2 位小数）；
- 尾部方案 b：仅统计该时次在场成员（WP292026 尾部消散段同样吻合）。
任一文件缺失时自动跳过；原始文件保持原样。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from typhoon_track.core import (
    DISSIPATED_KEY,
    ensemble_profile,
    filter_rows,
    make_mapping,
    normalize,
    read_csv,
)

DEMO = Path(__file__).resolve().parents[1] / "demo_src"
ENSEMBLE = DEMO / "WNV3_2026_10_15T18_00_paired_ensemble.csv"
MEAN = DEMO / "WNV3_2026_10_15T18_00_paired_mean.csv"

pytestmark = pytest.mark.skipif(
    not (ENSEMBLE.is_file() and MEAN.is_file()),
    reason="WNV3 配对 CSV 未放入 demo_src，跳过真实交叉验证",
)

STORMS = ("EP202026", "EP212026", "SH922026", "WP292026")


def _frame(path: Path):
    df = read_csv(path)
    return normalize(df, make_mapping(df.columns)).frame


@pytest.fixture(scope="module")
def ens_frame():
    return _frame(ENSEMBLE)


@pytest.fixture(scope="module")
def mean_frame():
    return _frame(MEAN)


def test_wnv3_ensemble_shape(ens_frame) -> None:
    assert len(ens_frame) == 5524
    assert ens_frame["member"].nunique() == 64  # WNV3 为 64 成员（FNV3P2 是 50，勿硬编码）
    assert ens_frame["storm"].nunique() == len(STORMS)


@pytest.mark.parametrize("storm", STORMS)
def test_wnv3_pair_self_computed_stats_match_official_mean(ens_frame, mean_frame, storm: str) -> None:
    profiles = {p.lead_h: p for p in ensemble_profile(filter_rows(ens_frame, storm=storm))}
    product_rows = filter_rows(mean_frame, storm=storm)
    assert bool(product_rows["lead_h"].notna().all())
    assert profiles[0.0].n_total == 64
    checked = 0
    for record in product_rows.to_dict("records"):
        lead_h = float(record["lead_h"])
        profile = profiles[lead_h]
        # 官方产品舍入到 0.1（风速/气压）与 2 位小数（经纬度），容差取半个舍入单位加余量
        assert profile.mean_wind == pytest.approx(float(record["wind"]), abs=0.05), (
            f"{storm} lead={lead_h}h 风速: 自算 {profile.mean_wind} vs 产品 {record['wind']}"
        )
        assert profile.mean_pressure == pytest.approx(float(record["pressure"]), abs=0.06), (
            f"{storm} lead={lead_h}h 气压: 自算 {profile.mean_pressure} vs 产品 {record['pressure']}"
        )
        assert profile.mean_lat == pytest.approx(float(record["lat"]), abs=0.006), (
            f"{storm} lead={lead_h}h 纬度: 自算 {profile.mean_lat} vs 产品 {record['lat']}"
        )
        assert profile.mean_lon == pytest.approx(float(record["lon"]), abs=0.006), (
            f"{storm} lead={lead_h}h 经度: 自算 {profile.mean_lon} vs 产品 {record['lon']}"
        )
        checked += 1
    assert checked == len(product_rows)  # 产品每行都已核对


def test_wnv3_total_checked_points_and_tail_facts(ens_frame, mean_frame) -> None:
    total = sum(len(filter_rows(mean_frame, storm=s)) for s in STORMS)
    assert total == 94  # 官方 mean 产品全部核对点数（含 WP292026 消散尾部）
    wp_profiles = {p.lead_h: p for p in ensemble_profile(filter_rows(ens_frame, storm="WP292026"))}
    # 尾部方案 b 的实证：lead 246 在场 20/64，消散 44；成员实际延续到 288（产品在 246 后停止）
    assert wp_profiles[246.0].n_present == 20
    assert wp_profiles[246.0].category_counts[DISSIPATED_KEY] == 44
    assert wp_profiles[246.0].low_denominator is False  # 20/64 ≈ 31% > 30%
    assert set(wp_profiles) >= {0.0, 246.0, 288.0}
