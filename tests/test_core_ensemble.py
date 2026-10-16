"""core.ensemble 与 core.geo 扩展：球面均值/大圆距离/概率半径/强度分布测试。"""

from __future__ import annotations

import math

import pandas as pd
import pytest

from typhoon_track.core import (
    CATEGORY_STACK_BOTTOM_UP,
    DEFAULT_P_VALUES,
    DISSIPATED_KEY,
    LOW_DENOMINATOR_FRACTION,
    UNKNOWN_KEY,
    WIND_CATEGORIES,
    ensemble_profile,
    haversine_km,
    spherical_mean,
    wind_category,
)

EARTH_RADIUS_KM = 6371.0088


def make_frame(rows: list[dict]) -> pd.DataFrame:
    """构造已 normalize 语义的单气旋预报帧；缺省字段由下方默认值补齐。"""
    base = {
        "storm": "SYN",
        "member": "0",
        "init": pd.Timestamp("2026-10-15T18:00:00", tz="UTC"),
        "valid": pd.Timestamp("2026-10-15T18:00:00", tz="UTC"),
        "lead_h": 0.0,
        "lat": 10.0,
        "lon": 130.0,
        "wind": 30.0,
        "pressure": 1000.0,
    }
    return pd.DataFrame([{**base, **row} for row in rows])


# ---------- geo：haversine / spherical_mean ----------


def test_haversine_known_distances() -> None:
    assert haversine_km(10.0, 130.0, 10.0, 130.0) == pytest.approx(0.0, abs=1e-9)
    # 赤道上经差 90°：四分之一周长
    assert haversine_km(0.0, 0.0, 0.0, 90.0) == pytest.approx(math.pi / 2 * EARTH_RADIUS_KM, rel=1e-9)
    # 对跖点：半周长
    assert haversine_km(0.0, 0.0, 0.0, 180.0) == pytest.approx(math.pi * EARTH_RADIUS_KM, rel=1e-9)
    # 两套经度约定结果一致（350° == -10°）
    assert haversine_km(0.0, 350.0, 0.0, 10.0) == pytest.approx(haversine_km(0.0, -10.0, 0.0, 10.0))


def test_spherical_mean_identical_points() -> None:
    lat, lon = spherical_mean(pd.Series([12.5, 12.5, 12.5]), pd.Series([131.2, 131.2, 131.2]))
    assert lat == pytest.approx(12.5)
    assert lon == pytest.approx(131.2)


def test_spherical_mean_antimeridian() -> None:
    # 跨 ±180°：179 与 -179 的平均经度应为 ±180（算术平均会错误地得 0）；
    # 中点纬度按大圆几何略高于 10°（向极凸）：atan2(sinφ, cosφ·cos(Δλ/2))
    lat, lon = spherical_mean(pd.Series([10.0, 10.0]), pd.Series([179.0, -179.0]))
    expected_lat = math.degrees(
        math.atan2(math.sin(math.radians(10.0)), math.cos(math.radians(10.0)) * math.cos(math.radians(1.0)))
    )
    assert lat == pytest.approx(expected_lat, abs=1e-9)
    assert abs(lon) == pytest.approx(180.0)


def test_spherical_mean_skips_incomplete_pairs_and_all_missing() -> None:
    lat, lon = spherical_mean(pd.Series([10.0, None, 20.0]), pd.Series([130.0, 140.0, None]))
    assert lat == pytest.approx(10.0)
    assert lon == pytest.approx(130.0)
    nan_lat, nan_lon = spherical_mean(pd.Series([None]), pd.Series([None]))
    assert math.isnan(nan_lat)
    assert math.isnan(nan_lon)


def test_spherical_mean_rejects_cancellation() -> None:
    with pytest.raises(ValueError, match="位置接近对消"):
        spherical_mean(pd.Series([0.0, 0.0]), pd.Series([0.0, 180.0]))


# ---------- ensemble：强度分级常量 ----------


def test_wind_category_boundaries() -> None:
    assert wind_category(137.0).key == "H5"
    assert wind_category(136.9).key == "H4"
    assert wind_category(96.0).key == "H3"
    assert wind_category(83.0).key == "H2"
    assert wind_category(64.0).key == "H1"
    assert wind_category(34.0).key == "TS"
    assert wind_category(0.0).key == "TD"
    assert [c.min_kt for c in WIND_CATEGORIES if math.isfinite(c.min_kt)] == [137, 113, 96, 83, 64, 34]


def test_stack_order_intuitive_no_h5_next_to_dissipated() -> None:
    # 自底向上：已消散 → TD → TS → H1…H5（强度单调递增；消散只邻 TD，H5 只邻 H4）
    assert CATEGORY_STACK_BOTTOM_UP == (DISSIPATED_KEY, "TD", "TS", "H1", "H2", "H3", "H4", "H5")
    assert DEFAULT_P_VALUES == (40, 50, 60, 70, 80, 90, 100)


# ---------- ensemble：ensemble_profile ----------


