"""轨迹查询：筛选（filter_rows 语义）+ 经度双约定 + 行级 JSON 载荷。"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from typhoon_track.core import filter_rows, signed_longitude


def track_rows(
    frame: pd.DataFrame,
    *,
    storm: str | None = None,
    member: str | None = None,
    init: str | None = None,
    model: str | None = None,
    source: str | None = None,
    max_lead_hours: float | None = None,
    at_lead_hours: float | None = None,
    lon_signed: bool = True,
) -> list[dict[str, Any]]:
    """按显式条件筛选并序列化为行字典列表（多值并存属调用方显式选择）。"""
    rows = filter_rows(
        frame,
        storm=storm,
        member=member,
        init=init,
        model=model,
        source=source,
        max_lead_hours=max_lead_hours,
        at_lead_hours=at_lead_hours,
    ).copy()
    if lon_signed and "lon" in rows:
        rows["lon_signed"] = signed_longitude(pd.Series(rows["lon"]))
    return [_jsonable_record(record) for record in rows.to_dict("records")]


def _jsonable_record(record: dict[str, object]) -> dict[str, Any]:
    return {str(key): _jsonable(value) for key, value in record.items()}


def _jsonable(value: object) -> Any:
    """缺失保持 None（不臆造 0）；时间转 ISO；numpy 标量转 Python 标量。"""
    if bool(pd.isna(value)):  # 记录值为标量；bool() 仅为类型层收口
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, np.generic):
        return value.item()
    return value
