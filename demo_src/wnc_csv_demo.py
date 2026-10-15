#!/usr/bin/env python3
"""Read an existing Weather Lab / WeatherNext Cyclones *track* CSV.

This demonstration does not download forecasts or run WNC. Column aliases are
based partly on google-deepmind/weathernext/cyclones/constants.py; actual
Weather Lab export variants must be inspected before quantitative use.

Requires: pandas >= 2.0
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

# Semantic key -> possible CSV headers. Never guess ambiguous wind/pressure units.
ALIASES = {
    "storm": ["track_id", "storm_id", "cyclone_id", "sid", "atcf_id"],
    "name": ["storm_name", "cyclone_name", "name"],
    "init": ["init_time", "initialization_time", "forecast_datetime", "forecast_init_time", "initial_time"],
    "valid": ["valid_time", "date_time", "datetime", "forecast_valid_time"],
    "lead": ["lead_time_hours", "lead_hours", "lead_time", "forecast_lead_time", "forecast_hour", "tau"],
    "lat": ["lat", "latitude"],
    "lon": ["lon", "longitude"],
    "wind": ["maximum_sustained_wind_speed_knots", "max_sustained_wind_speed_knots", "vmax_kt", "vmax_knots", "wind_kt"],
    "pressure": ["minimum_sea_level_pressure_hpa", "min_sea_level_pressure_hpa", "pmin_hpa", "mslp_hpa"],
    "member": ["ensemble_member", "member", "sample", "member_id", "ensemble_member_id"],
    "model": ["model", "model_name", "technique"],
    "source": ["source", "data_source", "track_type", "data_type"],
    "rmw": ["radius_of_maximum_winds_km", "rmw_km"],
    **{
        f"r{speed}_{quad}": [f"radius_{speed}_knot_winds_{quad}_km"]
        for speed in (34, 50, 64) for quad in ("ne", "se", "sw", "nw")
    },
}


def args_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="读取本地 WNC 热带气旋轨迹 CSV，展示轨迹、峰值强度和24小时风速变化。"
    )
    p.add_argument("csv", type=Path, help="CSV 文件路径（必填）")
    p.add_argument("--inspect", action="store_true", help="只查看原始字段、映射和前3行")
    p.add_argument("--list-tracks", action="store_true", help="列出文件中的气旋、成员数量及预报时效范围")
    p.add_argument("--storm", help="按 track_id / storm_name 精确选择一个气旋（忽略大小写）")
    p.add_argument("--member", help="按集合成员的字段值精确选择，不能混合不同成员")
    p.add_argument("--init", help="选择起报时次，如 2026-07-01T00:00Z（UTC）")
    p.add_argument("--model", help="选择模型列中的具体值")
    p.add_argument("--source", help="选择数据来源列中的具体值，以排除观测轨迹等")
    p.add_argument("--max-lead-hours", type=float, help="仅保留不超过该预报时效的行")
    p.add_argument("--at-lead-hours", type=float, help="仅保留指定时效（允许0.01小时误差）")
    p.add_argument("--lead-unit", choices=("hours", "seconds"),
                   help="仅当 CSV 中 lead_time 是数值且缺少起报/有效时刻时指定单位")
    p.add_argument("--column", action="append", default=[], metavar="KEY=HEADER",
                   help="覆盖原始列名映射，可重复使用，如 --column wind=VMAX_KT")
    p.add_argument("--output", type=Path, help="将筛选后的标准化字段导出为新 CSV")
    p.add_argument("--max-rows", type=int, default=30, help="终端最多显示几行轨迹，默认30")
    return p


def read_csv(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise ValueError(f"文件不存在: {path}")
    try:
        # Read as strings to preserve track IDs such as '01W'; convert known measurements later.
        # Weather Lab exports may start with license/comment lines followed by
        # "# BEGIN DATA" and the actual CSV header. Do not lose the raw file.
        df = pd.read_csv(path, dtype="string", encoding="utf-8-sig",
                         low_memory=False, comment="#")
    except (UnicodeError, pd.errors.ParserError) as exc:
        raise ValueError(f"读取失败（检查编码、分隔符和 CSV 格式）: {exc}") from exc
    df.columns = [c.strip().lstrip("\ufeff") for c in df.columns]
    if df.empty:
        raise ValueError("CSV 没有数据行")
    if len(df.columns) != len(set(df.columns)):
        raise ValueError("CSV 有重复的列名，需先处理")
    return df


def make_mapping(columns: pd.Index, overrides: list[str]) -> dict[str, str]:
    by_lower = {c.casefold(): c for c in columns}
    mapping = {}
    for key, candidates in ALIASES.items():
        for candidate in candidates:
            if candidate.casefold() in by_lower:
                mapping[key] = by_lower[candidate.casefold()]
                break
    for entry in overrides:
        if "=" not in entry:
            raise ValueError(f"--column 必须使用 KEY=HEADER: {entry}")
        key, header = (x.strip() for x in entry.split("=", 1))
        if key not in ALIASES:
            raise ValueError(f"未知 KEY={key}; 可选: {', '.join(ALIASES)}")
        if header not in columns:
            raise ValueError(f"指定的原始列名不存在: {header}; 现有: {list(columns)}")
        mapping[key] = header
    return mapping


def inspect(df: pd.DataFrame, mapping: dict[str, str]) -> None:
    print("\n[原始列名]")
    for i, c in enumerate(df.columns, 1):
        print(f"  {i:2d}. {c}")
    print("\n[识别到的语义字段 -> 原始列名]")
    for key, original in mapping.items():
        print(f"  {key:12s} <- {original}")
    unknown = [c for c in df.columns if c not in mapping.values()]
    if unknown:
        print("\n[尚未识别的原始字段]", ", ".join(unknown))
    print("\n[原始数据前3行]")
    with pd.option_context("display.max_columns", 12, "display.width", 170):
        print(df.head(3).to_string(index=False))


def normalize(df: pd.DataFrame, mapping: dict[str, str], lead_unit: str | None) -> pd.DataFrame:
    out = pd.DataFrame({key: df[col] for key, col in mapping.items()})
    for key in ("init", "valid"):
        if key in out:
            out[key] = pd.to_datetime(out[key], utc=True, errors="coerce")
    for key in ("lat", "lon", "wind", "pressure", "rmw"):
        if key in out:
            out[key] = pd.to_numeric(out[key], errors="coerce")
    for key in [c for c in out if c.startswith(("r34_", "r50_", "r64_"))]:
        out[key] = pd.to_numeric(out[key], errors="coerce")

    # Treat *_hours as explicitly labelled hours; do not infer the unit of
    # an otherwise numeric 'lead_time'. Verify against timestamps if possible.
    declared_hours = None
    if "lead" in out:
        raw_name = mapping["lead"].casefold()
        if raw_name in ("lead_time_hours", "lead_hours"):
            declared_hours = pd.to_numeric(out["lead"], errors="coerce")
            invalid = out["lead"].notna() & declared_hours.isna()
            if invalid.any():
                raise ValueError(f"显式小时数列 {mapping['lead']} 含非数值数据")
        elif "init" not in out or "valid" not in out:
            numeric = pd.to_numeric(out["lead"], errors="coerce")
            if numeric.notna().any():
                if lead_unit is None:
                    print("提示：lead_time 是数值；单位未知，未换算。可用 --lead-unit hours|seconds。", file=sys.stderr)
                else:
                    out["lead_h"] = numeric / (3600 if lead_unit == "seconds" else 1)
            else:
                deltas = pd.to_timedelta(out["lead"], errors="coerce")
                if deltas.notna().any():
                    out["lead_h"] = deltas.dt.total_seconds() / 3600

    if "init" in out and "valid" in out:
        computed = (out["valid"] - out["init"]).dt.total_seconds() / 3600
        if declared_hours is not None:
            disagree = (computed - declared_hours).abs() > 0.01
            if disagree.any():
                raise ValueError(f"{int(disagree.sum())} 行 lead_time_hours 与 valid_time-init_time 不一致")
        out["lead_h"] = computed
    elif declared_hours is not None:
        out["lead_h"] = declared_hours
    return out


def validate_track_table(out: pd.DataFrame) -> None:
    """Reject obviously incompatible CSVs rather than claiming success."""
    if "storm" not in out:
        raise ValueError("缺少气旋编号 track_id；请 --inspect 检查文件类型")
    if not any(key in out for key in ("lat", "lon", "wind", "pressure")):
        raise ValueError("没有识别到位置或强度字段；请 --inspect 检查文件类型")
    if "valid" not in out and "lead_h" not in out:
        raise ValueError("缺少有效时刻或可解释的预报时效；请 --inspect")
    for key in ("lat", "lon"):
        if key in out and out[key].notna().sum() == 0:
            raise ValueError(f"{key} 无有效数值；请核对原始 CSV 列和编码")
    if "valid" in out and out["valid"].notna().sum() == 0:
        raise ValueError("valid_time 无可解析的 UTC 时刻")


def list_tracks(out: pd.DataFrame) -> None:
    """Summarize raw ensemble structure without mixing members for statistics."""
    if "storm" not in out:
        raise ValueError("无法列出气旋：缺少 track_id，请 --inspect")
    print("\n[气旋列表及集合成员概况（非集合平均）]")
    for storm, group in out.groupby("storm", sort=True, dropna=False):
        count = len(group)
        member = (group["member"].nunique(dropna=True)
                  if "member" in group else "无成员字段")
        if "lead_h" in group and group["lead_h"].notna().any():
            leads = f"{group['lead_h'].min():g}–{group['lead_h'].max():g} h"
        else:
            leads = "未知"
        print(f"  {storm}: {count} 行；成员数={member}；时效范围={leads}")
    if "member" in out:
        uniq = out["member"].dropna().astype("string").unique().tolist()
        try:
            uniq.sort(key=lambda v: int(v))
        except ValueError:
            uniq.sort()
        print("  可用成员编号（前60个）：" + ", ".join(uniq[:60]))
    print("  提示：本文件中的 member/sample=0 不是集合均值。")


def exact_filter(out: pd.DataFrame, column: str, value: str | None) -> pd.DataFrame:
    if value is None:
        return out
    if column not in out:
        raise ValueError(f"使用 --{column} 但 CSV 缺少相应字段，请先 --inspect")
    chosen = out[out[column].astype("string").str.casefold() == value.casefold()]
    if chosen.empty:
        options = out[column].dropna().unique().tolist()[:20]
        raise ValueError(f"{column}={value!r} 没有匹配；可选值（最多20个）: {options}")
    return chosen


def choose_one_or_fail(out: pd.DataFrame, key: str, option: str) -> None:
    if key not in out:
        return
    unique = out[key].dropna().astype("string").unique().tolist()
    if len(unique) > 1:
        preview = ", ".join(unique[:15])
        raise ValueError(f"检测到多个 {key}：{preview}。请用 {option} 明确指定，避免混合不同轨迹/成员/起报时次。")


def apply_filters(out: pd.DataFrame, args: argparse.Namespace) -> pd.DataFrame:
    for key in ("model", "source", "member"):
        out = exact_filter(out, key, getattr(args, key))
    if args.storm is not None:
        if "storm" in out:
            matching = out["storm"].astype("string").str.casefold() == args.storm.casefold()
        else:
            matching = pd.Series(False, index=out.index)
        if "name" in out:
            matching = matching | (out["name"].astype("string").str.casefold() == args.storm.casefold())
        out = out[matching.fillna(False)]
        if out.empty:
            raise ValueError(f"未找到气旋 {args.storm!r}; 请 --inspect 以及检查 track_id")
    if args.init is not None:
        if "init" not in out:
            raise ValueError("使用 --init 但 CSV 缺少起报字段，请先 --inspect")
        parsed = pd.to_datetime(args.init, utc=True)
        out = out[out["init"] == parsed]
        if out.empty:
            raise ValueError(f"起报时间 {args.init!r} 没有匹配的行")

    # Do not silently combine observations with predictions, or different forecasts/members.
    for key, option in (("source", "--source"), ("model", "--model"),
                        ("storm", "--storm"), ("init", "--init"), ("member", "--member")):
        if key == "init" and key in out:
            unique = out[key].dropna().unique().tolist()
            if len(unique) > 1:
                raise ValueError("包含不同起报时间。请指定 --init，避免混合预报批次。")
        else:
            choose_one_or_fail(out, key, option)
    if "storm" not in out and "name" in out:
        choose_one_or_fail(out, "name", "--storm")

    if (args.max_lead_hours is not None or args.at_lead_hours is not None) and "lead_h" not in out:
        raise ValueError("预报时效无法判定：需要 init+valid，或 lead_time + --lead-unit")
    if args.max_lead_hours is not None:
        out = out[out["lead_h"] <= args.max_lead_hours]
    if args.at_lead_hours is not None:
        out = out[(out["lead_h"] - args.at_lead_hours).abs() <= 0.01]
    if out.empty:
        raise ValueError("筛选后没有数据；检查风暴、起报时间和时效选项")
    if "valid" in out and out["valid"].notna().any():
        duplicate_valid = out["valid"].notna() & out["valid"].duplicated(keep=False)
        if duplicate_valid.any():
            raise ValueError("当前选择有重复的 valid_time；请检查是否混合成员、源、路径或重复行，拒绝静默去重")
    return out.copy()


def ri_changes(out: pd.DataFrame) -> pd.DataFrame:
    """Exact 24-hour differences only; no interpolation or time-axis extrapolation."""
    if "wind" not in out or "valid" not in out:
        return pd.DataFrame()
    clean = out[["valid", "wind"]].dropna()
    if len(clean) < 2:
        return pd.DataFrame()
    prev = clean.rename(columns={"valid": "t0", "wind": "v0"})
    future = clean.rename(columns={"valid": "t1", "wind": "v1"})
    prev = prev.assign(t1=prev["t0"] + pd.Timedelta(hours=24))
    joined = prev.merge(future, on="t1", how="inner")
    if joined.empty:
        return joined
    joined["delta_kt_24h"] = joined["v1"] - joined["v0"]
    return joined.sort_values("delta_kt_24h", ascending=False)


def show_result(out: pd.DataFrame, max_rows: int) -> None:
    print("\n[已选择的气旋与预报]")
    for key in ("storm", "name", "model", "source", "member", "init"):
        if key in out:
            vals = out[key].dropna().unique()
            if len(vals):
                print(f"  {key}: {vals[0]}")
    print(f"  记录数量: {len(out)}")
    if "wind" not in out:
        print("  未识别最大风速列；需 --inspect 并核对单位，或 --column wind=实际列名")
    if "pressure" not in out:
        print("  未识别最低气压列；需 --inspect 并核对单位，或 --column pressure=实际列名")
    columns = [k for k in ("lead_h", "valid", "lat", "lon", "wind", "pressure", "rmw",
                           "r34_ne", "r34_se", "r34_sw", "r34_nw") if k in out]
    sortkey = "valid" if "valid" in out else ("lead_h" if "lead_h" in out else None)
    if sortkey:
        out = out.sort_values(sortkey)
    print("\n[轨迹/强度样例，坐标沿用 CSV 原经度系统]")
    with pd.option_context("display.max_rows", max_rows, "display.width", 185):
        print(out[columns].head(max_rows).to_string(index=False)) if columns else print("没有识别到轨迹字段")
    if len(out) > max_rows:
        print(f"  （仅显示前 {max_rows} 行；可增大 --max-rows 或 --output 导出）")

    if "wind" in out and out["wind"].notna().any():
        peak = out.loc[out["wind"].idxmax()]
        print(f"\n[最大预报风速] {peak['wind']:g} kt, 时刻={peak.get('valid', '未知')}, 时效={peak.get('lead_h', '未知')} 小时")
        radii = {c: peak[c] for c in ("r34_ne", "r34_se", "r34_sw", "r34_nw") if c in out and pd.notna(peak[c])}
        if radii:
            print("[该峰值时刻 34 kt 风圈半径，km] " + ", ".join(f"{c}={v:g}" for c, v in radii.items()))
    if "pressure" in out and out["pressure"].notna().any():
        low = out.loc[out["pressure"].idxmin()]
        print(f"[最低预报中心气压] {low['pressure']:g} hPa, 时刻={low.get('valid', '未知')}, 时效={low.get('lead_h', '未知')} 小时")
    d = ri_changes(out)
    if not d.empty:
        best = d.iloc[0]
        print(f"[最大可计算的24小时风速增量] {best['delta_kt_24h']:+g} kt "
              f"({best['t0']} -> {best['t1']}); "
              f"达到 30 kt 快速增强阈值: {'是' if best['delta_kt_24h'] >= 30 else '否'}")
        print("  注：仅比较恰好相隔24小时的有效时次，且只针对当前单条轨迹。")
    else:
        print("[24小时风速增量] 暂无法计算（需有效时间、风速及恰好相隔24小时的两行）。")


def main() -> int:
    p = args_parser()
    args = p.parse_args()
    try:
        df = read_csv(args.csv)
        mapping = make_mapping(df.columns, args.column)
        if args.inspect:
            inspect(df, mapping)
            return 0
        print(f"读取 {args.csv}：{len(df)} 行，{len(df.columns)} 列；已识别 {len(mapping)} 类语义字段。")
        print("如需查看全部原始列名、前3行和映射，请使用 --inspect。")
        out = normalize(df, mapping, args.lead_unit)
        validate_track_table(out)
        if args.list_tracks:
            list_tracks(out)
            return 0
        out = apply_filters(out, args)
        if args.max_rows < 1:
            raise ValueError("--max-rows 应为正整数")
        show_result(out, args.max_rows)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            out.to_csv(args.output, index=False, encoding="utf-8-sig")
            print(f"\n已保存筛选/标准化后的 CSV: {args.output}")
        return 0
    except (ValueError, OSError, pd.errors.EmptyDataError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
