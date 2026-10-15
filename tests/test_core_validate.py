"""core.normalize.validate_track_table：基本表校验测试。"""

from __future__ import annotations

from io import StringIO
from pathlib import Path

import pandas as pd
import pytest

from typhoon_track.core import make_mapping, normalize, read_csv, validate_track_table

ROOT = Path(__file__).resolve().parents[1]
MEAN = ROOT / "demo_src" / "sample_synthetic_ensemble_mean.csv"


def _normalized_frame(csv_text: str) -> pd.DataFrame:
    df = pd.read_csv(StringIO(csv_text), dtype="string")
    return normalize(df, make_mapping(df.columns)).frame


def test_valid_mean_table_passes() -> None:
    df = read_csv(MEAN)
    out = normalize(df, make_mapping(df.columns)).frame
    validate_track_table(out)


def test_missing_storm_id_rejected() -> None:
    out = _normalized_frame(
        "valid_time,lat,lon,vmax_kt\n2026-07-01T00:00:00Z,10.0,130.0,40\n")
    with pytest.raises(ValueError, match="缺少气旋编号"):
        validate_track_table(out)


def test_observation_kind_allows_name_only() -> None:
    out = _normalized_frame(
        "storm_name,valid_time,lat,lon,vmax_kt\nDEMO,2026-07-01T00:00:00Z,10.0,130.0,40\n")
    validate_track_table(out, kind="observation")
    with pytest.raises(ValueError, match="缺少气旋编号"):
        validate_track_table(out, kind="forecast")


def test_no_position_or_intensity_rejected() -> None:
    out = _normalized_frame("track_id,valid_time\nT1,2026-07-01T00:00:00Z\n")
    with pytest.raises(ValueError, match="没有识别到位置或强度字段"):
        validate_track_table(out)


def test_no_valid_time_or_lead_rejected() -> None:
    out = _normalized_frame("track_id,lat,lon\nT1,10.0,130.0\n")
    with pytest.raises(ValueError, match="缺少有效时刻或可解释的预报时效"):
        validate_track_table(out)


def test_all_invalid_lat_rejected() -> None:
    out = _normalized_frame(
        "track_id,valid_time,lat,lon,vmax_kt\nT1,2026-07-01T00:00:00Z,x,130.0,40\n")
    with pytest.raises(ValueError, match="lat 无有效数值"):
        validate_track_table(out)


def test_unparsed_valid_time_rejected() -> None:
    out = _normalized_frame(
        "track_id,valid_time,lat,lon,vmax_kt\nT1,not-a-time,10.0,130.0,40\n")
    with pytest.raises(ValueError, match="valid_time 无可解析"):
        validate_track_table(out)


def test_unknown_kind_rejected() -> None:
    df = read_csv(MEAN)
    out = normalize(df, make_mapping(df.columns)).frame
    with pytest.raises(ValueError, match="未知 kind"):
        validate_track_table(out, kind="bogus")
