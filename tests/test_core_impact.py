"""core.impact 与 core.geo 方位扩展：象限判定/三级影响概率/最近接近/核心强风区（M7d）/成员级 CPA（M15）测试。

含 WNV3 真实数据抽核（文件缺失自动跳过）：
- 远点三级概率全 0；
- 按成员实际风圈构造的命中点必使对应阈值分子 ≥1（独立于实现的落点公式）；
- 目标点取 lead 0 自算均值位置时最近接近时效为 0 且距离 ≈ 0；
- 成员级 CPA 独立复算（pandas 逐成员最小距离/分档/扇区计数对照，M15）。
"""

from __future__ import annotations

import math
from pathlib import Path

import pandas as pd
import pytest

from typhoon_track.core import (
    COMPASS_8_SECTORS,
    WIND_THRESHOLDS,
    compass_8,
    compass_16,
    ensemble_profile,
    filter_rows,
    haversine_km,
    impact_profile,
    initial_bearing_deg,
    make_mapping,
    normalize,
    point_in_core_wind,
    point_in_wind_field,
    quadrant_of_bearing,
    read_csv,
)

EARTH_RADIUS_KM = 6371.0088

DEMO = Path(__file__).resolve().parents[1] / "demo_src"
REAL_ENSEMBLE = DEMO / "WNV3_2026_10_15T18_00_paired_ensemble.csv"


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
        "r34_ne": 0.0,
        "r34_se": 0.0,
        "r34_sw": 0.0,
        "r34_nw": 0.0,
        "r50_ne": 0.0,
        "r50_se": 0.0,
        "r50_sw": 0.0,
        "r50_nw": 0.0,
        "r64_ne": 0.0,
        "r64_se": 0.0,
        "r64_sw": 0.0,
        "r64_nw": 0.0,
    }
    return pd.DataFrame([{**base, **row} for row in rows])


def destination_point(lat: float, lon: float, bearing_deg: float, dist_km: float) -> tuple[float, float]:
    """球面落点公式（测试内独立实现）：从 (lat, lon) 沿方位角行进 dist_km 的坐标。"""
    delta = dist_km / EARTH_RADIUS_KM
    theta = math.radians(bearing_deg)
    phi1 = math.radians(lat)
    lam1 = math.radians(lon)
    phi2 = math.asin(
        math.sin(phi1) * math.cos(delta) + math.cos(phi1) * math.sin(delta) * math.cos(theta)
    )
    lam2 = lam1 + math.atan2(
        math.sin(theta) * math.sin(delta) * math.cos(phi1),
        math.cos(delta) - math.sin(phi1) * math.sin(phi2),
    )
    return math.degrees(phi2), math.degrees(lam2)


# ---------- geo：initial_bearing_deg / compass_16 ----------


def test_initial_bearing_cardinal_directions() -> None:
    assert initial_bearing_deg(0.0, 0.0, 1.0, 0.0) == pytest.approx(0.0, abs=1e-9)  # 正北
    assert initial_bearing_deg(0.0, 0.0, 0.0, 10.0) == pytest.approx(90.0, abs=1e-9)  # 正东
    assert initial_bearing_deg(0.0, 0.0, -1.0, 0.0) == pytest.approx(180.0, abs=1e-9)  # 正南
    assert initial_bearing_deg(0.0, 0.0, 0.0, -10.0) == pytest.approx(270.0, abs=1e-9)  # 正西


def test_initial_bearing_northeast_and_reverse() -> None:
    assert initial_bearing_deg(0.0, 0.0, 1.0, 1.0) == pytest.approx(45.0, abs=0.05)
    # 球面上正反初始方位角之差一般不恰为 180°（子午线收敛），仅在赤道/经线上严格成立
    forward = initial_bearing_deg(10.0, 130.0, 12.0, 133.0)
    backward = initial_bearing_deg(12.0, 133.0, 10.0, 130.0)
    assert (forward - backward) % 360.0 == pytest.approx(180.0, abs=10.0)


def test_initial_bearing_antimeridian_and_coincident() -> None:
    # 跨 ±180°：179.5°E 向东到 179.5°W 应为正东（两套经度约定自洽）
    assert initial_bearing_deg(0.0, 179.5, 0.0, -179.5) == pytest.approx(90.0, abs=1e-9)
    assert initial_bearing_deg(0.0, 179.5, 0.0, 180.5) == pytest.approx(90.0, abs=1e-9)
    assert initial_bearing_deg(10.0, 130.0, 10.0, 130.0) == pytest.approx(0.0, abs=1e-9)


