"""core.selection：纯筛选与严格单轨迹选取测试。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from typhoon_track.core import filter_rows, make_mapping, normalize, read_csv, select_track

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "demo_src"
MEAN = DEMO / "sample_synthetic_ensemble_mean.csv"
MEMBERS = DEMO / "sample_synthetic_ensemble.csv"


def _frame(path: Path) -> pd.DataFrame:
    df = read_csv(path)
    return normalize(df, make_mapping(df.columns)).frame


def test_select_track_requires_single_member() -> None:
    out = _frame(MEMBERS)
    with pytest.raises(ValueError, match="检测到多个 member"):
        select_track(out)
    chosen = select_track(out, member="01")
    assert len(chosen) == 3


def test_select_track_by_storm_ignores_case() -> None:
    out = _frame(MEAN)
    chosen = select_track(out, storm="syn202601")
    assert len(chosen) == 5


def test_select_track_unknown_storm_lists_hint() -> None:
    out = _frame(MEMBERS)
    with pytest.raises(ValueError, match="未找到气旋 'NOPE'"):
        select_track(out, storm="NOPE", member="01")


def test_member_filter_on_file_without_member_column() -> None:
    out = _frame(MEAN)
    with pytest.raises(ValueError, match="使用 --member 但 CSV 缺少相应字段"):
        select_track(out, member="01")


def test_init_filter_exact_match_only() -> None:
    out = _frame(MEMBERS)
    chosen = select_track(out, member="01", init="2026-07-01T00:00Z")
    assert len(chosen) == 3
    with pytest.raises(ValueError, match="没有匹配的行"):
        select_track(out, member="01", init="2026-07-02T00:00Z")


def test_mixed_init_rejected_for_forecast_allowed_for_observation(tmp_path: Path) -> None:
    p = tmp_path / "mixed_init.csv"
    pd.DataFrame({
        "track_id": ["T1", "T1"],
        "init_time": ["2026-07-01T00:00:00Z", "2026-07-02T00:00:00Z"],
        "valid_time": ["2026-07-01T06:00:00Z", "2026-07-02T06:00:00Z"],
        "lat": [10.0, 11.0], "lon": [130.0, 131.0],
        "vmax_kt": [40, 45],
    }).to_csv(p, index=False)
    out = _frame(p)
    with pytest.raises(ValueError, match="包含不同起报时间"):
        select_track(out, kind="forecast")
    assert len(select_track(out, kind="observation")) == 2


def test_at_lead_hours_matches_existing_only() -> None:
    out = _frame(MEAN)
    assert len(select_track(out, at_lead_hours=48)) == 1
    with pytest.raises(ValueError, match="筛选后没有数据"):
        select_track(out, at_lead_hours=49)  # 不插值到不存在的时效


def test_max_lead_hours_window() -> None:
    out = _frame(MEAN)
    assert len(select_track(out, max_lead_hours=24)) == 2


def test_lead_unresolvable_rejected(tmp_path: Path) -> None:
    p = tmp_path / "lead.csv"
    pd.DataFrame({"track_id": ["T1", "T1"], "lead_time": [0, 86400],
                  "vmax_kt": [30, 65]}).to_csv(p, index=False)
    out = _frame(p)
    with pytest.raises(ValueError, match="预报时效无法判定"):
        select_track(out, at_lead_hours=24)


def test_duplicate_valid_time_rejected(tmp_path: Path) -> None:
    df = read_csv(MEAN)
    pd.concat([df, df.head(1)], ignore_index=True).to_csv(
        tmp_path / "dup.csv", index=False)
    out = _frame(tmp_path / "dup.csv")
    with pytest.raises(ValueError, match="重复的 valid_time"):
        select_track(out)


def test_filter_rows_keeps_all_members_for_spaghetti_view() -> None:
    out = _frame(MEMBERS)
    rows = filter_rows(out, storm="SYN202601")
    assert len(rows) == 6  # 两个成员共存，不报混合错误
    assert rows["member"].nunique() == 2


def test_filter_rows_still_applies_explicit_filters() -> None:
    out = _frame(MEMBERS)
    rows = filter_rows(out, storm="SYN202601", member="02", max_lead_hours=24)
    assert len(rows) == 2
    with pytest.raises(ValueError, match="筛选后没有数据"):
        filter_rows(out, storm="SYN202601", at_lead_hours=49)
