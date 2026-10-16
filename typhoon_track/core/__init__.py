"""core：WNC 轨迹 CSV 解析核心层（纯函数，无打印、无 Web 依赖）。

解析语义与 demo_src/wnc_csv_demo.py 保持一致；该演示脚本是行为对照基准，
core 的错误文案沿用其原文（含 CLI 选项字样），以便对照验证字节级一致。
"""

from .aliases import ALIASES
from .ensemble import (
    CATEGORY_STACK_BOTTOM_UP,
    DEFAULT_P_VALUES,
    DISSIPATED_COLOR,
    DISSIPATED_KEY,
    DISSIPATED_LABEL,
    LOW_DENOMINATOR_FRACTION,
    UNKNOWN_COLOR,
    UNKNOWN_KEY,
    WIND_CATEGORIES,
    LeadProfile,
    WindCategory,
    ensemble_profile,
    wind_category,
)
from .geo import haversine_km, signed_longitude, spherical_mean
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
    "CATEGORY_STACK_BOTTOM_UP",
    "DEFAULT_P_VALUES",
    "DatasetSummary",
    "DISSIPATED_COLOR",
    "DISSIPATED_KEY",
    "DISSIPATED_LABEL",
    "LOW_DENOMINATOR_FRACTION",
    "LeadProfile",
    "NormalizedResult",
    "StormOverview",
    "UNKNOWN_COLOR",
    "UNKNOWN_KEY",
    "WIND_CATEGORIES",
    "WindCategory",
    "ensemble_profile",
    "exact_filter",
    "filter_rows",
    "haversine_km",
    "make_mapping",
    "normalize",
    "read_csv",
    "ri_changes",
    "select_track",
    "signed_longitude",
    "sorted_members",
    "spherical_mean",
    "summarize_tracks",
    "validate_track_table",
    "wind_category",
]
