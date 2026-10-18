"""core.ensemble.peak_profile：成员终生峰值（M8）测试。

口径（见 docs/里程碑基线.md「M8」）：
- 终生最大风速 = wind 逐行 max；终生最低气压 = pressure 逐行 min；独立取极值、各报出现时效；
- 出现时效并列取最早（M6 最近接近同款先例）；
- 上中位值 = 升序第 floor(n/2)+1 个（偶数个成员取较大者）；
- 消散（行提前终止）成员以有限峰值正常参与；指标全缺成员为哨兵，仅在该指标剔除；
- 不跨气旋/起报时次混合统计。

含 WNV3 配对真实数据独立 pandas 复算与锁定值抽核（文件缺失自动跳过）。
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pandas as pd
import pytest

from typhoon_track.core import (
    filter_rows,
    make_mapping,
    normalize,
    peak_profile,
    read_csv,
)

DEMO = Path(__file__).resolve().parents[1] / "demo_src"
REAL_ENSEMBLE = DEMO / "WNV3_2026_10_15T18_00_paired_ensemble.csv"


def make_frame(rows: list[dict]) -> pd.DataFrame:
    """构造已 normalize 语义的单气旋预报帧；缺省字段由下方默认值补齐。"""
    base = {
        "storm": "SYN",
        "member": "0",
        "init": pd.Timestamp("2026-10-15T18:00:00", tz="UTC"),
        "valid": pd.Timestamp("2026-10-15T18:00:00", tz="UTC"),
        "lead_h": 0.0,
        "lat": 10.0,
        "lon": 130.0,
        "wind": 30.0,
        "pressure": 1000.0,
    }
    return pd.DataFrame([{**base, **row} for row in rows])


# ---------- 合成数据：极值、出现时效与聚合 ----------


def test_peak_independent_extremes_and_occurrence_leads() -> None:
    # 风速峰与气压谷出现在不同时效（真实数据常见风压不同步），各自独立报告
    rows = [
        {"member": "0", "lead_h": 0.0, "wind": 30.0, "pressure": 1000.0},
        {"member": "0", "lead_h": 6.0, "wind": 50.0, "pressure": 996.0},
        {"member": "0", "lead_h": 12.0, "wind": 45.0, "pressure": 990.0},
    ]
    profile = peak_profile(make_frame(rows))
    assert profile.n_total == 1
    peak = profile.members[0]
    assert peak.peak_wind == pytest.approx(50.0)
    assert peak.peak_wind_lead_h == pytest.approx(6.0)
    assert peak.peak_pressure == pytest.approx(990.0)
    assert peak.peak_pressure_lead_h == pytest.approx(12.0)
    assert profile.wind.median == pytest.approx(50.0)
    assert profile.wind.mean == pytest.approx(50.0)
    assert profile.pressure.median == pytest.approx(990.0)
    assert profile.pressure.mean == pytest.approx(990.0)


def test_peak_tie_takes_earliest_lead() -> None:
    rows = [
        {"member": "0", "lead_h": 0.0, "wind": 30.0, "pressure": 1002.0},
        {"member": "0", "lead_h": 12.0, "wind": 60.0, "pressure": 1000.0},
        {"member": "0", "lead_h": 24.0, "wind": 60.0, "pressure": 980.0},
        {"member": "0", "lead_h": 36.0, "wind": 55.0, "pressure": 980.0},
    ]
    peak = peak_profile(make_frame(rows)).members[0]
    assert peak.peak_wind == pytest.approx(60.0)
    assert peak.peak_wind_lead_h == pytest.approx(12.0)  # 并列取最早
    assert peak.peak_pressure == pytest.approx(980.0)
    assert peak.peak_pressure_lead_h == pytest.approx(24.0)  # 并列取最早


def test_peak_upper_median_even_and_odd_counts() -> None:
    rows = [
        {"member": "0", "wind": 10.0, "pressure": 990.0},
        {"member": "1", "wind": 20.0, "pressure": 980.0},
        {"member": "2", "wind": 30.0, "pressure": 970.0},
        {"member": "3", "wind": 40.0, "pressure": 960.0},
    ]
    profile = peak_profile(make_frame(rows))
    # 偶数 4 个：升序 [10,20,30,40]，上中位 = 第 floor(4/2)+1 = 3 个 = 30
    assert profile.wind.median == pytest.approx(30.0)
    assert profile.wind.mean == pytest.approx(25.0)
    assert profile.wind.n_valid == 4
    # 气压（各成员单值即其最低）：升序 [960,970,980,990]，上中位 980
    assert profile.pressure.median == pytest.approx(980.0)
    assert profile.pressure.mean == pytest.approx(975.0)
    # 奇数 3 个：上中位 = 正中
    odd = peak_profile(make_frame(rows[:3]))
    assert odd.wind.median == pytest.approx(20.0)
    assert odd.wind.mean == pytest.approx(20.0)


def test_peak_sentinel_all_missing_member_excluded_per_metric() -> None:
    rows = [
        {"member": "0", "wind": 30.0, "pressure": 1000.0},
        {"member": "1", "wind": None, "pressure": 1005.0},
        {"member": "1", "lead_h": 6.0, "wind": None, "pressure": 1004.0},
        {"member": "2", "wind": 40.0, "pressure": 1001.0},
    ]
    profile = peak_profile(make_frame(rows))
    assert profile.n_total == 3
    sentinel = profile.members[1]
    assert sentinel.peak_wind is None  # 哨兵：列表值为 None（前端显示"-"）
    assert sentinel.peak_wind_lead_h is None
    assert sentinel.peak_pressure == pytest.approx(1004.0)  # 气压正常参与
    assert profile.wind.n_valid == 2  # 两指标分母独立暴露
    assert profile.wind.median == pytest.approx(40.0)
    assert profile.wind.mean == pytest.approx(35.0)
    assert profile.pressure.n_valid == 3
    assert profile.pressure.median == pytest.approx(1001.0)  # [1000,1001,1004] 上中位
    assert profile.pressure.mean == pytest.approx((1000.0 + 1004.0 + 1001.0) / 3)


def test_peak_partial_missing_uses_available_rows() -> None:
    rows = [
        {"member": "0", "lead_h": 0.0, "wind": None, "pressure": None},
        {"member": "0", "lead_h": 6.0, "wind": 50.0, "pressure": 990.0},
        {"member": "0", "lead_h": 12.0, "wind": None, "pressure": 995.0},
    ]
    peak = peak_profile(make_frame(rows)).members[0]
    assert peak.peak_wind == pytest.approx(50.0)  # 部分缺失按已有行取极值
    assert peak.peak_wind_lead_h == pytest.approx(6.0)
    assert peak.peak_pressure == pytest.approx(990.0)


def test_peak_dissipated_member_keeps_finite_peak() -> None:
    # 消散 = 行提前终止：成员 1 只存在前两个时次，其有限峰值照常参与统计
    rows = [
        {"member": "0", "lead_h": 0.0, "wind": 20.0},
        {"member": "1", "lead_h": 0.0, "wind": 30.0},
        {"member": "2", "lead_h": 0.0, "wind": 10.0},
        {"member": "0", "lead_h": 6.0, "wind": 80.0},
        {"member": "1", "lead_h": 6.0, "wind": 25.0},
        {"member": "2", "lead_h": 6.0, "wind": 50.0},
        {"member": "0", "lead_h": 12.0, "wind": 70.0},
        {"member": "2", "lead_h": 12.0, "wind": 40.0},
    ]
    profile = peak_profile(make_frame(rows))
    assert profile.n_total == 3
    assert profile.wind.n_valid == 3  # 消散成员不做哨兵
    by_member = {m.member: m for m in profile.members}
    assert by_member["1"].peak_wind == pytest.approx(30.0)  # 有限峰值，非哨兵
    assert by_member["0"].peak_wind == pytest.approx(80.0)
    # [30,50,80] 上中位 50；若错误地把消散成员当哨兵剔除，中位数会变成 80
    assert profile.wind.median == pytest.approx(50.0)
    assert profile.wind.mean == pytest.approx((80.0 + 30.0 + 50.0) / 3)


def test_peak_members_sorted_numerically() -> None:
    rows = [{"member": m, "wind": 10.0} for m in ("2", "10", "1")]
    profile = peak_profile(make_frame(rows))
    assert [m.member for m in profile.members] == ["1", "2", "10"]


def test_peak_without_member_column_single_track() -> None:
    frame = make_frame(
        [{"lead_h": 0.0, "wind": 35.0}, {"lead_h": 6.0, "wind": 45.0}]
    ).drop(columns=["member"])
    profile = peak_profile(frame)
    assert profile.n_total == 1
    peak = profile.members[0]
    assert peak.peak_wind == pytest.approx(45.0)
    assert peak.peak_wind_lead_h == pytest.approx(6.0)
    assert profile.wind.median == pytest.approx(45.0)
    assert profile.wind.mean == pytest.approx(45.0)


def test_peak_all_missing_metric_stats_none() -> None:
    rows = [{"member": "0", "wind": None}, {"member": "1", "wind": None}]
    profile = peak_profile(make_frame(rows))
    assert profile.wind.n_valid == 0
    assert profile.wind.median is None  # 缺失保持缺失，不臆造
    assert profile.wind.mean is None
    assert profile.pressure.n_valid == 2
    assert profile.pressure.median == pytest.approx(1000.0)


def test_peak_rejects_mixed_storm_and_init() -> None:
    with pytest.raises(ValueError, match="不跨气旋混合统计"):
        peak_profile(make_frame([{"storm": "A"}, {"storm": "B"}]))
    with pytest.raises(ValueError, match="不跨起报时次混合统计"):
        peak_profile(make_frame([{"init": pd.Timestamp("2026-10-15T18:00:00", tz="UTC")},
                                 {"init": pd.Timestamp("2026-10-16T00:00:00", tz="UTC")}]))


# ---------- 真实数据抽核（WNV3 配对文件，缺失自动跳过） ----------


@pytest.fixture(scope="module")
def real_frame():
    if not REAL_ENSEMBLE.is_file():
        pytest.skip("WNV3 配对 CSV 未放入 demo_src，跳过真实数据抽核")
    df = read_csv(REAL_ENSEMBLE)
    return normalize(df, make_mapping(df.columns)).frame


def _independent_recompute(rows: pd.DataFrame) -> dict[str, dict[str, float]]:
    """独立 pandas 复算：每成员 max(wind)/min(pressure) 及各自最早出现时效。"""
    members: dict[str, dict[str, float]] = {}
    wind_rows = rows.dropna(subset=["wind"])
    pressure_rows = rows.dropna(subset=["pressure"])
    for member in rows["member"].dropna().astype("string").unique():
        winds = wind_rows[wind_rows["member"].astype("string") == member]
        pressures = pressure_rows[pressure_rows["member"].astype("string") == member]
        entry: dict[str, float] = {}
        if not winds.empty:
            entry["peak_wind"] = float(cast("float", winds["wind"].max()))
            best = winds[winds["wind"] == entry["peak_wind"]]
            entry["peak_wind_lead_h"] = float(cast("float", best["lead_h"].min()))
        if not pressures.empty:
            entry["peak_pressure"] = float(cast("float", pressures["pressure"].min()))
            best = pressures[pressures["pressure"] == entry["peak_pressure"]]
            entry["peak_pressure_lead_h"] = float(cast("float", best["lead_h"].min()))
        members[str(member)] = entry
    return members


@pytest.mark.parametrize(
    "storm", ("EP202026", "EP212026", "SH922026", "WP292026")
)
def test_real_wnv3_member_peaks_independent_recomputation(real_frame, storm: str) -> None:
    rows = filter_rows(real_frame, storm=storm)
    profile = peak_profile(rows)
    expected = _independent_recompute(rows)
    assert profile.n_total == 64
    by_member = {m.member: m for m in profile.members}
    assert set(by_member) == set(expected)
    for member, entry in expected.items():
        peak = by_member[member]
        if "peak_wind" in entry:
            assert peak.peak_wind == pytest.approx(entry["peak_wind"]), (
                f"{storm} 成员 {member} 峰值风速不符"
            )
            assert peak.peak_wind_lead_h == pytest.approx(entry["peak_wind_lead_h"]), (
                f"{storm} 成员 {member} 峰值风速出现时效应取最早"
            )
        if "peak_pressure" in entry:
            assert peak.peak_pressure == pytest.approx(entry["peak_pressure"]), (
                f"{storm} 成员 {member} 最低气压不符"
            )
            assert peak.peak_pressure_lead_h == pytest.approx(entry["peak_pressure_lead_h"]), (
                f"{storm} 成员 {member} 最低气压出现时效应取最早"
            )
    # 聚合独立复算：上中位值（升序第 floor(n/2)+1 个）与算术平均
    winds = sorted(e["peak_wind"] for e in expected.values() if "peak_wind" in e)
    pressures = sorted(e["peak_pressure"] for e in expected.values() if "peak_pressure" in e)
    assert profile.wind.n_valid == len(winds)
    assert profile.wind.median == pytest.approx(winds[len(winds) // 2])
    assert profile.wind.mean == pytest.approx(sum(winds) / len(winds))
    assert profile.pressure.n_valid == len(pressures)
    assert profile.pressure.median == pytest.approx(pressures[len(pressures) // 2])
    assert profile.pressure.mean == pytest.approx(sum(pressures) / len(pressures))


def test_real_wnv3_locked_aggregates(real_frame) -> None:
    # 锁定值来自 2026-10-16 首算（demo_src/WNV3_2026_10_15T18_00_paired_ensemble.csv）
    wp = peak_profile(filter_rows(real_frame, storm="WP292026"))
    assert wp.wind.median == pytest.approx(157.6)
    assert wp.wind.mean == pytest.approx(156.5546875)
    assert wp.pressure.median == pytest.approx(902.2)
    assert wp.pressure.mean == pytest.approx(902.259375)
    ep21 = peak_profile(filter_rows(real_frame, storm="EP212026"))
    assert ep21.wind.median == pytest.approx(115.8)
    assert ep21.wind.mean == pytest.approx(115.1734375)
    assert ep21.pressure.median == pytest.approx(949.7)
    assert ep21.pressure.mean == pytest.approx(949.4453125)


def test_real_wnv3_wind_pressure_desynchronized_member(real_frame) -> None:
    # 真实风压不同步例证：EP202026 成员 25 风速峰在 6h（51.5 kt）、气压谷在 0h（999.0 hPa）
    # —— 独立取极值口径的直接实证（若绑定峰值时刻取气压会得到 6h 的值）
    ep20 = {m.member: m for m in peak_profile(filter_rows(real_frame, storm="EP202026")).members}
    peak = ep20["25"]
    assert peak.peak_wind == pytest.approx(51.5)
    assert peak.peak_wind_lead_h == pytest.approx(6.0)
    assert peak.peak_pressure == pytest.approx(999.0)
    assert peak.peak_pressure_lead_h == pytest.approx(0.0)