def test_compass_16_sectors_and_boundaries() -> None:
    assert compass_16(0.0) == "N"
    assert compass_16(11.2499) == "N"
    assert compass_16(11.25) == "NNE"  # 分界归顺时针下一方位
    assert compass_16(33.75) == "NE"
    assert compass_16(90.0) == "E"
    assert compass_16(168.75) == "S"
    assert compass_16(258.75) == "W"  # 258.75° 为 W/WSW 分界，归顺时针下一方位 W
    assert compass_16(247.5) == "WSW"
    assert compass_16(348.75) == "N"
    assert compass_16(360.0) == "N"


# ---------- impact：象限与风圈判定 ----------


def test_quadrant_of_bearing_boundaries() -> None:
    assert quadrant_of_bearing(0.0) == "ne"
    assert quadrant_of_bearing(89.9) == "ne"
    assert quadrant_of_bearing(90.0) == "se"  # 90° 奇数倍分界归顺时针下一象限
    assert quadrant_of_bearing(179.9) == "se"
    assert quadrant_of_bearing(180.0) == "sw"
    assert quadrant_of_bearing(270.0) == "nw"
    assert quadrant_of_bearing(359.9) == "nw"
    assert quadrant_of_bearing(450.0) == "se"  # 360° 归一


def test_point_in_wind_field_quadrant_selection() -> None:
    # 点 (9.7, 130.3) 位于中心 (10, 130) 的东南（方位 ~135°），只有 se 象限半径有效
    assert point_in_wind_field(9.7, 130.3, 10.0, 130.0, {"ne": 500.0, "se": 10.0}) is False
    assert point_in_wind_field(9.7, 130.3, 10.0, 130.0, {"ne": 0.0, "se": 60.0}) is True


def test_point_in_wind_field_radius_semantics() -> None:
    distance = haversine_km(10.0, 130.0, 10.3, 130.3)
    assert point_in_wind_field(10.3, 130.3, 10.0, 130.0, {"ne": distance}) is True  # 含等号
    assert point_in_wind_field(10.3, 130.3, 10.0, 130.0, {"ne": distance - 1e-6}) is False
    assert point_in_wind_field(10.3, 130.3, 10.0, 130.0, {"ne": 0.0}) is False  # 0.0=该级风不存在
    assert point_in_wind_field(10.3, 130.3, 10.0, 130.0, {"ne": None}) is False  # 缺失不命中
    assert point_in_wind_field(10.3, 130.3, 10.0, 130.0, {}) is False  # 象限键缺失视同无半径


# ---------- M7d：核心强风区（距离 ≤ RMW，全向圆无象限） ----------


def test_point_in_core_wind_radius_semantics() -> None:
    distance = haversine_km(10.0, 130.0, 10.3, 130.3)  # ~46.8 km
    assert point_in_core_wind(10.3, 130.3, 10.0, 130.0, 60.0) is True
    assert point_in_core_wind(10.3, 130.3, 10.0, 130.0, distance) is True  # 含等号（同风圈口径）
    assert point_in_core_wind(10.3, 130.3, 10.0, 130.0, distance - 1e-6) is False
    # RMW 缺失 / 0 / 负值：该时次不命中（0.0=无核心区数据，不臆造）
    for rmw in (None, 0.0, -5.0):
        assert point_in_core_wind(10.3, 130.3, 10.0, 130.0, rmw) is False


def test_impact_profile_core_wind_member_hit_counts_once() -> None:
    # 成员 0 lead0 RMW=60 覆盖点（~46.8 km 命中）；lead24 中心远离不命中（仍只计一次）；
    # 成员 1 RMW 缺失 → 不命中但留在分母
    frame = make_frame(
        [
            {"member": "0", "rmw": 60.0},
            {"member": "0", "lead_h": 24.0, "lat": 15.0, "lon": 135.0, "rmw": 60.0},
            {"member": "1", "rmw": float("nan")},
        ]
    )
    core = impact_profile(frame, lat=10.3, lon=130.3).core_wind
    assert core.hit_members == 1
    assert core.total_members == 2
    assert core.fraction == pytest.approx(0.5)


def test_impact_profile_core_wind_column_absent_all_miss() -> None:
    # rmw 列整列缺失：不做运行时列探测（M7 规划已核实真实导出与合成样本均含该列），按全不命中
    core = impact_profile(
        make_frame([{"member": "0"}, {"member": "1"}]), lat=10.3, lon=130.3
    ).core_wind
    assert core.hit_members == 0
    assert core.total_members == 2
    assert core.fraction == pytest.approx(0.0)


# ---------- impact：impact_profile ----------


