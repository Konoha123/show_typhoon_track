#!/usr/bin/env python3
"""由 core 模块重组的 WNC 轨迹 CLI：与 demo_src/wnc_csv_demo.py 行为完全等价。

数据读取、字段映射、标准化与筛选全部来自 typhoon_track.core；
展示层文案与输出顺序按演示脚本逐字复刻，行为一致性由
tests/test_cli_parity.py 做“参数矩阵 × 数据集矩阵”的逐字节对照验证。
运行：python -m typhoon_track <csv> [选项]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from typhoon_track.core import (
    make_mapping,
    normalize,
    read_csv,
    ri_changes,
    select_track,
    summarize_tracks,
    validate_track_table,
)


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


def parse_overrides(entries: list[str]) -> dict[str, str]:
    """解析 --column 的 KEY=HEADER 覆盖项（与演示脚本报错文案一致）。"""
    overrides: dict[str, str] = {}
    for entry in entries:
        if "=" not in entry:
            raise ValueError(f"--column 必须使用 KEY=HEADER: {entry}")
        key, header = (x.strip() for x in entry.split("=", 1))
        overrides[key] = header
    return overrides


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


def list_tracks(out: pd.DataFrame) -> None:
    summary = summarize_tracks(out)
    print("\n[气旋列表及集合成员概况（非集合平均）]")
    for s in summary.storms:
        member = "无成员字段" if s.member_count is None else s.member_count
        if s.lead_min is not None and s.lead_max is not None:
            leads = f"{s.lead_min:g}–{s.lead_max:g} h"
        else:
            leads = "未知"
        print(f"  {s.storm}: {s.rows} 行；成员数={member}；时效范围={leads}")
    if summary.members is not None:
        print("  可用成员编号（前60个）：" + ", ".join(summary.members[:60]))
    print("  提示：本文件中的 member/sample=0 不是集合均值。")


def show_result(out: pd.DataFrame, max_rows: int) -> None:
    print("\n[已选择的气旋与预报]")
    for key in ("storm", "name", "model", "source", "member", "init"):
        if key in out:
            vals = pd.Series(out[key]).dropna().unique()
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

    if "wind" in out and bool(pd.Series(out["wind"]).notna().any()):
        peak = out.loc[pd.Series(out["wind"]).idxmax()]
        print(f"\n[最大预报风速] {peak['wind']:g} kt, 时刻={peak.get('valid', '未知')}, "
              f"时效={peak.get('lead_h', '未知')} 小时")
        radii = {c: peak[c] for c in ("r34_ne", "r34_se", "r34_sw", "r34_nw")
                 if c in out and pd.notna(peak[c])}
        if radii:
            print("[该峰值时刻 34 kt 风圈半径，km] " + ", ".join(f"{c}={v:g}" for c, v in radii.items()))
    if "pressure" in out and bool(pd.Series(out["pressure"]).notna().any()):
        low = out.loc[pd.Series(out["pressure"]).idxmin()]
        print(f"[最低预报中心气压] {low['pressure']:g} hPa, 时刻={low.get('valid', '未知')}, "
              f"时效={low.get('lead_h', '未知')} 小时")
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
        mapping = make_mapping(df.columns, parse_overrides(args.column))
        if args.inspect:
            inspect(df, mapping)
            return 0
        print(f"读取 {args.csv}：{len(df)} 行，{len(df.columns)} 列；已识别 {len(mapping)} 类语义字段。")
        print("如需查看全部原始列名、前3行和映射，请使用 --inspect。")
        result = normalize(df, mapping, args.lead_unit)
        for warning in result.warnings:
            print(warning, file=sys.stderr)
        out = result.frame
        validate_track_table(out)
        if args.list_tracks:
            list_tracks(out)
            return 0
        out = select_track(
            out,
            storm=args.storm,
            member=args.member,
            init=args.init,
            model=args.model,
            source=args.source,
            max_lead_hours=args.max_lead_hours,
            at_lead_hours=args.at_lead_hours,
        )
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
