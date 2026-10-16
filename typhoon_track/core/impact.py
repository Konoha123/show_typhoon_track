"""影响概率与最近接近（纯函数）。

口径（M6 规划，已经用户确认）：
- 判定：成员某时次使目标地点进入 x kt 风圈 ⟺ 地点相对气旋中心的方位落入某象限
  （NE∈[0°,90°)、SE∈[90°,180°)、SW∈[180°,270°)、NW∈[270°,360°)，按气旋中心→
  地点的大圆初始方位角），且 haversine 距离 ≤ 该象限 radius_{x}_knot_winds_{quad}_km；
- 风圈半径为 0.0（该级风不存在，ATCF 惯例）或缺失 → 该时次不命中；不臆造、不借用
  相邻象限（数据处理纪律第 5 条）；
- 成员在任一实际存在时次命中 ≥34/≥50/≥64 kt → 计入该阈值分子；只取实际存在时次，
  不插值、不外推（纪律第 7 条）；不跨气旋/起报时次混合（纪律第 6 条）；
- 分母 = 该 (storm, init) 下出现过的成员总数（与 M5 n_total 同口径）；
- 缺少任一风圈字段即显式拒绝，不提供纯距离回退（用户确认）；
- 最近接近采用 M5 自算逐时次均值位置（ensemble_profile，已 94/94 验证），
  并列等距取最早时效；方位角/16 方位为地点→气旋中心方向。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import pandas as pd

from .ensemble import _member_keys, _numeric_values, _validate_single_track, ensemble_profile
from .geo import compass_16, haversine_km, initial_bearing_deg

WIND_THRESHOLDS: tuple[int, ...] = (34, 50, 64)
_QUADRANTS: tuple[str, ...] = ("ne", "se", "sw", "nw")


@dataclass(frozen=True)
class ThresholdImpact:
    """单一风速阈值的成员命中统计。"""

    threshold_kt: int
    hit_members: int
    total_members: int
    fraction: float | None  # total_members 为 0 时为 None（缺失保持缺失，不臆造 0）


@dataclass(frozen=True)
class ClosestApproach:
    """mean 口径下目标地点对气旋的最近接近时次。"""

    lead_h: float
    valid: pd.Timestamp | None
    distance_km: float
    bearing_deg: float  # 地点→气旋中心方位角（正北 0°、顺时针 0–360°）
    compass: str  # 16 方位文字
    mean_wind: float | None
    mean_pressure: float | None
    mean_lat: float
    mean_lon: float


@dataclass(frozen=True)
class ImpactProfile:
    """目标地点的影响统计总载荷。"""

    thresholds: tuple[ThresholdImpact, ...]
    closest: ClosestApproach | None


def quadrant_of_bearing(bearing_deg: float) -> str:
    """方位角 → 风圈象限键（ne/se/sw/nw）；90° 奇数倍分界归顺时针下一象限。"""
    return _QUADRANTS[int((bearing_deg % 360.0) // 90.0)]


def point_in_wind_field(
    lat: float,
    lon: float,
    center_lat: float,
    center_lon: float,
    radii: dict[str, float | None],
) -> bool:
    """判定目标地点是否位于某时次气旋的风圈内。

    radii 为象限键 -> 半径 km 的映射；半径缺失或 ≤0 视为该象限无该级风（不命中）；
    距离恰等于半径判为命中（含等号）。经度两套约定均可（三角函数按周期自洽）。
    """
    bearing = initial_bearing_deg(center_lat, center_lon, lat, lon)
    radius = radii.get(quadrant_of_bearing(bearing))
    if radius is None or radius <= 0.0:
        return False
    return haversine_km(center_lat, center_lon, lat, lon) <= radius


def _to_float(value: object) -> float | None:
    numbers = _numeric_values([value])
    return numbers[0] if numbers else None


def impact_profile(
    frame: pd.DataFrame,
    *,
    lat: float,
    lon: float,
    thresholds: tuple[int, ...] = WIND_THRESHOLDS,
) -> ImpactProfile:
    """计算目标地点的三级影响概率与 mean 口径最近接近；输入为单一 (storm, init) 预报帧。

    帧应为 normalize 后的语义列（lat/lon/风圈列已数值化）；成员任一时次坐标缺失则
    该时次不参与判定（缺失保持缺失）。缺风圈列/纬度越界/跨气旋/跨起报均抛 ValueError。
    """
    _validate_single_track(frame)
    if not math.isfinite(lat) or not -90.0 <= lat <= 90.0:
        raise ValueError(f"目标纬度超出范围: {lat}; 应在 -90–90°（十进制度）")

    missing = [
        f"r{threshold}_{quadrant}"
        for threshold in thresholds
        for quadrant in _QUADRANTS
        if f"r{threshold}_{quadrant}" not in frame.columns
    ]
    if missing:
        raise ValueError(
            f"缺少风圈字段: {', '.join(missing)}; 无法计算影响概率（不提供距离回退）"
        )

    records: list[dict[str, Any]] = frame.to_dict("records")
    member_keys = _member_keys(frame)
    total = len(set(member_keys))
    hits: dict[int, set[str]] = {threshold: set() for threshold in thresholds}
    for record, member in zip(records, member_keys, strict=True):
        if all(member in hits[threshold] for threshold in thresholds):
            continue
        center_lat = _to_float(record.get("lat"))
        center_lon = _to_float(record.get("lon"))
        if center_lat is None or center_lon is None:
            continue
        for threshold in thresholds:
            if member in hits[threshold]:
                continue
            radii = {
                quadrant: _to_float(record.get(f"r{threshold}_{quadrant}"))
                for quadrant in _QUADRANTS
            }
            if point_in_wind_field(lat, lon, center_lat, center_lon, radii):
                hits[threshold].add(member)

    stats = tuple(
        ThresholdImpact(
            threshold_kt=threshold,
            hit_members=len(hits[threshold]),
            total_members=total,
            fraction=(len(hits[threshold]) / total) if total else None,
        )
        for threshold in thresholds
    )
    return ImpactProfile(thresholds=stats, closest=_closest_approach(frame, lat=lat, lon=lon))


def _closest_approach(frame: pd.DataFrame, *, lat: float, lon: float) -> ClosestApproach | None:
    """逐时次自算均值位置中离目标地点最近的时次（并列取最早时效；无有效位置为 None）。"""
    closest: ClosestApproach | None = None
    for profile in ensemble_profile(frame, p_values=(100,)):
        if profile.mean_lat is None or profile.mean_lon is None:
            continue
        distance = haversine_km(lat, lon, profile.mean_lat, profile.mean_lon)
        if closest is None or distance < closest.distance_km:
            bearing = initial_bearing_deg(lat, lon, profile.mean_lat, profile.mean_lon)
            closest = ClosestApproach(
                lead_h=profile.lead_h,
                valid=profile.valid,
                distance_km=distance,
                bearing_deg=bearing,
                compass=compass_16(bearing),
                mean_wind=profile.mean_wind,
                mean_pressure=profile.mean_pressure,
                mean_lat=profile.mean_lat,
                mean_lon=profile.mean_lon,
            )
    return closest
