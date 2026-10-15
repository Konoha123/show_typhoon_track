"""core：WNC 轨迹 CSV 解析核心层（纯函数，无打印、无 Web 依赖）。

解析语义与 demo_src/wnc_csv_demo.py 保持一致；该演示脚本是行为对照基准，
core 的错误文案沿用其原文（含 CLI 选项字样），以便对照验证字节级一致。
"""

from .aliases import ALIASES
from .geo import signed_longitude
from .io import make_mapping, read_csv
from .normalize import NormalizedResult, normalize, validate_track_table
from .selection import exact_filter, filter_rows, select_track
from .summary import (
    DatasetSummary,
    StormOverview,
    ri_changes,
    sorted_members,
    summarize_tracks,
)

__all__ = [
    "ALIASES",
    "DatasetSummary",
    "NormalizedResult",
    "StormOverview",
    "exact_filter",
    "filter_rows",
    "make_mapping",
    "normalize",
    "read_csv",
    "ri_changes",
    "select_track",
    "signed_longitude",
    "sorted_members",
    "summarize_tracks",
    "validate_track_table",
]
