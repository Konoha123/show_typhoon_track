"""地理坐标工具（纯函数）。"""

from __future__ import annotations

import math

import pandas as pd

_EARTH_RADIUS_KM = 6371.0088
_DEG2RAD = math.pi / 180.0


def signed_longitude(lon: pd.Series) -> pd.Series:
    """0–360° 经度约定转换为 −180–180°；已为负值时幂等；缺失保持缺失。

    依据数据处理纪律第 3 条：两套经度约定不可未经转换直接比较。
    """
    values = pd.Series(pd.to_numeric(lon, errors="coerce"))
    return ((values + 180) % 360) - 180


def haversine_km(lat_a: float, lon_a: float, lat_b: float, lon_b: float) -> float:
    """两点球面大圆距离（km）；输入为度，经度 0–360° 与 −180–180° 两套约定结果一致。"""
    phi_a = lat_a * _DEG2RAD
    phi_b = lat_b * _DEG2RAD
    d_phi = (lat_b - lat_a) * _DEG2RAD
    d_lam = (lon_b - lon_a) * _DEG2RAD
    h = math.sin(d_phi / 2.0) ** 2 + math.cos(phi_a) * math.cos(phi_b) * math.sin(d_lam / 2.0) ** 2
    return 2.0 * _EARTH_RADIUS_KM * math.asin(math.sqrt(min(h, 1.0)))


def spherical_mean(lat: pd.Series, lon: pd.Series) -> tuple[float, float]:
    """球面意义的位置平均：经纬度转单位矢量求平均，再归一化回经纬度。

    经纬度成对缺失的行剔除；全部缺失时返回 (nan, nan)；
    矢量合成近零（成员位置接近对消）时抛 ValueError，不臆造平均位置。
    返回经度归入 −180–180°（跨 ±180° 的平均自然落在正确一侧）。

    口径已对官方 mean 产品 94/94 验证一致（docs/M5口径验证记录_20261016.md）。
    """
    la = pd.Series(pd.to_numeric(lat, errors="coerce"))
    lo = pd.Series(pd.to_numeric(lon, errors="coerce"))
    mask = la.notna() & lo.notna()
    if not bool(mask.any()):
        return float("nan"), float("nan")
    xs: list[float] = []
    ys: list[float] = []
    zs: list[float] = []
    for lat_v, lon_v in zip(la[mask].tolist(), lo[mask].tolist(), strict=True):
        phi = lat_v * _DEG2RAD
        lam = lon_v * _DEG2RAD
        xs.append(math.cos(phi) * math.cos(lam))
        ys.append(math.cos(phi) * math.sin(lam))
        zs.append(math.sin(phi))
    count = len(xs)
    x = sum(xs) / count
    y = sum(ys) / count
    z = sum(zs) / count
    norm = math.sqrt(x * x + y * y + z * z)
    if norm < 1e-12:
        raise ValueError("球面均值矢量合成近零（成员位置接近对消），无法定义平均位置")
    mean_lat = math.degrees(math.atan2(z, math.hypot(x, y)))
    mean_lon = math.degrees(math.atan2(y, x))
    return mean_lat, mean_lon