def test_impact_profile_threshold_probabilities() -> None:
    frame = make_frame(
        [
            {"member": "0", "r34_ne": 100.0, "r50_ne": 60.0, "r64_ne": 30.0},
            {"member": "1", "lat": 15.0, "lon": 135.0, "r34_ne": 50.0},
            {"member": "2", "lat": 40.0, "lon": 160.0},
            {"member": "3", "lat": None, "r34_ne": 1000.0},  # 中心缺失：该时次不参与判定
        ]
    )
    profile = impact_profile(frame, lat=10.3, lon=130.3)
    stats = {s.threshold_kt: s for s in profile.thresholds}
    assert tuple(s.threshold_kt for s in profile.thresholds) == WIND_THRESHOLDS
    assert stats[34].hit_members == 1 and stats[34].total_members == 4
    assert stats[34].fraction == pytest.approx(0.25)
    assert stats[50].hit_members == 1 and stats[50].fraction == pytest.approx(0.25)
    assert stats[64].hit_members == 0 and stats[64].fraction == pytest.approx(0.0)


def test_impact_profile_member_hit_counts_once_across_leads() -> None:
    frame = make_frame(
        [
            {"lead_h": 0.0, "r34_ne": 5.0},  # 距离 ~46.8 km > 5 km：未命中
            {"lead_h": 12.0, "lat": 10.35, "lon": 130.35, "r34_sw": 20.0},  # 点在其 SW ~7.8 km：命中
            {"lead_h": 24.0, "lat": 10.35, "lon": 130.35, "r34_sw": 20.0},  # 再次命中仍只计一次
        ]
    )
    stats = {s.threshold_kt: s for s in impact_profile(frame, lat=10.3, lon=130.3).thresholds}
    assert stats[34].total_members == 1
    assert stats[34].hit_members == 1
    assert stats[34].fraction == pytest.approx(1.0)


def test_impact_profile_without_member_column_is_single_track() -> None:
    frame = make_frame([{"r34_ne": 100.0}]).drop(columns=["member"])
    stats = {s.threshold_kt: s for s in impact_profile(frame, lat=10.3, lon=130.3).thresholds}
    assert stats[34].total_members == 1
    assert stats[34].hit_members == 1


def test_impact_profile_missing_radius_columns_rejected() -> None:
    frame = make_frame([{"r34_ne": 100.0}]).drop(columns=[f"r64_{q}" for q in ("ne", "se", "sw", "nw")])
    with pytest.raises(ValueError, match="缺少风圈字段.*r64_ne"):
        impact_profile(frame, lat=10.0, lon=130.0)


def test_impact_profile_latitude_out_of_range_rejected() -> None:
    with pytest.raises(ValueError, match="目标纬度超出范围"):
        impact_profile(make_frame([{"r34_ne": 100.0}]), lat=100.0, lon=130.0)


def test_impact_profile_mixed_storm_or_init_rejected() -> None:
    with pytest.raises(ValueError, match="检测到多个 storm"):
        impact_profile(make_frame([{"storm": "A"}, {"storm": "B"}]), lat=10.0, lon=130.0)
    with pytest.raises(ValueError, match="检测到多个 init"):
        impact_profile(
            make_frame([{"init": pd.Timestamp("2026-10-15T18:00:00", tz="UTC")},
                        {"init": pd.Timestamp("2026-10-16T00:00:00", tz="UTC")}]),
            lat=10.0,
            lon=130.0,
        )


def test_impact_profile_all_positions_missing_no_closest() -> None:
    profile = impact_profile(make_frame([{"lat": None, "lon": None}]), lat=10.0, lon=130.0)
    assert profile.closest is None
    assert profile.closest_reason == "no_mean_position"
    assert all(s.hit_members == 0 for s in profile.thresholds)


def test_impact_profile_closest_approach_fields() -> None:
    frame = make_frame(
        [
            {"lead_h": 0.0, "lat": 10.0, "lon": 130.0, "wind": 40.0, "pressure": 990.0},
            {"lead_h": 24.0, "lat": 10.0, "lon": 132.0, "wind": 55.0, "pressure": 975.0},
        ]
    )
    closest = impact_profile(frame, lat=10.0, lon=131.0).closest
    assert closest is not None
    # 两时次对 (10,131) 等距 → 取最早时效 lead 0
    assert closest.lead_h == 0.0
    assert closest.valid == pd.Timestamp("2026-10-15T18:00:00", tz="UTC")
    assert closest.distance_km == pytest.approx(haversine_km(10.0, 131.0, 10.0, 130.0))
    assert closest.bearing_deg == pytest.approx(270.0, abs=0.2)  # 气旋在地点以西（大圆略偏）
    assert closest.compass == "W"
    assert closest.mean_wind == pytest.approx(40.0)
    assert closest.mean_pressure == pytest.approx(990.0)
    assert closest.mean_lat == pytest.approx(10.0)
    assert closest.mean_lon == pytest.approx(130.0)


