"""数据集目录存储：uploads/<id>/original.csv + meta.json，附进程内 LRU 解析缓存。

原始 CSV 字节级原样保存；元数据在导入时由 core 解析生成。
本机单人使用，不做并发与鉴权设计；历史目录由使用者自行管理。
"""

from __future__ import annotations

import json
import re
import shutil
import threading
from collections import OrderedDict
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from typhoon_track.core import (
    make_mapping,
    normalize,
    read_csv,
    summarize_tracks,
    validate_track_table,
)

KINDS = ("forecast", "observation")

_ID_PATTERN = re.compile(r"^[0-9A-Za-z_-]+$")
_SLUG_PATTERN = re.compile(r"[^0-9A-Za-z_-]+")


@dataclass(frozen=True)
class ParsedDataset:
    """一次解析的完整结果：元数据 + 标准化表。"""

    dataset_id: str
    kind: str
    meta: dict[str, Any]
    frame: pd.DataFrame


def _new_dataset_id(filename: str) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S_%f")
    slug = _SLUG_PATTERN.sub("-", Path(filename).stem).strip("-").lower()[:40]
    return f"{stamp}_{slug}" if slug else stamp


class DatasetStore:
    """数据集的落盘与读取；LRU 缓存避免每次请求重读大 CSV。"""

    def __init__(self, root: str | Path, cache_size: int = 8) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._cache: OrderedDict[str, ParsedDataset] = OrderedDict()
        self._cache_size = cache_size
        self._lock = threading.Lock()

    @property
    def root(self) -> Path:
        return self._root

    def _directory(self, dataset_id: str) -> Path:
        if not _ID_PATTERN.match(dataset_id):
            raise KeyError(dataset_id)
        directory = self._root / dataset_id
        if not (directory / "meta.json").is_file():
            raise KeyError(dataset_id)
        return directory

    def create(self, *, filename: str, content: bytes, kind: str) -> ParsedDataset:
        """保存原始文件并立即解析；解析失败则不留半成品目录。"""
        if kind not in KINDS:
            raise ValueError(f"未知 kind: {kind}; 可选: {', '.join(KINDS)}")
        dataset_id = _new_dataset_id(filename)
        directory = self._root / dataset_id
        directory.mkdir(parents=True)
        try:
            (directory / "original.csv").write_bytes(content)
            parsed = self._parse(
                directory,
                dataset_id=dataset_id,
                kind=kind,
                original_filename=filename,
                created_at=datetime.now(UTC).isoformat(timespec="seconds"),
            )
            meta_text = json.dumps(parsed.meta, ensure_ascii=False, indent=2)
            (directory / "meta.json").write_text(meta_text, encoding="utf-8")
        except BaseException:
            shutil.rmtree(directory, ignore_errors=True)
            raise
        with self._lock:
            self._cache[dataset_id] = parsed
            self._evict_locked()
        return parsed

    def list(self) -> list[dict[str, Any]]:
        """列出全部历史数据集元数据，新上传的在前（id 含时间戳前缀）。"""
        metas: list[dict[str, Any]] = []
        for directory in sorted(self._root.iterdir(), reverse=True):
            meta_file = directory / "meta.json"
            if directory.is_dir() and meta_file.is_file():
                metas.append(json.loads(meta_file.read_text(encoding="utf-8")))
        return metas

    def get(self, dataset_id: str) -> dict[str, Any]:
        """读取单个数据集元数据；不存在时抛 KeyError。"""
        meta_file = self._directory(dataset_id) / "meta.json"
        return json.loads(meta_file.read_text(encoding="utf-8"))

    def load(self, dataset_id: str) -> ParsedDataset:
        """取解析结果（LRU 缓存，未命中时按需重解析）。"""
        with self._lock:
            cached = self._cache.get(dataset_id)
            if cached is not None:
                self._cache.move_to_end(dataset_id)
                return cached
        directory = self._directory(dataset_id)
        meta = json.loads((directory / "meta.json").read_text(encoding="utf-8"))
        parsed = self._parse(
            directory,
            dataset_id=dataset_id,
            kind=str(meta["kind"]),
            original_filename=str(meta.get("original_filename", "original.csv")),
            created_at=str(meta.get("created_at", "")),
        )
        parsed = replace(parsed, meta=meta)  # 以落盘元数据为准
        with self._lock:
            self._cache[dataset_id] = parsed
            self._evict_locked()
        return parsed

    def _parse(
        self,
        directory: Path,
        *,
        dataset_id: str,
        kind: str,
        original_filename: str,
        created_at: str,
    ) -> ParsedDataset:
        df = read_csv(directory / "original.csv")
        mapping = make_mapping(df.columns)
        result = normalize(df, mapping)
        validate_track_table(result.frame, kind=kind)
        summary_frame = result.frame
        if "storm" not in summary_frame and "name" in summary_frame:
            # 观测轨迹可能只有 storm_name：以 name 补位汇总，不在 core 内做隐式别名
            summary_frame = summary_frame.assign(storm=summary_frame["name"])
        summary = summarize_tracks(summary_frame)
        meta: dict[str, Any] = {
            "dataset_id": dataset_id,
            "kind": kind,
            "original_filename": original_filename,
            "created_at": created_at,
            "rows": int(len(df)),
            "columns": int(len(df.columns)),
            "mapping": mapping,
            "warnings": result.warnings,
            "summary": {
                "storms": [
                    {
                        "storm": s.storm,
                        "rows": s.rows,
                        "member_count": s.member_count,
                        "lead_min": s.lead_min,
                        "lead_max": s.lead_max,
                    }
                    for s in summary.storms
                ],
                "members": summary.members,
            },
        }
        return ParsedDataset(dataset_id=dataset_id, kind=kind, meta=meta, frame=result.frame)

    def _evict_locked(self) -> None:
        while len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)
