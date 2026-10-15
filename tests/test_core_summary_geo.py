"""core.summary 与 core.geo：汇总统计与经度转换测试。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from typhoon_track.core import (
    make_mapping,
    normalize,
    read_csv,
    ri_changes,
    select_track,
    signed_longitude,
    sorted_members,
    summarize_tracks,
)

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "demo_src"
MEAN = DEMO / "sample_synthetic_ensemble_mean.csv"
MEMBERS = DEMO / "sample_synthetic_ensemble.csv"


def _frame(path: Path) -> pd.DataFrame:
    df = read_csv(path)
    return normalize(df, make_mapping(df.columns)).frame


def test_summarize_tracks_ensemble_structure() -> None:
    summary = summarize_tracks(_frame(MEMBERS))
    assert len(summary.storms) == 1
    overview = summary.storms[0]
    assert overview.storm == "SYN202601"
    assert overview.rows == 6
    assert overview.member_count == 2
    assert (overview.lead_min, overview.lead_max) == (0.0, 48.0)
    assert summary.members == ["01", "02"]


def test_summarize_tracks_without_member_column() -> None:
    summary = summarize_tracks(_frame(MEAN))
    assert summary.storms[0].member_count is None
    assert summary.members is None


def test_summarize_tracks_requires_storm() -> None:
    with pytest.raises(ValueError, match="无法列出气旋"):
        summarize_tracks(pd.DataFrame({"lat": [1.0]}))


def test_sorted_members_numeric_then_lexicographic_fallback() -> None:
    assert sorted_members(pd.Series(["10", "2", "1"])) == ["1", "2", "10"]
    assert sorted_members(pd.Series(["b", "a", "10", "2"])) == ["10", "2", "a", "b"]


def test_ri_changes_exact_24h_pairs_only() -> None:
    out = select_track(_frame(MEAN))
    joined = ri_changes(out)
    assert len(joined) == 4  # 0→24, 24→48, 48→72, 72→96
    assert joined["delta_kt_24h"].iloc[0] == 43  # 40 -> 83，按增量降序
    assert joined["delta_kt_24h"].is_monotonic_decreasing


def test_ri_changes_needs_wind_and_valid() -> None:
    assert ri_changes(pd.DataFrame({"wind": [10.0]})).empty


def test_signed_longitude_conversion() -> None:
    converted = signed_longitude(pd.Series([350.0, -10.0, 190.0, 0.0, 360.0, None]))
    assert converted.tolist()[:5] == [-10.0, -10.0, -170.0, 0.0, 0.0]
    assert pd.isna(converted.tolist()[5])
    # 幂等：已为负值时再转换不变
    again = signed_longitude(converted)
    assert again.tolist()[:5] == [-10.0, -10.0, -170.0, 0.0, 0.0]
