"""core：WNC 轨迹 CSV 解析核心层（纯函数，无打印、无 Web 依赖）。

解析语义与 demo_src/wnc_csv_demo.py 保持一致；该演示脚本是行为对照基准，
core 的错误文案沿用其原文（含 CLI 选项字样），以便对照验证字节级一致。
"""

from .aliases import ALIASES
from .basin import (
    BASIN_NAMES,
    BASIN_ORDER,
    TRACK_ID_PREFIX_TO_BASIN,
    basin_from_track_id,
    basin_label,
)
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
    MemberPeak,
    PeakMetricStats,
    PeakProfile,
    WindCategory,
    effective_lead_profiles,
    ensemble_profile,
    low_denominator_cut_lead,
    peak_profile,
    wind_category,
)
from .geo import (
    compass_16,
    haversine_km,
    initial_bearing_deg,
    signed_longitude,
    spherical_mean,
)
from .impact import (
    WIND_THRESHOLDS,
    ClosestApproach,
    CoreWindImpact,
    ImpactProfile,
    ThresholdImpact,
    impact_profile,
    point_in_core_wind,
    point_in_wind_field,
    quadrant_of_bearing,
)
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
    "BASIN_NAMES",
    "BASIN_ORDER",
    "CATEGORY_STACK_BOTTOM_UP",
    "ClosestApproach",
    "CoreWindImpact",
    "DEFAULT_P_VALUES",
    "DatasetSummary",
    "DISSIPATED_COLOR",
    "DISSIPATED_KEY",
    "DISSIPATED_LABEL",
    "ImpactProfile",
    "LOW_DENOMINATOR_FRACTION",
    "LeadProfile",
    "MemberPeak",
    "NormalizedResult",
    "PeakMetricStats",
    "PeakProfile",
    "StormOverview",
    "ThresholdImpact",
    "TRACK_ID_PREFIX_TO_BASIN",
    "UNKNOWN_COLOR",
    "UNKNOWN_KEY",
    "WIND_CATEGORIES",
    "WIND_THRESHOLDS",
    "WindCategory",
    "basin_from_track_id",
    "basin_label",
    "compass_16",
    "effective_lead_profiles",
    "ensemble_profile",
    "exact_filter",
    "filter_rows",
    "haversine_km",
    "impact_profile",
    "initial_bearing_deg",
    "low_denominator_cut_lead",
    "make_mapping",
    "normalize",
    "peak_profile",
    "point_in_core_wind",
    "point_in_wind_field",
    "quadrant_of_bearing",
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
