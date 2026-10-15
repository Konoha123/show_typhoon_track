"""轨迹选取：纯筛选（filter_rows）与严格单轨迹选取（select_track）。

错误文案沿用 demo_src/wnc_csv_demo.py 原文（含 CLI 选项字样），
以支撑重组 CLI 的行为一致性对照验证，属有意设计。
"""

from __future__ import annotations

from typing import cast

import pandas as pd

_FORECAST_UNIQUE_KEYS = ("source", "model", "storm", "init", "member")
_OBSERVATION_UNIQUE_KEYS = ("source", "model", "storm")
_KEY_OPTIONS: tuple[tuple[str, str], ...] = (
    ("source", "--source"),
    ("model", "--model"),
    ("storm", "--storm"),
    ("init", "--init"),
    ("member", "--member"),
)


def _rows(out: pd.DataFrame, mask: object) -> pd.DataFrame:
    """布尔掩码行筛选：仅类型层收口 pandas 索引重载，运行时等价 out[mask]。"""
    return cast("pd.DataFrame", out[mask])


def exact_filter(out: pd.DataFrame, column: str, value: str | None) -> pd.DataFrame:
    """按字段值精确匹配（忽略大小写）；无匹配时报错并列出可选值。"""
    if value is None:
        return out
    if column not in out:
        raise ValueError(f"使用 --{column} 但 CSV 缺少相应字段，请先 --inspect")
    values = out[column].astype("string")
    mask = values.str.casefold() == value.casefold()
    chosen = _rows(out, mask)
    if chosen.empty:
        options = out[column].dropna().unique().tolist()[:20]
        raise ValueError(f"{column}={value!r} 没有匹配；可选值（最多20个）: {options}")
    return chosen


def _choose_one_or_fail(out: pd.DataFrame, key: str, option: str) -> None:
    """同键多值即拒绝：不得静默混合不同成员/起报时次/气旋。"""
    if key not in out:
        return
    unique = out[key].dropna().astype("string").unique().tolist()
    if len(unique) > 1:
        preview = ", ".join(unique[:15])
        raise ValueError(
            f"检测到多个 {key}：{preview}。请用 {option} 明确指定，"
            "避免混合不同轨迹/成员/起报时次。"
        )


def _apply_filters(
    out: pd.DataFrame,
    *,
    storm: str | None,
    member: str | None,
    init: str | None,
    model: str | None,
    source: str | None,
    max_lead_hours: float | None,
    at_lead_hours: float | None,
    unique_keys: tuple[str, ...] | None,
) -> pd.DataFrame:
    for key, value in (("model", model), ("source", source), ("member", member)):
        out = exact_filter(out, key, value)
    if storm is not None:
        if "storm" in out:
            storm_values = out["storm"].astype("string")
            matching = storm_values.str.casefold() == storm.casefold()
        else:
            matching = pd.Series(False, index=out.index)
        if "name" in out:
            name_values = out["name"].astype("string")
            matching = matching | (name_values.str.casefold() == storm.casefold())
        storm_mask = matching.fillna(False)
        out = _rows(out, storm_mask)
        if out.empty:
            raise ValueError(f"未找到气旋 {storm!r}; 请 --inspect 以及检查 track_id")
    if init is not None:
        if "init" not in out:
            raise ValueError("使用 --init 但 CSV 缺少起报字段，请先 --inspect")
        parsed = pd.to_datetime(init, utc=True)
        init_mask = pd.Series(out["init"]) == parsed
        out = _rows(out, init_mask)
        if out.empty:
            raise ValueError(f"起报时间 {init!r} 没有匹配的行")

    # 不静默合并观测与预报，或混合成员/起报时次；观测 kind 放宽成员与起报唯一性。
    if unique_keys is not None:
        for key, option in _KEY_OPTIONS:
            if key not in unique_keys:
                continue
            if key == "init" and "init" in out:
                unique = out["init"].dropna().unique().tolist()
                if len(unique) > 1:
                    raise ValueError("包含不同起报时间。请指定 --init，避免混合预报批次。")
            else:
                _choose_one_or_fail(out, key, option)
        if "storm" not in out and "name" in out:
            _choose_one_or_fail(out, "name", "--storm")

    if (max_lead_hours is not None or at_lead_hours is not None) and "lead_h" not in out:
        raise ValueError("预报时效无法判定：需要 init+valid，或 lead_time + --lead-unit")
    if max_lead_hours is not None:
        lead_values = pd.Series(out["lead_h"])
        out = _rows(out, lead_values <= max_lead_hours)
    if at_lead_hours is not None:
        lead_values = pd.Series(out["lead_h"])
        at_mask = (lead_values - at_lead_hours).abs() <= 0.01
        out = _rows(out, at_mask)
    if out.empty:
        raise ValueError("筛选后没有数据；检查风暴、起报时间和时效选项")
    if unique_keys is not None and "valid" in out:
        valid_values = pd.Series(out["valid"])
        duplicate_valid = valid_values.notna() & valid_values.duplicated(keep=False)
        if bool(duplicate_valid.any()):
            raise ValueError(
                "当前选择有重复的 valid_time；请检查是否混合成员、源、路径或重复行，拒绝静默去重"
            )
    return out.copy()


def filter_rows(
    out: pd.DataFrame,
    *,
    storm: str | None = None,
    member: str | None = None,
    init: str | None = None,
    model: str | None = None,
    source: str | None = None,
    max_lead_hours: float | None = None,
    at_lead_hours: float | None = None,
) -> pd.DataFrame:
    """纯筛选，不强制唯一性：供 Web 端按显式条件取数（如某气旋全部成员）。

    多值并存属调用方显式选择（集合意面图等），不构成统计口径混淆；
    重复 valid_time 不在此报错，由展示层按成员分列。
    """
    return _apply_filters(
        out,
        storm=storm,
        member=member,
        init=init,
        model=model,
        source=source,
        max_lead_hours=max_lead_hours,
        at_lead_hours=at_lead_hours,
        unique_keys=None,
    )


def select_track(
    out: pd.DataFrame,
    *,
    storm: str | None = None,
    member: str | None = None,
    init: str | None = None,
    model: str | None = None,
    source: str | None = None,
    max_lead_hours: float | None = None,
    at_lead_hours: float | None = None,
    kind: str = "forecast",
) -> pd.DataFrame:
    """严格单轨迹选取（与 demo 行为一致）：强制关键维度唯一，拒绝混合。"""
    if kind not in ("forecast", "observation"):
        raise ValueError(f"未知 kind: {kind}")
    unique_keys = _FORECAST_UNIQUE_KEYS if kind == "forecast" else _OBSERVATION_UNIQUE_KEYS
    return _apply_filters(
        out,
        storm=storm,
        member=member,
        init=init,
        model=model,
        source=source,
        max_lead_hours=max_lead_hours,
        at_lead_hours=at_lead_hours,
        unique_keys=unique_keys,
    )