def test_impact_profile_closest_approach_northeast_compass() -> None:
    frame = make_frame([{"lead_h": 0.0, "lat": 12.0, "lon": 132.0}])
    closest = impact_profile(frame, lat=10.0, lon=130.0).closest
    assert closest is not None
    assert closest.bearing_deg == pytest.approx(45.0, abs=0.75)  # 气旋在地点东北（大圆偏差）
    assert closest.compass == "NE"


# ---------- 最近接近截断口径（M11a：止于首个低分母时次之前） ----------


def test_impact_profile_closest_truncated_before_low_denominator_tail() -> None:
    # M11a 最小复现：4 成员 0/24/48h 全员在场（mean 在 10N），72h 起仅 m1 存活
    # （低分母尾段）且其位置贴近目标——无截断时最近接近为 72h/0km；修复后应回退
    # 到截断内最近时次（lead 0），与前端 mean 线（M5d-R1 起截断）同口径
    rows = [{"member": str(m), "lead_h": lead} for m in range(4) for lead in (0.0, 24.0, 48.0)]
    rows += [{"member": "0", "lead_h": lead, "lat": 15.0} for lead in (72.0, 96.0, 120.0)]
    profile = impact_profile(make_frame(rows), lat=15.0, lon=130.0)
    closest = profile.closest
    assert closest is not None
    assert closest.lead_h == 0.0
    assert closest.mean_lat == pytest.approx(10.0)
    assert closest.distance_km == pytest.approx(haversine_km(15.0, 130.0, 10.0, 130.0))
    assert closest.distance_km > 500.0  # 修复前为 72h/0km（低分母尾段均值中心）
    assert profile.closest_reason is None


def test_impact_profile_closest_all_low_denominator_returns_none() -> None:
    # 极端消散：首时次即低分母（lead 0 仅 1/4 在场）→ 截断内无时次可取 → None + 原因
    # （缺失保持缺失，不退回首时次）
    rows = [{"member": "0", "lead_h": 0.0, "lat": 15.0, "lon": 130.0}]
    rows += [{"member": str(m), "lead_h": 24.0, "lat": 15.0, "lon": 130.0} for m in range(1, 4)]
    profile = impact_profile(make_frame(rows), lat=15.0, lon=130.0)
    assert profile.closest is None
    assert profile.closest_reason == "truncated_empty"


def test_impact_profile_closest_positions_only_in_tail_truncated_empty() -> None:
    # 有效均值位置仅存在于低分母尾段：全程有位置但截断内时次均值位置缺失 → truncated_empty
    rows = [
        {"member": str(m), "lead_h": 0.0, "lat": None, "lon": None} for m in range(4)
    ] + [{"member": "0", "lead_h": 6.0, "lat": 15.0, "lon": 130.0}]
    profile = impact_profile(make_frame(rows), lat=15.0, lon=130.0)
    assert profile.closest is None
    assert profile.closest_reason == "truncated_empty"


def test_impact_profile_closest_single_member_untruncated() -> None:
    # 单成员轨迹 low_denominator 恒为 False（n_total=1）：不截断，最近接近可落在晚时效
    frame = make_frame(
        [
            {"lead_h": 0.0, "lat": 10.0, "lon": 130.0},
            {"lead_h": 72.0, "lat": 15.0, "lon": 130.0},
        ]
    )
    closest = impact_profile(frame, lat=15.0, lon=130.0).closest
    assert closest is not None
    assert closest.lead_h == 72.0
    assert closest.distance_km == pytest.approx(0.0, abs=1e-6)


# ---------- geo：compass_8（M15） ----------


def test_compass_8_sectors_and_boundaries() -> None:
    assert compass_8(0.0) == "N"
    assert compass_8(11.24) == "N"
    assert compass_8(22.5) == "NE"  # 分界归顺时针下一方位
    assert compass_8(45.0) == "NE"
    assert compass_8(67.5) == "E"
    assert compass_8(90.0) == "E"
    assert compass_8(112.5) == "SE"
    assert compass_8(157.5) == "S"
    assert compass_8(202.5) == "SW"
    assert compass_8(247.5) == "W"
    assert compass_8(292.5) == "NW"
    assert compass_8(337.5) == "N"
    assert compass_8(359.9) == "N"
    assert compass_8(360.0) == "N"


