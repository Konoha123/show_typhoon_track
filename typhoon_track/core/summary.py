"""数据集结构与强度统计汇总（不跨成员混合统计）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import pandas as pd


@dataclass(frozen=True)
class StormOverview:
    """单个气旋在数据集内的行数、成员数与时效范围（非集合平均）。"""

    storm: str
    rows: int
    member_count: int | None  # None 表示无成员字段
    lead_min: float | None
    lead_max: float | None


@dataclass(frozen=True)
class DatasetSummary:
    """数据集级气旋概况；members 为排序后的全部成员编号（None 表示无成员字段）。"""

    storms: list[StormOverview]
    members: list[str] | None


def sorted_members(values: pd.Series) -> list[str]:
    """成员编号排序：可转 int 时按数值序，否则退回字典序。"""
    uniq = values.dropna().astype("string").unique().tolist()
    try:
        uniq.sort(key=lambda v: int(v))
    except ValueError:
        uniq.sort()
    return uniq


def summarize_tracks(out: pd.DataFrame) -> DatasetSummary:
    """按气旋汇总行数/成员数/时效范围；保留集合含义，不做任何均值。"""
    if "storm" not in out:
        raise ValueError("无法列出气旋：缺少 track_id，请 --inspect")
    storms: list[StormOverview] = []
    for storm, group in out.groupby("storm", sort=True, dropna=False):
        member_count = (
            int(cast("int", group["member"].nunique(dropna=True))) if "member" in group else None
        )
        lead_min: float | None = None
        lead_max: float | None = None
        if "lead_h" in group and bool(pd.Series(group["lead_h"]).notna().any()):
            lead_min = float(pd.Series(group["lead_h"]).min())
            lead_max = float(pd.Series(group["lead_h"]).max())
        storms.append(StormOverview(str(storm), len(group), member_count, lead_min, lead_max))
    members = sorted_members(pd.Series(out["member"])) if "member" in out else None
    return DatasetSummary(storms=storms, members=members)


def ri_changes(out: pd.DataFrame) -> pd.DataFrame:
    """仅计算恰好相隔 24 小时的风速差；不插值、不外推时间轴。"""
    if "wind" not in out or "valid" not in out:
        return pd.DataFrame()
    clean = out[["valid", "wind"]].dropna()
    if len(clean) < 2:
        return pd.DataFrame()
    prev = pd.DataFrame({"t0": clean["valid"], "v0": clean["wind"]})
    prev = prev.assign(t1=prev["t0"] + pd.Timedelta(hours=24))
    future = pd.DataFrame({"t1": clean["valid"], "v1": clean["wind"]})
    joined = prev.merge(future, on="t1", how="inner")
    if joined.empty:
        return joined
    joined["delta_kt_24h"] = joined["v1"] - joined["v0"]
    return joined.sort_values("delta_kt_24h", ascending=False)
