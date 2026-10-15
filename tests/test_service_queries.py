"""service.queries：轨迹查询与行级序列化测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from typhoon_track.core import make_mapping, normalize, read_csv
from typhoon_track.service.queries import track_rows

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "demo_src"
MEAN = DEMO / "sample_synthetic_ensemble_mean.csv"
MEMBERS = DEMO / "sample_synthetic_ensemble.csv"


def _frame(path: Path):
    df = read_csv(path)
    return normalize(df, make_mapping(df.columns)).frame


def test_all_members_for_spaghetti_view():
    rows = track_rows(_frame(MEMBERS), storm="SYN202601")
    assert len(rows) == 6
    assert {r["member"] for r in rows} == {"01", "02"}


def test_member_filter_serialization_types():
    rows = track_rows(_frame(MEMBERS), member="01")
    first = rows[0]
    assert first["member"] == "01"  # 前导零保留
    assert first["valid"].startswith("2026-07-01T00:00:00")  # ISO 时间
    assert first["wind"] == 35  # 数值已转 Python 标量
    assert first["lon_signed"] == pytest.approx(first["lon"])  # 东经幂等


def test_missing_values_serialize_to_none():
    rows = track_rows(_frame(MEAN))
    assert rows[0]["r34_sw"] is None  # 缺失保持缺失，不臆造 0
    assert rows[4]["r34_sw"] == 130


def test_at_lead_filter_exact():
    rows = track_rows(_frame(MEAN), at_lead_hours=48)
    assert len(rows) == 1
    assert rows[0]["wind"] == 94


def test_no_match_raises_with_core_message():
    with pytest.raises(ValueError, match="未找到气旋"):
        track_rows(_frame(MEAN), storm="NOPE")
