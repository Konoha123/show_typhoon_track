"""集合概率特征：逐时次的成员均值、位置概率半径与强度分布（纯函数）。

口径依据 docs/M5口径验证记录_20261016.md（与官方 mean 产品 94/94 验证一致）：
- 强度量（风速/气压）= 该时次在场成员的算术平均；
- 平均位置 = 球面矢量平均（core.geo.spherical_mean）；
- 尾部方案 b：仅统计该时次在场的成员，分母 n 逐时次暴露，不隐藏样本量衰减；
  消散数 = 该轨迹成员总数 − 该时次在场数；
- 概率半径 = 覆盖离平均位置最近 p% 成员的最小 haversine 半径；
- 只取实际存在的时次（不插值、不外推）；不跨气旋/成员/起报时次混合统计。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import cast

import pandas as pd

from .geo import haversine_km, spherical_mean


@dataclass(frozen=True)
class WindCategory:
    """强度分级（阈值与配色与 web 端强度图例保持一致，1 分钟平均，按数据提供口径）。"""

    key: str
    label: str
    min_kt: float  # 下限（含）；TD 用 -inf
    color: str


WIND_CATEGORIES: tuple[WindCategory, ...] = (
    WindCategory("H5", "≥137 kt（H5）", 137, "#9d4edd"),
    WindCategory("H4", "113–136 kt（H4）", 113, "#d62828"),
    WindCategory("H3", "96–112 kt（H3）", 96, "#ef767a"),
    WindCategory("H2", "83–95 kt（H2）", 83, "#f4a261"),
    WindCategory("H1", "64–82 kt（H1）", 64, "#ffd166"),
    WindCategory("TS", "34–63 kt（TS）", 34, "#66c2a5"),
    WindCategory("TD", "<34 kt（TD）", -math.inf, "#6fb7e0"),
)
DISSIPATED_KEY = "DISSIPATED"
UNKNOWN_KEY = "UNKNOWN"  # 在场但风速缺失的成员（缺失保持缺失，不并入任何等级）
DISSIPATED_LABEL = "已消散"
DISSIPATED_COLOR = "#9ca3af"
UNKNOWN_COLOR = "#888888"
# 堆叠图自底向上的层级：强度向上单调递增，已消散仅在底部与 TD 相邻，H5 仅与 H4 相邻
CATEGORY_STACK_BOTTOM_UP: tuple[str, ...] = (
    DISSIPATED_KEY, "TD", "TS", "H1", "H2", "H3", "H4", "H5",
)
DEFAULT_P_VALUES: tuple[int, ...] = (40, 50, 60, 70, 80, 90, 100)
LOW_DENOMINATOR_FRACTION = 0.3  # n_present < 30% × n_total 时标记低分母（视觉降权，不删数据）


def wind_category(kt: float) -> WindCategory:
    """按风速返回所属强度等级（下限含）。"""
    for category in WIND_CATEGORIES:
        if kt >= category.min_kt:
            return category
    return WIND_CATEGORIES[-1]


@dataclass(frozen=True)
class LeadProfile:
    """单个预报时效的集合统计。"""

    lead_h: float
    valid: pd.Timestamp | None
    n_total: int  # 该轨迹出现过的成员总数
    n_present: int  # 该时次在场（仍输出该气旋）的成员数
    mean_wind: float | None
    mean_pressure: float | None
    mean_lat: float | None
    mean_lon: float | None
    radius_km: dict[int, float | None]  # p(%) -> 覆盖最近 p% 成员的最小半径
    category_counts: dict[str, int]  # 各强度等级成员数 + DISSIPATED（+ UNKNOWN 若有）
    low_denominator: bool  # n_present < LOW_DENOMINATOR_FRACTION × n_total


def _column_values(group: pd.DataFrame, key: str) -> list[object]:
    """取一列的原始值列表（列缺失时为空列表），供逐值类型安全处理。"""
    if key not in group.columns:
        return []
    return list(group[key].tolist())


def _is_missing(value: object) -> bool:
    """标量缺失判定；bool() 仅为类型层收口 pandas 联合返回（同 service.queries 先例）。"""
    return bool(pd.isna(value))


def _numeric_series(values: list[object]) -> pd.Series:
    """对象值列表 -> 浮点 Series（不可转换的非数值按缺失处理，缺失保持缺失）。"""
    converted = pd.to_numeric(pd.Series(values, dtype="object"), errors="coerce")
    return cast("pd.Series", converted)


def _numeric_values(values: list[object]) -> list[float]:
    """剔除缺失后的数值列表。"""
    converted = _numeric_series(values)
    return [float(v) for v in converted.dropna().tolist()]


def _member_keys(frame: pd.DataFrame) -> list[str]:
    """成员标识列表；无成员字段时视作单一轨迹（全部行同一伪成员）。"""
    values = _column_values(frame, "member") or ["—"] * len(frame)
    return ["—" if _is_missing(v) else str(v) for v in values]


def _validate_single_track(frame: pd.DataFrame) -> None:
    """拒绝跨气旋/起报时次的混合统计（调用方负责 storm/init 筛选，此处兜底校验）。"""
    storms = sorted({str(v) for v in _column_values(frame, "storm") if not _is_missing(v)})
    if len(storms) > 1:
        preview = ", ".join(storms[:15])
        raise ValueError(f"检测到多个 storm：{preview}。不跨气旋混合统计，请先筛选。")
    inits = [v for v in _column_values(frame, "init") if not _is_missing(v)]
    if len({str(v) for v in inits}) > 1:
        preview = ", ".join(str(v) for v in inits[:15])
        raise ValueError(f"检测到多个 init：{preview}。不跨起报时次混合统计，请先筛选。")


def _radius_quantile(distances: list[float], p: int) -> float:
    """覆盖离中心最近 p% 成员的最小半径：升序取第 ceil(p%·n) 个（p=100 即最大距离）。"""
    ordered = sorted(distances)
    rank = max(1, math.ceil(p / 100 * len(ordered)))
    return ordered[rank - 1]


def ensemble_profile(
    frame: pd.DataFrame, *, p_values: tuple[int, ...] = DEFAULT_P_VALUES
) -> list[LeadProfile]:
    """按实际存在的时效逐档计算集合统计；输入应为单一 (storm, init) 的预报帧。

    分母口径：n_total = 该轨迹出现过的成员总数；n_present = 该时次在场的成员数；
    位置类统计仅计入该时次有坐标的成员（坐标缺失保持缺失，不充当 0）。
    """
    _validate_single_track(frame)
    if "lead_h" not in frame.columns:
        raise ValueError("缺少预报时效 lead_h，无法按时效聚合；请检查 init+valid 或 lead 字段")

    member_keys = _member_keys(frame)
    n_total = len(set(member_keys))
    profiles: list[LeadProfile] = []
    for lead, group in frame.groupby("lead_h", sort=True):
        if _is_missing(lead):
            continue
        lead_value = float(cast("float", lead))

        members = ["—" if _is_missing(v) else str(v) for v in _column_values(group, "member")] or ["—"]
        counts: dict[str, int] = {}
        for member in members:
            counts[member] = counts.get(member, 0) + 1
        duplicated = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        member, count = duplicated[0]
        if count > 1:
            raise ValueError(
                f"成员 {member} 在时效 {lead_value} h 重复出现 {count} 行，拒绝静默去重，请先调查数据"
            )
        n_present = len(counts)

        valid: pd.Timestamp | None = None
        for value in _column_values(group, "valid"):
            if isinstance(value, pd.Timestamp):
                valid = value
                break

        winds = _numeric_values(_column_values(group, "wind"))
        mean_wind = sum(winds) / len(winds) if winds else None
        pressures = _numeric_values(_column_values(group, "pressure"))
        mean_pressure = sum(pressures) / len(pressures) if pressures else None

        positions: list[tuple[float, float]] = []
        lat_converted = _numeric_series(_column_values(group, "lat"))
        lon_converted = _numeric_series(_column_values(group, "lon"))
        for lat_v, lon_v in zip(lat_converted.tolist(), lon_converted.tolist(), strict=True):
            if _is_missing(lat_v) or _is_missing(lon_v):
                continue
            positions.append((float(lat_v), float(lon_v)))

        if positions:
            mean_lat, mean_lon = spherical_mean(
                pd.Series([lat for lat, _ in positions]),
                pd.Series([lon for _, lon in positions]),
            )
            distances = [haversine_km(mean_lat, mean_lon, lat, lon) for lat, lon in positions]
            radius_km: dict[int, float | None] = {p: _radius_quantile(distances, p) for p in p_values}
        else:
            mean_lat, mean_lon = float("nan"), float("nan")
            radius_km = {p: None for p in p_values}

        category_counts = {key: 0 for key in CATEGORY_STACK_BOTTOM_UP}
        wind_values = _column_values(group, "wind")
        for value in wind_values:
            numbers = _numeric_values([value])
            if not numbers:
                category_counts[UNKNOWN_KEY] = category_counts.get(UNKNOWN_KEY, 0) + 1
            else:
                category_counts[wind_category(numbers[0]).key] += 1
        category_counts[DISSIPATED_KEY] = n_total - n_present

        low_denominator = n_total > 1 and n_present < LOW_DENOMINATOR_FRACTION * n_total
        profiles.append(
            LeadProfile(
                lead_h=lead_value,
                valid=valid,
                n_total=n_total,
                n_present=n_present,
                mean_wind=mean_wind,
                mean_pressure=mean_pressure,
                mean_lat=None if math.isnan(mean_lat) else mean_lat,
                mean_lon=None if math.isnan(mean_lon) else mean_lon,
                radius_km=radius_km,
                category_counts=category_counts,
                low_denominator=low_denominator,
            )
        )
    return profiles
