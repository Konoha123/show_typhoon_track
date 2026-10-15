"""读取原始轨迹 CSV 与语义字段映射。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .aliases import ALIASES


def read_csv(path: str | Path) -> pd.DataFrame:
    """读取轨迹 CSV，一律按字符串读入以保护编号标识符，跳过 '#' 注释行。"""
    path = Path(path)
    if not path.is_file():
        raise ValueError(f"文件不存在: {path}")
    try:
        df = pd.read_csv(
            path,
            dtype="string",
            encoding="utf-8-sig",
            low_memory=False,
            comment="#",
        )
    except (UnicodeError, pd.errors.ParserError) as exc:
        raise ValueError(f"读取失败（检查编码、分隔符和 CSV 格式）: {exc}") from exc
    df.columns = [c.strip().lstrip("\ufeff") for c in df.columns]
    if df.empty:
        raise ValueError("CSV 没有数据行")
    if len(df.columns) != len(set(df.columns)):
        raise ValueError("CSV 有重复的列名，需先处理")
    return df


def make_mapping(
    columns: pd.Index, overrides: dict[str, str] | None = None
) -> dict[str, str]:
    """按 ALIASES 大小写不敏感识别列名，返回 语义键 -> 原始列名。

    overrides 为显式覆盖（语义键 -> 原始列名），优先于自动识别。
    """
    by_lower = {c.casefold(): c for c in columns}
    mapping: dict[str, str] = {}
    for key, candidates in ALIASES.items():
        for candidate in candidates:
            if candidate.casefold() in by_lower:
                mapping[key] = by_lower[candidate.casefold()]
                break
    for key, header in (overrides or {}).items():
        if key not in ALIASES:
            raise ValueError(f"未知 KEY={key}; 可选: {', '.join(ALIASES)}")
        if header not in columns:
            raise ValueError(f"指定的原始列名不存在: {header}; 现有: {list(columns)}")
        mapping[key] = header
    return mapping
