"""core.io：CSV 读取与字段映射测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from typhoon_track.core import make_mapping, read_csv

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "demo_src"
MEAN = DEMO / "sample_synthetic_ensemble_mean.csv"
MEMBERS = DEMO / "sample_synthetic_ensemble.csv"


def test_read_csv_preserves_string_ids_and_skips_comments(tmp_path: Path) -> None:
    commented = tmp_path / "commented.csv"
    commented.write_text("# license\n# BEGIN DATA\n" + MEAN.read_text(encoding="utf-8"),
                         encoding="utf-8")
    df = read_csv(commented)
    assert len(df) == 5
    assert df["track_id"].tolist() == ["SYN202601"] * 5


def test_read_csv_keeps_member_leading_zero() -> None:
    df = read_csv(MEMBERS)
    assert sorted(df["ensemble_member"].tolist()) == ["01", "01", "01", "02", "02", "02"]


def test_read_csv_handles_bom(tmp_path: Path) -> None:
    bom_file = tmp_path / "bom.csv"
    bom_file.write_bytes(MEAN.read_bytes().replace(b"track_id", "\ufefftrack_id".encode()))
    df = read_csv(bom_file)
    assert df.columns[0] == "track_id"


def test_read_csv_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="文件不存在"):
        read_csv(tmp_path / "nope.csv")


def test_read_csv_duplicate_headers_mangled_by_pandas(tmp_path: Path) -> None:
    # pandas 读取时自动改名重复表头（与 demo 行为一致）；重复列守卫仅对
    # 程序内直接传入的真重复列 DataFrame 生效，此处确认改名后的表仍可读。
    dup = tmp_path / "dup.csv"
    dup.write_text("track_id,track_id,lat\nT1,T1,1.0\n", encoding="utf-8")
    df = read_csv(dup)
    assert list(df.columns) == ["track_id", "track_id.1", "lat"]


def test_read_csv_rejects_empty_table(tmp_path: Path) -> None:
    empty = tmp_path / "empty.csv"
    empty.write_text("track_id,lat\n", encoding="utf-8")
    with pytest.raises(ValueError, match="没有数据行"):
        read_csv(empty)


def test_make_mapping_alias_detection() -> None:
    df = read_csv(MEAN)
    mapping = make_mapping(df.columns)
    assert mapping["storm"] == "track_id"
    assert mapping["init"] == "init_time"
    assert mapping["valid"] == "valid_time"
    assert mapping["lead"] == "lead_time_hours"
    assert mapping["wind"] == "maximum_sustained_wind_speed_knots"
    assert mapping["pressure"] == "minimum_sea_level_pressure_hpa"
    assert mapping["r34_ne"] == "radius_34_knot_winds_ne_km"
    assert "member" not in mapping  # 均值样例无成员列


def test_make_mapping_member_prefers_ensemble_member_column() -> None:
    df = read_csv(MEMBERS)
    mapping = make_mapping(df.columns)
    assert mapping["member"] == "ensemble_member"


def test_make_mapping_override(tmp_path: Path) -> None:
    df = read_csv(MEAN)
    df.rename(columns={"maximum_sustained_wind_speed_knots": "MY_KNOTS"}).to_csv(
        tmp_path / "alt.csv", index=False)
    alt = read_csv(tmp_path / "alt.csv")
    mapping = make_mapping(alt.columns, overrides={"wind": "MY_KNOTS"})
    assert mapping["wind"] == "MY_KNOTS"


def test_make_mapping_override_unknown_key() -> None:
    df = read_csv(MEAN)
    with pytest.raises(ValueError, match="未知 KEY=bogus"):
        make_mapping(df.columns, overrides={"bogus": "track_id"})


def test_make_mapping_override_missing_header() -> None:
    df = read_csv(MEAN)
    with pytest.raises(ValueError, match="指定的原始列名不存在"):
        make_mapping(df.columns, overrides={"wind": "NOT_A_COLUMN"})
