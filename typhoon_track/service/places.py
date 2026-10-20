"""预存地点：根目录 places/places.csv 的热读取（每次请求现读，手工维护即时生效）。

契约（M6 规划 + M9 洋区扩展，已经用户确认）：
- 列 name,lat,lon,basin,note（note 可选；多余列忽略；'#' 注释行与 BOM 兼容，同 core.io）；
- name 唯一：重复名跳过后续行并报 warning（不静默覆盖）；
- lat/lon 十进制度：lat∈[−90,90]、lon∈[−180,180]，非数值或越界跳过该行并报 warning；
- basin 洋区码：合法值域 core.basin.BASIN_ORDER（8 码，M9）；缺失/非法码视为错误数据，
  跳过该行并报 warning；整表缺 basin 列 → 单条汇总 warning 且地点为空
  （区别于 name/lat/lon 缺列的配置错误 ValueError，向后显式暴露旧格式文件）；
- 文件缺失 → 空结果 + warning（前端降级为仅临时选点，不报错）；
- 文件存在但缺必要列/为空 → ValueError（配置错误显式暴露，api 层转 400）。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import pandas as pd

from typhoon_track.core.basin import BASIN_ORDER


@dataclass(frozen=True)
class Place:
    """单个预存地点。"""

    name: str
    lat: float
    lon: float
    basin: str
    note: str | None


@dataclass(frozen=True)
class PlacesResult:
    """一次读取结果：有效地点与逐行诊断（坏行跳过，不中断整体）。"""

    places: tuple[Place, ...]
    warnings: tuple[str, ...]
    available: bool  # 文件是否存在（存在但零有效行也为 True）


def _text(value: object) -> str:
    if value is None or bool(pd.isna(value)):
        return ""
    return str(value).strip()


def _to_float(value: object) -> float | None:
    converted = pd.to_numeric(pd.Series([value], dtype="object"), errors="coerce")
    series = cast("pd.Series", converted)
    first = series.iloc[0]
    if bool(pd.isna(first)):
        return None
    return float(first)


def load_places(path: str | Path) -> PlacesResult:
    path = Path(path)
    if not path.is_file():
        return PlacesResult((), (f"未找到预存地点文件 {path}; 仅可使用临时选点",), False)
    try:
        frame = pd.read_csv(path, dtype="string", encoding="utf-8-sig", comment="#")
    except pd.errors.EmptyDataError as exc:
        raise ValueError(f"预存地点文件为空: {path}") from exc
    frame.columns = [str(column).strip() for column in frame.columns]
    missing = [key for key in ("name", "lat", "lon") if key not in frame.columns]
    if missing:
        raise ValueError(f"{path} 缺少必要列: {', '.join(missing)}; 应为 name,lat,lon,basin[,note]")
    if "basin" not in frame.columns:
        return PlacesResult(
            (),
            (f"{path} 缺少 basin 列（M9 起必填），全部地点跳过; 应为 name,lat,lon,basin[,note]",),
            True,
        )

    records: list[dict[str, Any]] = frame.to_dict("records")
    warnings: list[str] = []
    if not records:
        warnings.append(f"预存地点文件没有数据行: {path}")
    places: list[Place] = []
    seen: set[str] = set()
    for line, record in enumerate(records, start=2):  # 行号按含表头的原文件计
        name = _text(record.get("name"))
        if not name:
            warnings.append(f"第 {line} 行 name 为空，跳过")
            continue
        if name in seen:
            warnings.append(f"第 {line} 行 name 重复: {name}，跳过（以首现为准）")
            continue
        lat = _to_float(record.get("lat"))
        lon = _to_float(record.get("lon"))
        if lat is None or lon is None:
            warnings.append(f"第 {line} 行 lat/lon 非数值（{name}），跳过")
            continue
        lat_value, lon_value = lat, lon
        if not -90.0 <= lat_value <= 90.0 or not -180.0 <= lon_value <= 180.0:
            warnings.append(
                f"第 {line} 行坐标越界（{name}: {lat_value},{lon_value}），跳过；"
                "应为 lat∈[-90,90]、lon∈[-180,180]"
            )
            continue
        basin = _text(record.get("basin")).upper()
        if basin not in BASIN_ORDER:
            warnings.append(
                f"第 {line} 行 basin 缺失或非法（{name}: {basin or '空'}），跳过；"
                f"合法值: {', '.join(BASIN_ORDER)}"
            )
            continue
        note = _text(record.get("note"))
        seen.add(name)
        places.append(
            Place(name=name, lat=lat_value, lon=lon_value, basin=basin, note=note or None)
        )
    return PlacesResult(tuple(places), tuple(warnings), True)