def test_compass_8_sector_order_constant() -> None:
    # 响应契约序：N 起顺时针固定 8 码（closest_bearing_cells 按此序展开）
    assert COMPASS_8_SECTORS == ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


# ---------- 成员级 CPA（M15：全程时次、一成员一点、并列取最早时效） ----------


def test_member_cpa_minimum_distance_and_earliest_lead_tie() -> None:
    # 成员 0 两时次对目标 (10,131) 镜像等距（130/132 经度）→ 并列取最早时效；
    # 更早行在文件序靠后也须胜出（排序键而非文件序）
    frame = make_frame(
        [
            {"member": "0", "lead_h": 24.0, "lat": 10.0, "lon": 132.0},
            {"member": "0", "lead_h": 0.0, "lat": 10.0, "lon": 130.0},
        ]
    )
    (entry,) = impact_profile(frame, lat=10.0, lon=131.0).members_closest
    assert entry.member == "0"
    assert entry.lead_h == 0.0
    assert entry.valid == pd.Timestamp("2026-10-15T18:00:00", tz="UTC")
    assert entry.distance_km == pytest.approx(haversine_km(10.0, 131.0, 10.0, 130.0))
    assert entry.bearing_deg == pytest.approx(270.0, abs=0.2)  # CPA 位置在目标以西
    assert entry.sector == "W"


def test_member_cpa_missing_lead_row_eligible() -> None:
    # lead 缺失的时次仍可参选（更近即胜，缺失保持缺失不臆造时效）
    frame = make_frame(
        [
            {"member": "0", "lead_h": None, "lat": 10.0, "lon": 130.5},
            {"member": "0", "lead_h": 24.0, "lat": 15.0, "lon": 135.0},
        ]
    )
    (entry,) = impact_profile(frame, lat=10.0, lon=130.0).members_closest
    assert entry.lead_h is None
    assert entry.distance_km == pytest.approx(haversine_km(10.0, 130.0, 10.0, 130.5))


def test_member_cpa_tie_prefers_row_with_lead_over_missing() -> None:
    # 等距并列：有实效的时次排在无时效时次之前（无时效视为最晚）
    frame = make_frame(
        [
            {"member": "0", "lead_h": None, "lat": 10.0, "lon": 130.0},
            {"member": "0", "lead_h": 24.0, "lat": 10.0, "lon": 132.0},
        ]
    )
    (entry,) = impact_profile(frame, lat=10.0, lon=131.0).members_closest
    assert entry.lead_h == 24.0


def test_member_cpa_full_lead_untruncated_vs_mean_closest_truncated() -> None:
    # M11a 低分母尾段复用：mean 最近接近截断于 48h（lead 0/~555 km），而成员 0 的
    # CPA 走全程时次口径——尾段 72h 贴目标（0 km）仍须计入（两口径并存不混淆）
    rows = [{"member": str(m), "lead_h": lead} for m in range(4) for lead in (0.0, 24.0, 48.0)]
    rows += [{"member": "0", "lead_h": lead, "lat": 15.0} for lead in (72.0, 96.0, 120.0)]
    profile = impact_profile(make_frame(rows), lat=15.0, lon=130.0)
    assert profile.closest is not None
    assert profile.closest.lead_h == 0.0  # mean 截断口径不变（回归保护）
    assert profile.closest.distance_km > 500.0
    by_member = {m.member: m for m in profile.members_closest}
    assert by_member["0"].distance_km == pytest.approx(0.0, abs=1e-6)  # 全程：尾段命中
    assert by_member["0"].lead_h == 72.0
    assert by_member["1"].distance_km == pytest.approx(haversine_km(15.0, 130.0, 10.0, 130.0))
    assert by_member["1"].sector == "S"  # CPA 位置在目标以南
    assert [b.hit_members for b in profile.closest_bands] == [1, 1, 1, 4]
    assert profile.closest_origin_members == 1  # 成员 0 正面穿越（< 30 km）
    assert profile.closest_beyond_members == 0
    cells = {(c.sector, c.radius_km): c.hit_members for c in profile.closest_cells}
    assert cells[("S", 800)] == 3  # 成员 1/2/3 ~555 km 落 (400,800] 环带
    assert sum(cells.values()) + profile.closest_origin_members == 4  # 守恒：格+原点=明细数


