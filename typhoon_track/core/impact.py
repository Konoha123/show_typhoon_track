"""影响概率与最近接近（纯函数）。

口径（M6 规划，已经用户确认；M7d 扩充核心强风区）：
- 判定：成员某时次使目标地点进入 x kt 风圈 ⟺ 地点相对气旋中心的方位落入某象限
  （NE∈[0°,90°)、SE∈[90°,180°)、SW∈[180°,270°)、NW∈[270°,360°)，按气旋中心→
  地点的大圆初始方位角），且 haversine 距离 ≤ 该象限 radius_{x}_knot_winds_{quad}_km；
- 风圈半径为 0.0（该级风不存在，ATCF 惯例）或缺失 → 该时次不命中；不臆造、不借用
  相邻象限（数据处理纪律第 5 条）；
- 成员在任一实际存在时次命中 ≥34/≥50/≥64 kt → 计入该阈值分子；只取实际存在时次，
  不插值、不外推（纪律第 7 条）；不跨气旋/起报时次混合（纪律第 6 条）；
- 核心强风区（M7d）：成员某时次使地点与气旋中心的 haversine 距离 ≤
  radius_of_maximum_winds_km（RMW，全向圆、无象限）→ 计入分子；RMW 缺失或 ≤0 的
  时次不命中（留在分母，缺失保持缺失）；真实导出与合成样本均含该列（M7 规划阶段
  已核实），不做运行时列探测，rmw 列整列缺失同样按全不命中处理；
- 分母 = 该 (storm, init) 下出现过的成员总数（与 M5 n_total 同口径）；
- 缺少任一风圈字段即显式拒绝，不提供纯距离回退（用户确认）；
- 最近接近采用 M5 自算逐时次均值位置（ensemble_profile，已 94/94 验证），
  并列等距取最早时效；方位角/16 方位为地点→气旋中心方向；
- 最近接近截断口径（M11a）：只在截断内时次中选取（effective_lead_profiles，
  止于首个低分母时次之前——与 M5d-R1 起前端 mean 线同口径）；截断内全程无有效
  均值位置时 closest 为 None 并以 closest_reason 区分原因（no_mean_position =
  全程无均值位置；truncated_empty = 截断内无时次可取），缺失保持缺失；
- 成员级 CPA（M15）：逐成员在**存在期全部输出行**（消散=行终止，无哨兵行，
  故全程=存在期；含 wind=0 行）中取中心到目标地点 haversine 距离的最小值，
  一成员一点；并列等距取最早时效（lead 缺失的时次仍可参选，仅并列排序视为
  最晚）；坐标缺失时次跳过，全程无有效坐标的成员留在分母、永不命中（与三级
  风速统计一致）；
- CPA 距离分档（M15）：累积口径「≤ radius_km」（含等号，与风圈/RMW 一致），
  档位 CLOSEST_DISTANCE_RADII（也是地图参考圆半径的单一事实来源）；分母 =
  成员总数（M5 n_total 同口径），total=0 时 fraction=None；
- CPA 方位分箱（M15）：地点→CPA 位置方位角按 compass_8 分 8 扇区（22.5° 奇数倍
  分界归顺时针下一方位）；格为 8 扇区 × 4 环带的增量语义（(prev, radius]），
  原点区（distance < CPA_ORIGIN_RADIUS_KM，正面穿越）不入扇区格、环外
  （> 最大档）不入任何格，两者单独计数；明细按 (distance, member) 升序。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal

import pandas as pd

from .ensemble import (
    _member_keys,
    _numeric_values,
    _validate_single_track,
    effective_lead_profiles,
    ensemble_profile,
)
from .geo import COMPASS_8_SECTORS, compass_8, compass_16, haversine_km, initial_bearing_deg

WIND_THRESHOLDS: tuple[int, ...] = (34, 50, 64)
_QUADRANTS: tuple[str, ...] = ("ne", "se", "sw", "nw")

# CPA 距离分档（累积 ≤，M15）：与地图参考圆半径共用档位（页面注入同一来源）
CLOSEST_DISTANCE_RADII: tuple[int, ...] = (100, 200, 400, 800)
# CPA 原点区阈值（正面穿越，M15）：小于该距离的成员方位角数值上任意，归原点语义
CPA_ORIGIN_RADIUS_KM: float = 30.0

# closest 为 None 时的不可用原因（M11a；全程均无有效均值位置 vs 截断内无时次可取）
ClosestUnavailableReason = Literal["no_mean_position", "truncated_empty"]


@dataclass(frozen=True)
class ThresholdImpact:
    """单一风速阈值的成员命中统计。"""

    threshold_kt: int
    hit_members: int
    total_members: int
    fraction: float | None  # total_members 为 0 时为 None（缺失保持缺失，不臆造 0）


@dataclass(frozen=True)
class CoreWindImpact:
    """核心强风区（距中心 ≤ RMW）的成员命中统计（M7d）。"""

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
class MemberClosest:
    """单成员 CPA（M15）：存在期全时次距目标的最小值（并列取最早时效）。"""

    member: str
    distance_km: float
    lead_h: float | None  # CPA 时次时效（帧缺 lead 列时为 None）
    valid: pd.Timestamp | None
    bearing_deg: float  # 地点→CPA 位置方位角（正北 0°、顺时针 0–360°）
    sector: str  # 8 方位码（compass_8；原点区成员按方位角照常计算，仅分箱归原点格）


@dataclass(frozen=True)
class DistanceBand:
    """CPA 距离分档累积统计（≤ radius_km，含等号；M15）。"""

    radius_km: int
    hit_members: int
    total_members: int
    fraction: float | None  # total_members 为 0 时为 None（缺失保持缺失）


@dataclass(frozen=True)
class BearingCell:
    """CPA 方位扇区 × 环带格计数（M15；环带增量语义 (prev, radius_km]）。

    原点区（< CPA_ORIGIN_RADIUS_KM）与环外（> 最大档）不入格，单独计数。
    """

    sector: str  # 8 方位码（COMPASS_8_SECTORS 固定序）
    radius_km: int
    hit_members: int


@dataclass(frozen=True)
class ImpactProfile:
    """目标地点的影响统计总载荷。"""

    thresholds: tuple[ThresholdImpact, ...]
    core_wind: CoreWindImpact
    closest: ClosestApproach | None
    # closest 为 None 时的原因（closest 非 None 时为 None；M11a）
    closest_reason: ClosestUnavailableReason | None = None
    # 成员级 CPA（M15）：按 (distance_km, member) 升序
    members_closest: tuple[MemberClosest, ...] = ()
    closest_bands: tuple[DistanceBand, ...] = ()
    closest_cells: tuple[BearingCell, ...] = ()
    closest_origin_members: int = 0
    closest_beyond_members: int = 0


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


def point_in_core_wind(
    lat: float,
    lon: float,
    center_lat: float,
    center_lon: float,
    rmw_km: float | None,
) -> bool:
    """判定目标地点是否进入某时次的核心强风区（M7d：距中心 ≤ RMW，全向圆无象限）。

    RMW 缺失或 ≤0 视为该时次无核心区数据（不命中，留在分母）；距离恰等于 RMW 判为
    命中（含等号，与风圈口径一致）。经度两套约定均可（三角函数按周期自洽）。
    """
    if rmw_km is None or rmw_km <= 0.0:
        return False
    return haversine_km(center_lat, center_lon, lat, lon) <= rmw_km


def _to_float(value: object) -> float | None:
    numbers = _numeric_values([value])
    return numbers[0] if numbers else None


def impact_profile(
    frame: pd.DataFrame,
    *,
    lat: float,
    lon: float,
    thresholds: tuple[int, ...] = WIND_THRESHOLDS,
    radii: tuple[int, ...] = CLOSEST_DISTANCE_RADII,
    origin_radius_km: float = CPA_ORIGIN_RADIUS_KM,
) -> ImpactProfile:
    """计算目标地点的三级影响概率、mean 口径最近接近与成员级 CPA 统计（M15）。

    输入为单一 (storm, init) 预报帧。帧应为 normalize 后的语义列（lat/lon/风圈列已
    数值化）；成员任一时次坐标缺失则该时次不参与判定（缺失保持缺失）。缺风圈列/
    纬度越界/跨气旋/跨起报均抛 ValueError。radii 与 origin_radius_km 可注入
    （默认单源常量），供测试精确断言等号与原点区边界。
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
    core_hits: set[str] = set()
    # 成员 CPA 候选：member -> (distance_km, lead 排序键, lead 原值, record)
    cpa_best: dict[str, tuple[float, float, float | None, dict[str, Any]]] = {}
    for record, member in zip(records, member_keys, strict=True):
        # CPA 累积须逐行进行（一成员一点：距离最小、并列最早时效），先于风圈命中的
        # 跳过优化——该优化只保证「已全命中的成员无需再看风圈」，不豁免 CPA 行
        _update_member_cpa(cpa_best, member, record, lat=lat, lon=lon)
        if member in core_hits and all(member in hits[threshold] for threshold in thresholds):
            continue
        center_lat = _to_float(record.get("lat"))
        center_lon = _to_float(record.get("lon"))
        if center_lat is None or center_lon is None:
            continue
        rmw = _to_float(record.get("rmw"))
        for threshold in thresholds:
            if member in hits[threshold]:
                continue
            radii_quadrant = {
                quadrant: _to_float(record.get(f"r{threshold}_{quadrant}"))
                for quadrant in _QUADRANTS
            }
            if point_in_wind_field(lat, lon, center_lat, center_lon, radii_quadrant):
                hits[threshold].add(member)
        if member not in core_hits and point_in_core_wind(lat, lon, center_lat, center_lon, rmw):
            core_hits.add(member)

    stats = tuple(
        ThresholdImpact(
            threshold_kt=threshold,
            hit_members=len(hits[threshold]),
            total_members=total,
            fraction=(len(hits[threshold]) / total) if total else None,
        )
        for threshold in thresholds
    )
    core_wind = CoreWindImpact(
        hit_members=len(core_hits),
        total_members=total,
        fraction=(len(core_hits) / total) if total else None,
    )
    closest, closest_reason = _closest_approach(frame, lat=lat, lon=lon)
    members_closest, bands, cells, origin_count, beyond_count = _member_cpa_stats(
        cpa_best, lat=lat, lon=lon, total=total, radii=radii,
        origin_radius_km=origin_radius_km,
    )
    return ImpactProfile(
        thresholds=stats,
        core_wind=core_wind,
        closest=closest,
        closest_reason=closest_reason,
        members_closest=members_closest,
        closest_bands=bands,
        closest_cells=cells,
        closest_origin_members=origin_count,
        closest_beyond_members=beyond_count,
    )


