"""地理坐标工具（纯函数）。"""

from __future__ import annotations

import pandas as pd


def signed_longitude(lon: pd.Series) -> pd.Series:
    """0–360° 经度约定转换为 −180–180°；已为负值时幂等；缺失保持缺失。

    依据数据处理纪律第 3 条：两套经度约定不可未经转换直接比较。
    """
    values = pd.Series(pd.to_numeric(lon, errors="coerce"))
    return ((values + 180) % 360) - 180