def test_profile_means_and_radius_quantile_selection() -> None:
    rows = []
    for member, lon in (("0", 0.0), ("1", 1.0), ("2", 2.0), ("3", 10.0)):
        rows.append({"member": member, "lon": lon, "lat": 0.0, "wind": 20.0 + float(member) * 30.0})
    profiles = ensemble_profile(make_frame(rows))
    assert len(profiles) == 1
    profile = profiles[0]
    assert profile.n_total == 4
    assert profile.n_present == 4
    assert profile.mean_wind == pytest.approx((20.0 + 50.0 + 80.0 + 110.0) / 4)
    assert profile.mean_pressure == pytest.approx(1000.0)
    assert profile.valid == pd.Timestamp("2026-10-15T18:00:00", tz="UTC")
    # 半径 = 覆盖最近 p% 成员的最小距离：以返回的均值中心自算距离核对分位取值
    assert profile.mean_lat is not None and profile.mean_lon is not None
    distances = sorted(
        haversine_km(profile.mean_lat, profile.mean_lon, 0.0, lon)
        for lon in (0.0, 1.0, 2.0, 10.0)
    )
    assert profile.radius_km[100] == pytest.approx(distances[3])  # ceil(1.0×4)=4
    assert profile.radius_km[50] == pytest.approx(distances[1])  # ceil(0.5×4)=2
    assert profile.radius_km[40] == pytest.approx(distances[1])  # ceil(0.4×4)=ceil(1.6)=2
    radius_100 = profile.radius_km[100]
    radius_40 = profile.radius_km[40]
    assert radius_100 is not None and radius_40 is not None
    assert radius_100 >= radius_40 >= 0.0


def test_profile_tail_denominator_dissipated_and_low_flag() -> None:
    rows = [
        {"member": "0", "lead_h": 0.0},
        {"member": "1", "lead_h": 0.0},
        {"member": "2", "lead_h": 0.0},
        {"member": "0", "lead_h": 6.0},
        {"member": "1", "lead_h": 6.0},
        {"member": "0", "lead_h": 12.0},  # 尾部仅剩 1/3 成员，略高于 30% 阈值
        {"member": "0", "lead_h": 18.0},
    ]
    profiles = {p.lead_h: p for p in ensemble_profile(make_frame(rows))}
    assert set(profiles) == {0.0, 6.0, 12.0, 18.0}  # 只取实际存在的时次
    assert profiles[0.0].n_present == 3
    assert profiles[6.0].category_counts[DISSIPATED_KEY] == 1
    assert profiles[12.0].low_denominator is False  # 1/3 ≈ 33% > 30%
    # 构造 4 成员仅剩 1 名（25% < 30%）的场景验证低分母标记
    rows_low = [
        {"member": str(m), "lead_h": 0.0} for m in range(4)
    ] + [{"member": "0", "lead_h": 6.0}]
    low = {p.lead_h: p for p in ensemble_profile(make_frame(rows_low))}
    assert low[6.0].low_denominator is True
    assert low[6.0].category_counts[DISSIPATED_KEY] == 3
    assert low[0.0].low_denominator is False
    assert LOW_DENOMINATOR_FRACTION == 0.3


def test_profile_category_counts_and_unknown_wind() -> None:
    rows = [
        {"member": "0", "wind": 30.0},   # TD
        {"member": "1", "wind": 40.0},   # TS
        {"member": "2", "wind": 70.0},   # H1
        {"member": "3", "wind": None},   # 缺失 -> UNKNOWN（不臆测为 0）
    ]
    profile = ensemble_profile(make_frame(rows))[0]
    assert profile.category_counts["TD"] == 1
    assert profile.category_counts["TS"] == 1
    assert profile.category_counts["H1"] == 1
    assert profile.category_counts[UNKNOWN_KEY] == 1
    assert profile.mean_wind == pytest.approx((30.0 + 40.0 + 70.0) / 3)
    # 全部风速缺失：均值保持 None
    profile_all_missing = ensemble_profile(make_frame([{"member": "0", "wind": None}]))[0]
    assert profile_all_missing.mean_wind is None
    assert profile_all_missing.category_counts[UNKNOWN_KEY] == 1


def test_profile_without_member_column_is_single_track() -> None:
    frame = make_frame([{"lead_h": 0.0, "wind": 35.0}, {"lead_h": 6.0, "wind": 45.0}]).drop(columns=["member"])
    profiles = {p.lead_h: p for p in ensemble_profile(frame)}
    assert profiles[0.0].n_total == 1
    assert profiles[6.0].category_counts[DISSIPATED_KEY] == 0
    assert profiles[6.0].mean_wind == pytest.approx(45.0)
    assert profiles[6.0].low_denominator is False


def test_profile_missing_positions_yield_none() -> None:
    frame = make_frame([{"member": "0", "lat": None, "lon": None}])
    profile = ensemble_profile(frame)[0]
    assert profile.mean_lat is None
    assert profile.mean_lon is None
    assert profile.radius_km[100] is None


def test_profile_rejects_mixed_storm_and_init() -> None:
    with pytest.raises(ValueError, match="不跨气旋混合统计"):
        ensemble_profile(make_frame([{"storm": "A"}, {"storm": "B"}]))
    with pytest.raises(ValueError, match="不跨起报时次混合统计"):
        ensemble_profile(make_frame([{"init": pd.Timestamp("2026-10-15T18:00:00", tz="UTC")},
                                     {"init": pd.Timestamp("2026-10-16T00:00:00", tz="UTC")}]))


def test_profile_rejects_duplicate_member_lead_rows() -> None:
    rows = [{"member": "0", "lead_h": 0.0}, {"member": "0", "lead_h": 0.0, "wind": 50.0}]
    with pytest.raises(ValueError, match="拒绝静默去重"):
        ensemble_profile(make_frame(rows))


def test_profile_requires_lead_h() -> None:
    with pytest.raises(ValueError, match="缺少预报时效 lead_h"):
        ensemble_profile(make_frame([{"lead_h": 0.0}]).drop(columns=["lead_h"]))