def test_member_cpa_wind_taken_from_cpa_row() -> None:
    # M15-R3：wind_kt 取被选中 CPA 行（距离最小行）的风速——非成员峰值风速行、
    # 非末行、非任何其它时次。目标 (10,130)：CPA 行 = lead 24（10.5, 130.0,
    # 45 kt）；lead 0 行风速 80（更高但更远）、lead 48 行 20（更远）
    frame = make_frame(
        [
            {"member": "0", "lead_h": 0.0, "lat": 12.0, "lon": 130.0, "wind": 80.0},
            {"member": "0", "lead_h": 24.0, "lat": 10.5, "lon": 130.0, "wind": 45.0},
            {"member": "0", "lead_h": 48.0, "lat": 13.0, "lon": 131.0, "wind": 20.0},
        ]
    )
    (entry,) = impact_profile(frame, lat=10.0, lon=130.0).members_closest
    assert entry.lead_h == 24.0  # CPA 行 = 距离最小行
    assert entry.distance_km == pytest.approx(haversine_km(10.0, 130.0, 10.5, 130.0))
    assert entry.wind_kt == pytest.approx(45.0)  # CPA 行风速，不串行


def test_member_cpa_wind_missing_stays_none() -> None:
    # M15-R3：CPA 行风速缺失 → None；帧整列无 wind 同样 None（缺失保持缺失，
    # 不臆造 0、不借用它行风速——lead 24 行 40 kt 不得串入 CPA 行）
    frame = make_frame(
        [
            {"member": "0", "lead_h": 0.0, "lat": 10.0, "lon": 130.0, "wind": None},
            {"member": "0", "lead_h": 24.0, "lat": 12.0, "lon": 131.0, "wind": 40.0},
        ]
    )
    (entry,) = impact_profile(frame, lat=10.0, lon=130.0).members_closest
    assert entry.distance_km == pytest.approx(0.0, abs=1e-6)  # CPA = lead 0 行
    assert entry.wind_kt is None
    (no_wind_entry,) = impact_profile(
        frame.drop(columns=["wind"]), lat=10.0, lon=130.0
    ).members_closest
    assert no_wind_entry.wind_kt is None  # 帧缺 wind 列同样 None


def test_closest_bands_cumulative_with_bit_exact_equality() -> None:
    # 成员 A 与目标重合（d=0.0，位级精确）与注入档位 0 比较：累积 ≤ 含等号
    # （若为严格 < 则 A 不命中）；成员 B ~1.1 km 不入 0 档
    frame = make_frame(
        [
            {"member": "A", "lat": 10.0, "lon": 130.0},
            {"member": "B", "lat": 10.01, "lon": 130.0},
        ]
    )
    profile = impact_profile(frame, lat=10.0, lon=130.0, radii=(0, 100), origin_radius_km=1.0)
    bands = {b.radius_km: b for b in profile.closest_bands}
    assert bands[0].hit_members == 1  # 仅 d=0（≤ 0 含等号）
    assert bands[0].total_members == 2
    assert bands[0].fraction == pytest.approx(0.5)
    assert bands[100].hit_members == 2


def test_closest_bands_monotonic_cells_order_and_sectors() -> None:
    # 三成员 150/300/500 km（扇区内部方位角，避开分界浮点）→ 累积单调 + 固定格序
    spec = {"A": (5.0, 150.0), "B": (50.0, 300.0), "C": (95.0, 500.0)}
    rows = []
    for member, (bearing, dist) in spec.items():
        point_lat, point_lon = destination_point(10.0, 130.0, bearing, dist)
        rows.append({"member": member, "lat": point_lat, "lon": point_lon})
    profile = impact_profile(make_frame(rows), lat=10.0, lon=130.0)
    assert [b.hit_members for b in profile.closest_bands] == [0, 1, 2, 3]
    assert {m.member: m.sector for m in profile.members_closest} == {"A": "N", "B": "NE", "C": "E"}
    assert [m.member for m in profile.members_closest] == ["A", "B", "C"]  # 距离升序
    assert [(c.sector, c.radius_km) for c in profile.closest_cells] == [
        (sector, radius) for sector in COMPASS_8_SECTORS for radius in (100, 200, 400, 800)
    ]
    cells = {(c.sector, c.radius_km): c.hit_members for c in profile.closest_cells}
    assert cells[("N", 100)] == 0
    assert cells[("N", 200)] == 1  # A 150 km 落 (100,200] 环带
    assert cells[("NE", 400)] == 1  # B 300 km
    assert cells[("E", 800)] == 1  # C 500 km
    assert sum(cells.values()) == 3
    assert profile.closest_origin_members == 0
    assert profile.closest_beyond_members == 0


