"""service.datasets：上传存储、元数据与 LRU 缓存测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from typhoon_track.service.datasets import DatasetStore

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "demo_src"
MEAN = DEMO / "sample_synthetic_ensemble_mean.csv"
MEMBERS = DEMO / "sample_synthetic_ensemble.csv"

OBS_CSV = (
    b"storm_name,valid_time,lat,lon,vmax_kt,minimum_sea_level_pressure_hpa\n"
    b"DEMO,2026-07-01T00:00:00Z,18.2,131.5,40,998\n"
    b"DEMO,2026-07-01T06:00:00Z,18.8,130.8,45,994\n"
)


@pytest.fixture
def store(tmp_path: Path) -> DatasetStore:
    return DatasetStore(tmp_path)


def test_create_forecast_dataset(store: DatasetStore) -> None:
    parsed = store.create(filename="mean.csv", content=MEAN.read_bytes(), kind="forecast")
    assert parsed.kind == "forecast"
    meta = parsed.meta
    assert meta["rows"] == 5
    assert meta["columns"] == 13
    assert meta["warnings"] == []
    assert len(meta["summary"]["storms"]) == 1
    assert meta["summary"]["members"] is None
    directory = store.root / parsed.dataset_id
    assert (directory / "original.csv").read_bytes() == MEAN.read_bytes()  # 字节级原样
    assert (directory / "meta.json").is_file()


def test_create_observation_dataset(store: DatasetStore) -> None:
    parsed = store.create(filename="obs.csv", content=OBS_CSV, kind="observation")
    assert parsed.kind == "observation"
    assert parsed.meta["rows"] == 2
    assert parsed.meta["summary"]["storms"][0]["storm"] == "DEMO"


def test_create_rejects_unknown_kind(store: DatasetStore) -> None:
    with pytest.raises(ValueError, match="未知 kind"):
        store.create(filename="x.csv", content=MEAN.read_bytes(), kind="bogus")


def test_create_invalid_csv_leaves_no_leftover(store: DatasetStore) -> None:
    with pytest.raises(ValueError):
        store.create(filename="bad.csv", content=b"not,a,csv\n1,2\n", kind="forecast")
    assert list(store.root.iterdir()) == []


def test_member_ids_preserved_after_upload(store: DatasetStore) -> None:
    parsed = store.create(filename="ens.csv", content=MEMBERS.read_bytes(), kind="forecast")
    assert sorted(set(parsed.frame["member"])) == ["01", "02"]


def test_list_orders_newest_first_and_get_roundtrip(store: DatasetStore) -> None:
    first = store.create(filename="a.csv", content=MEAN.read_bytes(), kind="forecast")
    second = store.create(filename="b.csv", content=MEMBERS.read_bytes(), kind="forecast")
    listed = store.list()
    assert [m["dataset_id"] for m in listed][:2] == [second.dataset_id, first.dataset_id]
    assert store.get(first.dataset_id)["original_filename"] == "a.csv"
    with pytest.raises(KeyError):
        store.get("no-such-id")
    with pytest.raises(KeyError):
        store.get("../escape")  # 拒绝路径穿越


def test_load_returns_cached_object(store: DatasetStore) -> None:
    parsed = store.create(filename="m.csv", content=MEAN.read_bytes(), kind="forecast")
    assert store.load(parsed.dataset_id) is parsed
    # 逐出后重解析仍等价
    store._cache.clear()
    reloaded = store.load(parsed.dataset_id)
    assert reloaded is not parsed
    assert reloaded.frame.equals(parsed.frame)
    assert reloaded.meta["original_filename"] == "m.csv"  # 元数据以落盘为准
