"""api：peak-stats 终生峰值统计端点集成测试（TestClient + 临时数据集目录；含 WNV3 真实抽核）。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from typhoon_track.api.app import create_app
from typhoon_track.service.datasets import DatasetStore

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "demo_src"
MEMBERS = DEMO / "sample_synthetic_ensemble.csv"
REAL = DEMO / "WNV3_2026_10_15T18_00_paired_ensemble.csv"

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
# 成员 03 的风速整列缺失（哨兵），气压正常；成员 01/02 正常
SENTINEL_CSV = (
    "track_id,ensemble_member,init_time,valid_time,lead_time_hours,lat,lon,"
    "maximum_sustained_wind_speed_knots,minimum_sea_level_pressure_hpa\n"
    "SYN202601,01,2026-07-01T00:00:00Z,2026-07-01T00:00:00Z,0,17.5,132.0,35,1000\n"
    "SYN202601,01,2026-07-01T00:00:00Z,2026-07-02T00:00:00Z,24,18.0,131.0,45,990\n"
    "SYN202601,02,2026-07-01T00:00:00Z,2026-07-01T00:00:00Z,0,17.2,132.6,30,1002\n"
    "SYN202601,03,2026-07-01T00:00:00Z,2026-07-01T00:00:00Z,0,17.0,132.8,,1005\n"
    "SYN202601,03,2026-07-01T00:00:00Z,2026-07-02T00:00:00Z,24,17.4,132.4,,1004\n"
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
    response = client.get(f"/api/datasets/{dataset_id}/peak-stats", params=params)
    assert response.status_code == 200
    return response.json()


def test_peak_stats_members_and_aggregates(client: TestClient) -> None:
    meta = _upload(client, "members.csv", MEMBERS.read_bytes()).json()
    body = _stats(client, meta["dataset_id"], storm="SYN202601")
    assert body["kind"] == "forecast"
    assert body["storm"] == "SYN202601"
    assert body["init"] is None
    assert body["n_total"] == 2
    # 每成员峰值：01 风速 70@48h / 气压 972@48h；02 风速 60@48h / 气压 980@48h
    by_member = {m["member"]: m for m in body["members"]}
    assert [m["member"] for m in body["members"]] == ["01", "02"]  # 数值序
    assert by_member["01"]["peak_wind"] == pytest.approx(70.0)
    assert by_member["01"]["peak_wind_lead_h"] == pytest.approx(48.0)
    assert by_member["01"]["peak_pressure"] == pytest.approx(972.0)
    assert by_member["01"]["peak_pressure_lead_h"] == pytest.approx(48.0)
    assert by_member["02"]["peak_wind"] == pytest.approx(60.0)
    assert by_member["02"]["peak_pressure"] == pytest.approx(980.0)
    # 聚合：风速 [60,70] 上中位=70、平均 65；气压 [972,980] 上中位=980、平均 976
    assert body["wind"] == {"n_valid": 2, "median": pytest.approx(70.0), "mean": pytest.approx(65.0)}
    assert body["pressure"] == {
        "n_valid": 2,
        "median": pytest.approx(980.0),
        "mean": pytest.approx(976.0),
    }


def test_peak_stats_sentinel_member_excluded_per_metric(client: TestClient) -> None:
    meta = _upload(client, "sentinel.csv", SENTINEL_CSV.encode()).json()
    body = _stats(client, meta["dataset_id"])
    assert body["n_total"] == 3
    by_member = {m["member"]: m for m in body["members"]}
    assert by_member["03"]["peak_wind"] is None  # 哨兵：前端显示"-"
    assert by_member["03"]["peak_wind_lead_h"] is None
    assert by_member["03"]["peak_pressure"] == pytest.approx(1004.0)  # 气压正常参与
    # 两指标分母独立：风速剔除哨兵（[30,45] 上中位 45），气压全员（[990,1002,1004] 正中 1002）
    assert body["wind"]["n_valid"] == 2
    assert body["wind"]["median"] == pytest.approx(45.0)
    assert body["pressure"]["n_valid"] == 3
    assert body["pressure"]["median"] == pytest.approx(1002.0)


def test_peak_stats_openapi_contract(client: TestClient) -> None:
    document = client.get("/openapi.json").json()
    schemas = document["components"]["schemas"]
    for name in ("PeakMetricStats", "MemberPeak", "PeakStatsResponse"):
        assert name in schemas, f"OpenAPI 缺少契约模型: {name}"
    member_properties = schemas["MemberPeak"]["properties"]
    for field in ("peak_wind", "peak_wind_lead_h", "peak_pressure", "peak_pressure_lead_h"):
        assert field in member_properties


def test_peak_stats_unknown_dataset_404(client: TestClient) -> None:
    response = client.get("/api/datasets/nope/peak-stats")
    assert response.status_code == 404


def test_peak_stats_observation_kind_400(client: TestClient) -> None:
    meta = _upload(client, "obs.csv", OBS_CSV.encode(), kind="observation").json()
    response = client.get(f"/api/datasets/{meta['dataset_id']}/peak-stats")
    assert response.status_code == 400
    assert "仅适用于预报数据集" in response.json()["detail"]


def test_peak_stats_rejects_mixed_storms_and_inits(client: TestClient) -> None:
    meta = _upload(client, "multi.csv", MULTI_CSV.encode()).json()
    without_storm = client.get(f"/api/datasets/{meta['dataset_id']}/peak-stats")
    assert without_storm.status_code == 400
    assert "检测到多个 storm" in without_storm.json()["detail"]
    mixed_init = client.get(
        f"/api/datasets/{meta['dataset_id']}/peak-stats", params={"storm": "SYN202601"}
    )
    assert mixed_init.status_code == 400
    assert "检测到多个 init" in mixed_init.json()["detail"]
    # 指定 storm + init 后正常返回单一 (storm, init) 统计
    body = _stats(client, meta["dataset_id"], storm="SYN202601", init="2026-07-01T00:00:00Z")
    assert body["n_total"] == 1
    assert body["members"][0]["peak_wind"] == pytest.approx(35.0)


@pytest.mark.skipif(not REAL.is_file(), reason="WNV3 配对 CSV 未放入 demo_src，跳过真实抽核")
def test_peak_stats_real_wnv3_locked_values(client: TestClient) -> None:
    meta = _upload(client, "wnv3.csv", REAL.read_bytes()).json()
    body = _stats(client, meta["dataset_id"], storm="WP292026")
    # 锁定值与 core 真实复算一致（tests/test_core_peak.py 独立 pandas 复算锁定）
    assert body["n_total"] == 64
    assert body["wind"]["n_valid"] == 64
    assert body["wind"]["median"] == pytest.approx(157.6)
    assert body["wind"]["mean"] == pytest.approx(156.5546875)
    assert body["pressure"]["median"] == pytest.approx(902.2)
    assert body["pressure"]["mean"] == pytest.approx(902.259375)
    # 成员数值序 + 首成员哨兵语义不触发（WNV3 全员风压齐备）
    assert len(body["members"]) == 64
    assert body["members"][0]["member"] == "0"
    assert body["members"][63]["member"] == "63"
    # 最强成员 41：风速 168.6@78h、气压 891.4@78h（core 真实复算锁定）
    strongest = body["members"][41]
    assert strongest["peak_wind"] == pytest.approx(168.6)
    assert strongest["peak_wind_lead_h"] == pytest.approx(78.0)
    assert strongest["peak_pressure"] == pytest.approx(891.4)
    assert strongest["peak_pressure_lead_h"] == pytest.approx(78.0)
