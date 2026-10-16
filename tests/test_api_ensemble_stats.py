"""api：ensemble-stats 聚合端点集成测试（TestClient + 临时数据集目录）。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from typhoon_track.api.app import create_app
from typhoon_track.service.datasets import DatasetStore

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "demo_src"
MEMBERS = DEMO / "sample_synthetic_ensemble.csv"

OBS_CSV = (
    "storm_name,valid_time,lat,lon,vmax_kt,minimum_sea_level_pressure_hpa\n"
    "DEMO,2026-07-01T00:00:00Z,18.2,131.5,40,998\n"
)
# 双气旋 + 双起报时次的最小预报帧（用于校验拒绝混合统计）
MULTI_CSV = (
    "track_id,ensemble_member,init_time,valid_time,lead_time_hours,lat,lon,"
    "maximum_sustained_wind_speed_knots,minimum_sea_level_pressure_hpa\n"
    "SYN202601,01,2026-07-01T00:00:00Z,2026-07-01T00:00:00Z,0,17.5,132.0,35,1000\n"
    "SYN202601,01,2026-07-02T00:00:00Z,2026-07-02T00:00:00Z,0,17.6,132.1,36,999\n"
    "SYN202602,01,2026-07-01T00:00:00Z,2026-07-01T00:00:00Z,0,8.0,140.0,25,1006\n"
)


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(DatasetStore(tmp_path)))


def _upload(client: TestClient, name: str, content: bytes, kind: str = "forecast"):
    return client.post(
        "/api/datasets",
        files={"file": (name, content, "text/csv")},
        data={"kind": kind},
    )


def _stats(client: TestClient, dataset_id: str, **params) -> dict:
    response = client.get(f"/api/datasets/{dataset_id}/ensemble-stats", params=params)
    assert response.status_code == 200
    return response.json()


def test_ensemble_stats_leads_and_values(client: TestClient) -> None:
    meta = _upload(client, "members.csv", MEMBERS.read_bytes()).json()
    body = _stats(client, meta["dataset_id"], storm="SYN202601")
    assert body["kind"] == "forecast"
    assert body["storm"] == "SYN202601"
    assert body["init"] is None
    assert body["count"] == 3
    assert body["p_values"] == [40, 50, 60, 70, 80, 90, 100]
    leads = body["leads"]
    assert [lead["lead_h"] for lead in leads] == [0.0, 24.0, 48.0]
    first = leads[0]
    assert first["n_total"] == 2
    assert first["n_present"] == 2
    assert first["mean_wind"] == pytest.approx(32.5)  # (35 + 30) / 2
    assert first["mean_pressure"] == pytest.approx(1001.0)
    assert first["valid"] is not None and first["valid"].startswith("2026-07-01T00:00:00")
    # 概率半径档位齐全且单调：p=100 >= p=40
    assert set(first["radius_km"].keys()) == {"40", "50", "60", "70", "80", "90", "100"}
    assert first["radius_km"]["100"] >= first["radius_km"]["40"] >= 0.0
    # 强度分布：lead 0 成员 01=35kt(TS)、02=30kt(TD)；无消散
    assert first["category_counts"]["TS"] == 1
    assert first["category_counts"]["TD"] == 1
    assert first["category_counts"]["DISSIPATED"] == 0
    assert first["low_denominator"] is False


def test_ensemble_stats_openapi_contract(client: TestClient) -> None:
    document = client.get("/openapi.json").json()
    schemas = document["components"]["schemas"]
    for name in ("EnsembleLeadStats", "EnsembleStatsResponse"):
        assert name in schemas, f"OpenAPI 缺少契约模型: {name}"
    lead_properties = schemas["EnsembleLeadStats"]["properties"]
    for field in ("n_present", "radius_km", "category_counts", "low_denominator"):
        assert field in lead_properties


def test_ensemble_stats_unknown_dataset_404(client: TestClient) -> None:
    response = client.get("/api/datasets/nope/ensemble-stats")
    assert response.status_code == 404


def test_ensemble_stats_observation_kind_400(client: TestClient) -> None:
    meta = _upload(client, "obs.csv", OBS_CSV.encode(), kind="observation").json()
    response = client.get(f"/api/datasets/{meta['dataset_id']}/ensemble-stats")
    assert response.status_code == 400
    assert "仅适用于预报数据集" in response.json()["detail"]


def test_ensemble_stats_storm_no_match_400(client: TestClient) -> None:
    meta = _upload(client, "members.csv", MEMBERS.read_bytes()).json()
    response = client.get(
        f"/api/datasets/{meta['dataset_id']}/ensemble-stats", params={"storm": "NOPE"}
    )
    assert response.status_code == 400
    assert "未找到气旋" in response.json()["detail"]


def test_ensemble_stats_rejects_mixed_storms_and_inits(client: TestClient) -> None:
    meta = _upload(client, "multi.csv", MULTI_CSV.encode()).json()
    without_storm = client.get(f"/api/datasets/{meta['dataset_id']}/ensemble-stats")
    assert without_storm.status_code == 400
    assert "检测到多个 storm" in without_storm.json()["detail"]
    mixed_init = client.get(
        f"/api/datasets/{meta['dataset_id']}/ensemble-stats", params={"storm": "SYN202601"}
    )
    assert mixed_init.status_code == 400
    assert "检测到多个 init" in mixed_init.json()["detail"]
    # 指定 storm + init 后正常返回单一 (storm, init) 统计
    body = _stats(
        client, meta["dataset_id"], storm="SYN202601", init="2026-07-01T00:00:00Z"
    )
    assert body["count"] == 1
    assert body["leads"][0]["lead_h"] == 0.0
    assert body["leads"][0]["mean_wind"] == pytest.approx(35.0)