def test_closest_origin_zone_and_beyond_members() -> None:
    # 正面穿越（<30 km）入原点区不入扇区格；环外（>800 km）不入任何档/格但留明细
    direct_lat, direct_lon = destination_point(10.0, 130.0, 300.0, 5.0)
    far_lat, far_lon = destination_point(10.0, 130.0, 120.0, 1200.0)
    frame = make_frame(
        [
            {"member": "D", "lat": direct_lat, "lon": direct_lon},
            {"member": "E", "lat": 10.0, "lon": 130.0},  # 与目标重合：原点区
            {"member": "F", "lat": far_lat, "lon": far_lon},
        ]
    )
    profile = impact_profile(frame, lat=10.0, lon=130.0)
    assert profile.closest_origin_members == 2
    assert profile.closest_beyond_members == 1
    assert [b.hit_members for b in profile.closest_bands] == [2, 2, 2, 2]  # D/E ≤100；F 环外不入档
    assert sum(c.hit_members for c in profile.closest_cells) == 0
    by_member = {m.member: m for m in profile.members_closest}
    assert by_member["E"].distance_km == pytest.approx(0.0, abs=1e-9)
    assert by_member["D"].sector == "NW"  # 方位 300°（原点区仍按方位角计算 sector）
    assert by_member["F"].distance_km == pytest.approx(1200.0, rel=1e-3)  # 环外仍在明细
    assert by_member["F"].sector == "SE"


def test_member_cpa_positionless_member_stays_in_denominator() -> None:
    # 全程无有效坐标的成员：留分母、永不命中、不出现在明细（与三级风速口径一致）
    frame = make_frame(
        [
            {"member": "A", "lat": 10.05, "lon": 130.05},  # ~7.8 km → 原点区
            {"member": "B", "lat": None, "lon": None},
        ]
    )
    profile = impact_profile(frame, lat=10.0, lon=130.0)
    assert [m.member for m in profile.members_closest] == ["A"]
    bands = {b.radius_km: b for b in profile.closest_bands}
    assert bands[100].hit_members == 1
    assert bands[100].total_members == 2
    assert bands[100].fraction == pytest.approx(0.5)
    assert profile.closest_origin_members == 1


# ---------- 真实数据抽核（WNV3 配对文件，缺失自动跳过） ----------


@pytest.fixture(scope="module")
def real_frame():
    if not REAL_ENSEMBLE.is_file():
        pytest.skip("WNV3 配对 CSV 未放入 demo_src，跳过真实数据抽核")
    df = read_csv(REAL_ENSEMBLE)
    return normalize(df, make_mapping(df.columns)).frame


@pytest.fixture(scope="module")
def real_storm_frame(real_frame):
    return filter_rows(real_frame, storm="EP202026")


def test_real_far_point_zero_probability(real_storm_frame) -> None:
    profile = impact_profile(real_storm_frame, lat=60.0, lon=100.0)
    assert all(s.fraction == 0.0 for s in profile.thresholds)
    assert profile.closest is not None
    assert profile.closest.distance_km > 1000.0


def test_real_member_gale_hit_by_constructed_point(real_storm_frame) -> None:
    first = filter_rows(real_storm_frame, member="0").sort_values("lead_h").iloc[0]
    radius = float(first["r34_ne"])
    assert radius > 0.0
    lat, lon = destination_point(float(first["lat"]), float(first["lon"]), 45.0, radius * 0.5)
    stats = {s.threshold_kt: s for s in impact_profile(real_storm_frame, lat=lat, lon=lon).thresholds}
    assert stats[34].hit_members >= 1  # 成员 0 的 lead 0 NE 象限内，必命中


def test_real_member_hurricane_hit_by_constructed_point(real_frame) -> None:
    # EP202026 全程无 64 kt 风圈（风暴较弱），按数据实况选取确有 r64_ne>0 的气旋
    with_wind64 = real_frame[real_frame["r64_ne"] > 0]
    assert not with_wind64.empty
    row = with_wind64.iloc[0]
    storm_frame = filter_rows(real_frame, storm=str(row["storm"]))
    lat, lon = destination_point(float(row["lat"]), float(row["lon"]), 45.0, float(row["r64_ne"]) * 0.5)
    stats = {s.threshold_kt: s for s in impact_profile(storm_frame, lat=lat, lon=lon).thresholds}
    assert stats[64].hit_members >= 1


def test_real_closest_at_lead0_mean_center(real_storm_frame) -> None:
    lead0 = ensemble_profile(real_storm_frame)[0]
    assert lead0.mean_lat is not None and lead0.mean_lon is not None
    closest = impact_profile(
        real_storm_frame, lat=lead0.mean_lat, lon=lead0.mean_lon
    ).closest
    assert closest is not None
    assert closest.lead_h == lead0.lead_h
    assert closest.distance_km == pytest.approx(0.0, abs=1e-6)


