"""core.basin：洋区码表与气旋编号前缀映射（M9）测试。

口径（见 docs/里程碑基线.md「M9」）：
- 地点侧码表 8 码固定顺序 NA/EP/CP/WP/NI/SI/SP/SA（IBTrACS 七分 + CP 扩展）；
- 气旋侧 track_id 前缀直映不合并：AL→NA、EP→EP、CP→CP、WP→WP、IO→NI、SH→SH；
- 未识别前缀（如 SYN）→ None；
- SH 为气旋侧粗码，不在地点码表 BASIN_ORDER 中（备用联动规则仅登记不实现）。

含 WNV3 配对真实数据前缀可识别性抽核（文件缺失自动跳过）。
"""

from __future__ import annotations

from pathlib import Path

from typhoon_track.core import (
    BASIN_NAMES,
    BASIN_ORDER,
    TRACK_ID_PREFIX_TO_BASIN,
    basin_from_track_id,
    basin_label,
)

DEMO = Path(__file__).resolve().parents[1] / "demo_src"
REAL_ENSEMBLE = DEMO / "WNV3_2026_10_15T18_00_paired_ensemble.csv"


# ---------- 码表 ----------


def test_catalog_order_and_names() -> None:
    # 地点码表固定 8 码：IBTrACS 七分 + CP 扩展；顺序为 UI 复选框显示顺序
    assert BASIN_ORDER == ("NA", "EP", "CP", "WP", "NI", "SI", "SP", "SA")
    for code in BASIN_ORDER:
        assert code in BASIN_NAMES
    # SH 为气旋侧粗码：有显示名、不在地点码表
    assert BASIN_NAMES["SH"] == "南半球"
    assert "SH" not in BASIN_ORDER


def test_prefix_map_values_are_known_labels() -> None:
    # 前缀直映表：值域 = 地点 8 码 + SH；SH 无对应地点码（不合并消歧）
    assert set(TRACK_ID_PREFIX_TO_BASIN) == {"AL", "EP", "CP", "WP", "IO", "SH"}
    # 值域不含 SI/SP/SA：南半球细分（SH→SI/SP）需坐标消歧，已确认不做
    assert set(TRACK_ID_PREFIX_TO_BASIN.values()) == (set(BASIN_ORDER) - {"SI", "SP", "SA"}) | {"SH"}


def test_basin_label_format() -> None:
    assert basin_label("WP") == "WP 西北太平洋"
    assert basin_label("SH") == "SH 南半球"
    assert basin_label("XX") == "XX"  # 未知代码原样返回，不臆造名称


# ---------- 前缀直映 ----------


def test_prefix_direct_mapping_matrix() -> None:
    # ATCF 编号格式：2 字母洋区码 + 2 位序号 + 4 位年份（如 EP202026 = EP 2026 年第 20 号）
    cases = {
        "AL092026": "NA",
        "EP202026": "EP",  # 与真实配对文件一致
        "CP012026": "CP",
        "WP292026": "WP",  # 与真实配对文件一致
        "IO052026": "NI",
        "SH112026": "SH",
    }
    for track_id, expected in cases.items():
        assert basin_from_track_id(track_id) == expected


def test_unrecognized_prefix_returns_none() -> None:
    # 合成数据 SYN 不在 ATCF 码表；空串/None/长度不足同样无洋区
    assert basin_from_track_id("SYN202601") is None
    assert basin_from_track_id("") is None
    assert basin_from_track_id(None) is None
    assert basin_from_track_id("E") is None
    assert basin_from_track_id("X92026") is None


def test_whitespace_and_case_normalized() -> None:
    assert basin_from_track_id("  ep202026 ") == "EP"
    assert basin_from_track_id("wp292026") == "WP"


# ---------- 真实数据抽核（缺文件自动跳过） ----------


def test_real_wnv3_track_ids_all_recognized() -> None:
    # WNV3 配对真实文件的 track_id 前缀应全部可识别且等于前 2 字符直映结果
    import pandas as pd

    if not REAL_ENSEMBLE.exists():
        import pytest

        pytest.skip(f"真实数据缺失：{REAL_ENSEMBLE}")
    frame = pd.read_csv(REAL_ENSEMBLE, dtype="string", comment="#")
    track_ids = sorted(frame["track_id"].dropna().unique().tolist())
    assert track_ids, "真实文件应含 track_id"
    for track_id in track_ids:
        assert basin_from_track_id(track_id) == TRACK_ID_PREFIX_TO_BASIN[track_id[:2].upper()]
