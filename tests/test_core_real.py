"""真实 Weather Lab 导出 CSV 的 core 级回归测试（文件缺失时自动跳过）。

对齐 demo_src/test_wnc_csv_real.py 的既有验收事实，原始文件保持原样。
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from typhoon_track.core import (
    filter_rows,
    make_mapping,
    normalize,
    read_csv,
    select_track,
    signed_longitude,
    summarize_tracks,
    validate_track_table,
)

REAL = Path(__file__).resolve().parents[1] / "demo_src" / "FNV3P2_2026_10_14T00_00_paired (1).csv"

pytestmark = pytest.mark.skipif(
    not REAL.is_file(), reason="原始 Weather Lab CSV 未放入 demo_src，跳过实测回归"
)


def _frame() -> pd.DataFrame:
    df = read_csv(REAL)
    return normalize(df, make_mapping(df.columns)).frame


def test_real_schema_and_normalization() -> None:
    df = read_csv(REAL)
    assert df.shape == (4592, 23)
    mapping = make_mapping(df.columns)
    assert mapping["lead"] == "lead_time_hours"
    assert mapping["member"] == "sample"
    out = normalize(df, mapping).frame
    validate_track_table(out)
    assert out["lead_h"].max() == 360
    assert out["storm"].nunique() == 4
    assert out["member"].nunique() == 50


def test_real_single_member_point_values() -> None:
    out = _frame()
    chosen = select_track(out, storm="EP202026", member="0", at_lead_hours=24)
    row = chosen.iloc[0]
    assert row["lat"] == pytest.approx(19.77)
    assert row["lon"] == pytest.approx(-108.44)
    assert row["wind"] == pytest.approx(57.4)
    assert row["pressure"] == pytest.approx(993.9)


def test_real_multi_member_rejected_in_select_track() -> None:
    with pytest.raises(ValueError, match="检测到多个 member"):
        select_track(_frame(), storm="EP202026")


def test_real_filter_rows_all_members_for_map() -> None:
    rows = filter_rows(_frame(), storm="WP962026")
    assert len(rows) == 2451  # 全部 50 个成员，供意面图渲染
    assert rows["member"].nunique() == 50


def test_real_summarize_tracks_counts() -> None:
    summary = summarize_tracks(_frame())
    counts = {s.storm: s.rows for s in summary.storms}
    assert counts == {
        "EP202026": 763,
        "EP212026": 1142,
        "WP282026": 236,
        "WP962026": 2451,
    }
    assert summary.members is not None
    assert summary.members[0] == "0"  # 数值序成员编号


def test_real_signed_longitude_for_western_storms() -> None:
    out = _frame()
    east = filter_rows(out, storm="EP202026")
    assert float(signed_longitude(pd.Series(east["lon"])).min()) < -100  # 幂等