def _independent_haversine_km(lat_a: float, lon_a: float, lat_b: float, lon_b: float) -> float:
    """测试内独立球面距离实现（不复用 core.geo，规避同源盲区）。"""
    phi_a, phi_b = math.radians(lat_a), math.radians(lat_b)
    d_phi = math.radians(lat_b - lat_a)
    d_lam = math.radians(lon_b - lon_a)
    h = (
        math.sin(d_phi / 2.0) ** 2
        + math.cos(phi_a) * math.cos(phi_b) * math.sin(d_lam / 2.0) ** 2
    )
    return 2.0 * EARTH_RADIUS_KM * math.asin(math.sqrt(min(h, 1.0)))


def _independent_bearing_deg(lat_a: float, lon_a: float, lat_b: float, lon_b: float) -> float:
    """测试内独立初始方位角实现（正北 0°、顺时针 0–360°）。"""
    phi_a, phi_b = math.radians(lat_a), math.radians(lat_b)
    d_lam = math.radians(lon_b - lon_a)
    y = math.sin(d_lam) * math.cos(phi_b)
    x = math.cos(phi_a) * math.sin(phi_b) - math.sin(phi_a) * math.cos(phi_b) * math.cos(d_lam)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


_INDEPENDENT_SECTORS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


def _independent_compass_8(bearing_deg: float) -> str:
    return _INDEPENDENT_SECTORS[int(((bearing_deg % 360.0) + 22.5) // 45.0) % 8]


def test_real_member_cpa_independent_recomputation(real_storm_frame) -> None:
    # M15 独立复算：lead 0 均值位置东南 350 km 取确定性目标点，pandas 逐成员最小
    # 距离/方位 → 分档/扇区格/原点/环外计数全部独立重算，与 impact_profile 对照
    lead0 = ensemble_profile(real_storm_frame)[0]
    assert lead0.mean_lat is not None and lead0.mean_lon is not None
    target_lat, target_lon = destination_point(lead0.mean_lat, lead0.mean_lon, 135.0, 350.0)
    profile = impact_profile(real_storm_frame, lat=target_lat, lon=target_lon)

    best: dict[str, tuple[float, float, float, float]] = {}  # member -> (distance, lead, lat, lon)
    for record in real_storm_frame.to_dict("records"):
        lat_v, lon_v = record["lat"], record["lon"]
        if pd.isna(lat_v) or pd.isna(lon_v):
            continue
        distance = _independent_haversine_km(target_lat, target_lon, float(lat_v), float(lon_v))
        member = str(record["member"])
        current = best.get(member)
        if current is None or distance < current[0]:
            best[member] = (distance, float(record["lead_h"]), float(lat_v), float(lon_v))

    assert len(profile.members_closest) == len(best) == real_storm_frame["member"].nunique()
    for entry in profile.members_closest:
        independent_distance, _, _, _ = best[entry.member]
        assert entry.distance_km == pytest.approx(independent_distance, abs=1e-6), entry.member

    radii = (100, 200, 400, 800)
    independent_bands = [sum(1 for d, *_ in best.values() if d <= r) for r in radii]
    assert [b.hit_members for b in profile.closest_bands] == independent_bands
    assert all(b.total_members == len(best) for b in profile.closest_bands)

    # 扇区格独立重算：CPA 时次坐标 → 测试内方位/扇区公式 → 环带增量计数
    cells: dict[tuple[str, int], int] = {}
    for _member, (distance, _, cpa_lat, cpa_lon) in best.items():
        sector = _independent_compass_8(
            _independent_bearing_deg(target_lat, target_lon, cpa_lat, cpa_lon)
        )
        if distance < 30.0:
            continue  # 原点区不入格
        for prev, radius in zip((0, 100, 200, 400), radii, strict=True):
            if prev < distance <= radius:
                cells[(sector, radius)] = cells.get((sector, radius), 0) + 1
                break
    assert {
        (c.sector, c.radius_km): c.hit_members for c in profile.closest_cells if c.hit_members
    } == cells
    assert (
        sum(cells.values())
        + profile.closest_origin_members
        + profile.closest_beyond_members
        == len(best)
    )
    assert profile.closest_origin_members == sum(1 for d, *_ in best.values() if d < 30.0)
    assert profile.closest_beyond_members == sum(1 for d, *_ in best.values() if d > 800)
