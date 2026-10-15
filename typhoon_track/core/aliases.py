"""语义字段别名表：语义键 -> 可能的原始列名（大小写不敏感匹配）。

依据 google-deepmind/weathernext/cyclones/constants.py 与真实导出文件的
差异整理；风速/气压等带单位的字段仅在列名显式标注单位时才映射，绝不猜测。
"""

from __future__ import annotations

ALIASES: dict[str, list[str]] = {
    "storm": ["track_id", "storm_id", "cyclone_id", "sid", "atcf_id"],
    "name": ["storm_name", "cyclone_name", "name"],
    "init": [
        "init_time",
        "initialization_time",
        "forecast_datetime",
        "forecast_init_time",
        "initial_time",
    ],
    "valid": ["valid_time", "date_time", "datetime", "forecast_valid_time"],
    "lead": [
        "lead_time_hours",
        "lead_hours",
        "lead_time",
        "forecast_lead_time",
        "forecast_hour",
        "tau",
    ],
    "lat": ["lat", "latitude"],
    "lon": ["lon", "longitude"],
    "wind": [
        "maximum_sustained_wind_speed_knots",
        "max_sustained_wind_speed_knots",
        "vmax_kt",
        "vmax_knots",
        "wind_kt",
    ],
    "pressure": [
        "minimum_sea_level_pressure_hpa",
        "min_sea_level_pressure_hpa",
        "pmin_hpa",
        "mslp_hpa",
    ],
    "member": [
        "ensemble_member",
        "member",
        "sample",
        "member_id",
        "ensemble_member_id",
    ],
    "model": ["model", "model_name", "technique"],
    "source": ["source", "data_source", "track_type", "data_type"],
    "rmw": ["radius_of_maximum_winds_km", "rmw_km"],
    **{
        f"r{speed}_{quad}": [f"radius_{speed}_knot_winds_{quad}_km"]
        for speed in (34, 50, 64)
        for quad in ("ne", "se", "sw", "nw")
    },
}
