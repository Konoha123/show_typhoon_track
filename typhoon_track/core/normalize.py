"""标准化层：类型解析、预报时效（lead_h）判定与基本表校验。"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


@dataclass
class NormalizedResult:
    """normalize 的返回：标准化表 + 需由调用方渲染的诊断信息（core 不打印）。"""

    frame: pd.DataFrame
    warnings: list[str] = field(default_factory=list)


def normalize(
    df: pd.DataFrame, mapping: dict[str, str], lead_unit: str | None = None
) -> NormalizedResult:
    """按映射抽取语义列并解析类型；lead_h 判定与 demo 语义一致。

    显式声明的 lead_time_hours 与 valid_time-init_time 双口径交叉核对；
    数值 lead_time 单位未知时不换算，仅给出诊断信息（原脚本为 stderr 提示）。
    """
    warnings: list[str] = []
    out = pd.DataFrame({key: df[col] for key, col in mapping.items()})
    for key in ("init", "valid"):
        if key in out:
            out[key] = pd.to_datetime(out[key], utc=True, errors="coerce")
    for key in ("lat", "lon", "wind", "pressure", "rmw"):
        if key in out:
            out[key] = pd.to_numeric(out[key], errors="coerce")
    for key in [c for c in out if c.startswith(("r34_", "r50_", "r64_"))]:
        out[key] = pd.to_numeric(out[key], errors="coerce")

    declared_hours: pd.Series | None = None
    if "lead" in out:
        raw_name = mapping["lead"].casefold()
        if raw_name in ("lead_time_hours", "lead_hours"):
            declared_hours = pd.Series(pd.to_numeric(out["lead"], errors="coerce"))
            lead_values = out["lead"]
            invalid = lead_values.notna() & declared_hours.isna()
            if invalid.any():
                raise ValueError(f"显式小时数列 {mapping['lead']} 含非数值数据")
        elif "init" not in out or "valid" not in out:
            numeric = pd.Series(pd.to_numeric(out["lead"], errors="coerce"))
            if bool(numeric.notna().any()):
                if lead_unit is None:
                    warnings.append(
                        "提示：lead_time 是数值；单位未知，未换算。可用 --lead-unit hours|seconds。"
                    )
                else:
                    out["lead_h"] = numeric / (3600 if lead_unit == "seconds" else 1)
            else:
                deltas = pd.to_timedelta(pd.Series(out["lead"]), errors="coerce")
                if bool(deltas.notna().any()):
                    out["lead_h"] = deltas.dt.total_seconds() / 3600

    if "init" in out and "valid" in out:
        computed = (out["valid"] - out["init"]).dt.total_seconds() / 3600
        if declared_hours is not None:
            disagree = (computed - declared_hours).abs() > 0.01
            if disagree.any():
                raise ValueError(
                    f"{int(disagree.sum())} 行 lead_time_hours 与 valid_time-init_time 不一致"
                )
        out["lead_h"] = computed
    elif declared_hours is not None:
        out["lead_h"] = declared_hours
    return NormalizedResult(frame=out, warnings=warnings)


def validate_track_table(out: pd.DataFrame, *, kind: str = "forecast") -> None:
    """拒绝明显不是轨迹 CSV 的输入，而不是静默输出空结果。

    kind=observation（观测参考轨迹）时放宽：允许无 track_id（有 storm_name）、
    无成员/起报字段；位置与有效时刻要求不变。
    """
    if kind not in ("forecast", "observation"):
        raise ValueError(f"未知 kind: {kind}")
    if "storm" not in out and not (kind == "observation" and "name" in out):
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
