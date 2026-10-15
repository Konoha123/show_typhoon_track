"""core.normalize：类型解析与预报时效判定测试。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from typhoon_track.core import make_mapping, normalize, read_csv

ROOT = Path(__file__).resolve().parents[1]
MEAN = ROOT / "demo_src" / "sample_synthetic_ensemble_mean.csv"


def _normalize(csv: Path | pd.DataFrame, lead_unit: str | None = None):
    df = read_csv(csv) if isinstance(csv, Path) else csv
    return normalize(df, make_mapping(df.columns), lead_unit)


def test_lead_computed_from_timestamps_and_cross_checked() -> None:
    result = _normalize(MEAN)
    assert result.warnings == []
    out = result.frame
    assert out["lead_h"].tolist() == [0.0, 24.0, 48.0, 72.0, 96.0]
    assert out["wind"].tolist() == [40, 83, 94, 88, 80]
    assert out["valid"].dt.tz is not None  # UTC 解析


def test_declared_hours_must_match_timestamps(tmp_path: Path) -> None:
    df = read_csv(MEAN)
    df.loc[df.index[-1], "lead_time_hours"] = "99"
    bad = tmp_path / "bad.csv"
    df.to_csv(bad, index=False)
    with pytest.raises(ValueError, match="不一致"):
        _normalize(bad)


def test_declared_hours_non_numeric_rejected(tmp_path: Path) -> None:
    df = read_csv(MEAN)
    df.loc[df.index[0], "lead_time_hours"] = "abc"
    bad = tmp_path / "bad2.csv"
    df.to_csv(bad, index=False)
    with pytest.raises(ValueError, match="含非数值数据"):
        _normalize(bad)


def test_numeric_lead_without_unit_warns_and_keeps_missing(tmp_path: Path) -> None:
    p = tmp_path / "lead.csv"
    pd.DataFrame({"track_id": ["T1", "T1"], "lead_time": [0, 86400],
                  "vmax_kt": [30, 65]}).to_csv(p, index=False)
    result = _normalize(p)
    assert any("lead_time 是数值" in w for w in result.warnings)
    assert "lead_h" not in result.frame


def test_numeric_lead_with_seconds_unit(tmp_path: Path) -> None:
    p = tmp_path / "lead.csv"
    pd.DataFrame({"track_id": ["T1", "T1"], "lead_time": [0, 86400],
                  "vmax_kt": [30, 65]}).to_csv(p, index=False)
    result = _normalize(p, lead_unit="seconds")
    assert result.frame["lead_h"].tolist() == [0.0, 24.0]


def test_timedelta_style_lead(tmp_path: Path) -> None:
    p = tmp_path / "delta.csv"
    pd.DataFrame({"track_id": ["T1", "T1"], "lead_time": ["0h", "24h"],
                  "vmax_kt": [30, 65]}).to_csv(p, index=False)
    result = _normalize(p)
    assert result.warnings == []
    assert result.frame["lead_h"].tolist() == [0.0, 24.0]


def test_missing_values_stay_missing_not_zero() -> None:
    out = _normalize(MEAN).frame
    assert pd.isna(out["r34_sw"].iloc[0])  # 首行 SW 风圈缺失
    assert out["r34_sw"].iloc[-1] == 130  # 其余行保持原值，未被 0 填充


def test_declared_hours_used_when_no_timestamps(tmp_path: Path) -> None:
    p = tmp_path / "hours_only.csv"
    pd.DataFrame({"track_id": ["T1", "T1"], "lead_time_hours": [0, 12],
                  "vmax_kt": [30, 40]}).to_csv(p, index=False)
    out = _normalize(p).frame
    assert out["lead_h"].tolist() == [0.0, 12.0]
    assert np.isclose(out["wind"].iloc[1], 40)