def _update_member_cpa(
    best: dict[str, tuple[float, float, float | None, dict[str, Any]]],
    member: str,
    record: dict[str, Any],
    *,
    lat: float,
    lon: float,
) -> None:
    """以 (distance, lead) 字典序更新成员 CPA 候选；坐标缺失时次跳过（M15）。"""
    center_lat = _to_float(record.get("lat"))
    center_lon = _to_float(record.get("lon"))
    if center_lat is None or center_lon is None:
        return
    distance = haversine_km(lat, lon, center_lat, center_lon)
    lead = _to_float(record.get("lead_h"))
    lead_key = math.inf if lead is None else lead
    current = best.get(member)
    if current is None or (distance, lead_key) < (current[0], current[1]):
        best[member] = (distance, lead_key, lead, record)


def _member_cpa_stats(
    best: dict[str, tuple[float, float, float | None, dict[str, Any]]],
    *,
    lat: float,
    lon: float,
    total: int,
    radii: tuple[int, ...],
    origin_radius_km: float,
) -> tuple[
    tuple[MemberClosest, ...],
    tuple[DistanceBand, ...],
    tuple[BearingCell, ...],
    int,
    int,
]:
    """由成员 CPA 候选聚合明细、距离分档与方位扇区格（M15 口径见模块 docstring）。"""
    # 明细：候选行必含坐标（_update_member_cpa 保证）；按 (distance, member) 升序
    members: list[MemberClosest] = []
    for member, (distance, _lead_key, lead, record) in best.items():
        center_lat = _to_float(record.get("lat"))
        center_lon = _to_float(record.get("lon"))
        if center_lat is None or center_lon is None:
            continue
        bearing = initial_bearing_deg(lat, lon, center_lat, center_lon)
        members.append(
            MemberClosest(
                member=member,
                distance_km=distance,
                lead_h=lead,
                valid=_timestamp_or_none(record.get("valid")),
                bearing_deg=bearing,
                sector=compass_8(bearing),
            )
        )
    members.sort(key=lambda m: (m.distance_km, m.member))

    # 距离分档：累积 ≤（含等号）
    band_stats: list[DistanceBand] = []
    for radius in radii:
        hit = sum(1 for m in members if m.distance_km <= radius)
        band_stats.append(
            DistanceBand(
                radius_km=radius,
                hit_members=hit,
                total_members=total,
                fraction=(hit / total) if total else None,
            )
        )

    # 方位扇区格：8 扇区固定序 × 环带增量 (prev, radius]；原点区/环外不入格
    max_radius = radii[-1]
    origin_count = sum(1 for m in members if m.distance_km < origin_radius_km)
    beyond_count = sum(1 for m in members if m.distance_km > max_radius)
    cells = tuple(
        BearingCell(
            sector=sector,
            radius_km=radius,
            hit_members=sum(
                1
                for m in members
                if m.sector == sector
                and m.distance_km >= origin_radius_km
                and (prev_radius < m.distance_km <= radius)
            ),
        )
        for sector in COMPASS_8_SECTORS
        for prev_radius, radius in zip((0, *radii[:-1]), radii, strict=True)
    )
    return tuple(members), tuple(band_stats), cells, origin_count, beyond_count


def _timestamp_or_none(value: object) -> pd.Timestamp | None:
    """valid 列取值归一：Timestamp 保留，其余（缺失/NaT/字符串残留）为 None。"""
    return value if isinstance(value, pd.Timestamp) else None


def _closest_approach(
    frame: pd.DataFrame, *, lat: float, lon: float
) -> tuple[ClosestApproach | None, ClosestUnavailableReason | None]:
    """截断内时次中离目标地点最近的自算均值位置时次（并列取最早时效）。

    M11a：只在 effective_lead_profiles（止于首个低分母时次之前）内选取；返回
    (最近接近, 不可用原因)——closest 非 None 时原因为 None，否则区分全程无均值
    位置（no_mean_position）与截断内无时次可取（truncated_empty）。
    """
    profiles = ensemble_profile(frame, p_values=(100,))
    has_position = any(
        profile.mean_lat is not None and profile.mean_lon is not None for profile in profiles
    )
    closest: ClosestApproach | None = None
    for profile in effective_lead_profiles(profiles):
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
    reason: ClosestUnavailableReason | None = None
    if closest is None:
        reason = "no_mean_position" if not has_position else "truncated_empty"
    return closest, reason
