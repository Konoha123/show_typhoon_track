"""api：impact-stats 端点集成测试（TestClient + 临时数据集目录；含 WNV3 真实抽核）。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from typhoon_track.api.app import create_app
from typhoon_track.service.datasets import DatasetStore

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "demo_src"
MEMBERS = DEMO / "sample_synthetic_ensemble.csv"  # 无风圈列：用于显式拒绝
REAL = DEMO / "WNV3_2026_10_15T18_00_paired_ensemble.csv"

_RADIUS_COLS = ",".join(
    f"radius_{speed}_knot_winds_{quad}_km"
    for speed in (34, 50, 64)
    for quad in ("ne", "se", "sw", "nw")
)

IMPACT_CSV = (
    "track_id,ensemble_member,init_time,valid_time,lead_time_hours,lat,lon,"
    "maximum_sustained_wind_speed_knots,minimum_sea_level_pressure_hpa,"
    f"{_RADIUS_COLS}\n"
    "SYN202601,01,2026-07-01T00:00:00Z,2026-07-01T00:00:00Z,0,17.5,132.0,35,1000,"
    "100,0,0,0,60,0,0,0,30,0,0,0\n"
    "SYN202601,01,2026-07-01T00:00:00Z,2026-07-02T00:00:00Z,24,18.5,132.5,34,999,"
    "80,0,0,0,50,0,0,0,0,0,0,0\n"
    "SYN202601,02,2026-07-01T00:00:00Z,2026-07-01T00:00:00Z,0,17.0,131.5,30,1002,"
    "0,0,0,0,0,0,0,0,0,0,0,0\n"
    "SYN202601,02,2026-07-01T00:00:00Z,2026-07-02T00:00:00Z,24,18.0,132.0,31,1001,"
    "0,0,0,0,0,0,0,0,0,0,0,0\n"
)

# 双气旋（含风圈列）：用于校验拒绝混合统计
MULTI_IMPACT_CSV = (
    "track_id,ensemble_member,init_time,valid_time,lead_time_hours,lat,lon,"
    "maximum_sustained_wind_speed_knots,minimum_sea_level_pressure_hpa,"
    f"{_RADIUS_COLS}\n"
    "SYN202601,01,2026-07-01T00:00:00Z,2026-07-01T00:00:00Z,0,17.5,132.0,35,1000,"
    "100,0,0,0,60,0,0,0,30,0,0,0\n"
    "SYN202602,01,2026-07-01T00:00:00Z,2026-07-01T00:00:00Z,0,8.0,140.0,25,1006,"
    "0,0,0,0,0,0,0,0,0,0,0,0\n"
)

OBS_CSV = (
    "storm_name,valid_time,lat,lon,vmax_kt,minimum_sea_level_pressure_hpa\n"
    "DEMO,2026-07-01T00:00:00Z,18.2,131.5,40,998\n"
)


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(DatasetStore(tmp_path)))


def _upload(client: TestClient, name: str, content: bytes, kind: str = "forecast"):
    return client.post(
        "/api/datasets", files={"file": (name, content, "text/csv")}, data={"kind": kind}
    )


def _impact(client: TestClient, dataset_id: str, **params):
    return client.get(f"/api/datasets/{dataset_id}/impact-stats", params=params)


def test_impact_stats_thresholds_and_closest(client: TestClient) -> None:
    meta = _upload(client, "impact.csv", IMPACT_CSV.encode()).json()
    response = _impact(client, meta["dataset_id"], lat=17.8, lon=132.4)
    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "forecast"
    assert body["lat"] == 17.8 and body["lon"] == 132.4
    by_key = {t["threshold_kt"]: t for t in body["thresholds"]}
    # 成员 01 lead 0：点在其 NE ~52 km（r34_ne=100 命中、r50_ne=60 命中、r64_ne=30 未命中）
    assert by_key[34]["hit_members"] == 1 and by_key[34]["total_members"] == 2
    assert by_key[34]["fraction"] == pytest.approx(0.5)
    assert by_key[50]["hit_members"] == 1
    assert by_key[64]["hit_members"] == 0
    assert by_key[34]["label"] == "烈风（风速≥34 kt）"
    assert by_key[64]["label"] == "飓风（风速≥64 kt）"
    # M7d：核心强风区（距离≤RMW）；IMPACT_CSV 无 rmw 列 → 全不命中但留在分母
    core = body["core_wind"]
    assert core["label"] == "核心强风区（距离≤RMW）"
    assert core["hit_members"] == 0 and core["total_members"] == 2
    assert core["fraction"] == pytest.approx(0.0)
    closest = body["closest"]
    assert closest is not None
    # lead 24 均值位置 (≈18.25, 132.25) 距点 ~52.6 km，近于 lead 0 的 ~92 km
    assert closest["lead_h"] == 24.0
    assert closest["valid"].startswith("2026-07-02T00:00:00")
    assert 50.0 < closest["distance_km"] < 55.0
    assert 330.0 < closest["bearing_deg"] < 350.0
    assert closest["compass"] == "NNW"
    assert closest["mean_wind"] == pytest.approx(32.5)
    assert closest["mean_pressure"] == pytest.approx(1000.0)
    # M11a：closest 非 None 时 closest_note 为 None（契约字段存在且语义正确）
    assert body["closest_note"] is None


def test_impact_stats_closest_note_truncated_empty(client: TestClient) -> None:
    # M11a：首时次即低分母（lead 0 仅 1/4 成员在场）→ closest=null + 截断内无有效时次文案
    csv = (
        "track_id,ensemble_member,init_time,valid_time,lead_time_hours,lat,lon,"
        "maximum_sustained_wind_speed_knots,minimum_sea_level_pressure_hpa,"
        f"{_RADIUS_COLS}\n"
        "SYN202601,01,2026-07-01T00:00:00Z,2026-07-01T00:00:00Z,0,17.5,132.0,35,1000,"
        "100,0,0,0,60,0,0,0,30,0,0,0\n"
        "SYN202601,02,2026-07-01T00:00:00Z,2026-07-02T00:00:00Z,24,18.0,132.0,30,1002,"
        "0,0,0,0,0,0,0,0,0,0,0,0\n"
        "SYN202601,03,2026-07-01T00:00:00Z,2026-07-02T00:00:00Z,24,18.1,132.1,30,1002,"
        "0,0,0,0,0,0,0,0,0,0,0,0\n"
        "SYN202601,04,2026-07-01T00:00:00Z,2026-07-02T00:00:00Z,24,18.2,132.2,30,1002,"
        "0,0,0,0,0,0,0,0,0,0,0,0\n"
    )
    meta = _upload(client, "low.csv", csv.encode()).json()
    response = _impact(client, meta["dataset_id"], lat=17.5, lon=132.0)
    assert response.status_code == 200
    body = response.json()
    assert body["closest"] is None
    assert "截断内无有效时次" in body["closest_note"]


def test_impact_stats_closest_note_no_mean_position(client: TestClient) -> None:
    # M11a：被查询气旋全程无有效均值位置（另一气旋行保证上传 lat 列校验通过）
    # → closest=null + 全程无均值位置文案（区别于截断原因）
    csv = (
        "track_id,ensemble_member,init_time,valid_time,lead_time_hours,lat,lon,"
        "maximum_sustained_wind_speed_knots,minimum_sea_level_pressure_hpa,"
        f"{_RADIUS_COLS}\n"
        "SYN202601,01,2026-07-01T00:00:00Z,2026-07-01T00:00:00Z,0,17.5,132.0,35,1000,"
        "100,0,0,0,60,0,0,0,30,0,0,0\n"
        "SYN202602,01,2026-07-01T00:00:00Z,2026-07-01T00:00:00Z,0,,,35,1000,"
        "100,0,0,0,60,0,0,0,30,0,0,0\n"
        "SYN202602,01,2026-07-01T00:00:00Z,2026-07-02T00:00:00Z,24,,,34,999,"
        "80,0,0,0,50,0,0,0,0,0,0,0\n"
    )
    meta = _upload(client, "nopos.csv", csv.encode()).json()
    response = _impact(client, meta["dataset_id"], lat=17.5, lon=132.0, storm="SYN202602")
    assert response.status_code == 200
    body = response.json()
    assert body["closest"] is None
    assert "全程无有效均值位置" in body["closest_note"]


def test_impact_stats_openapi_contract(client: TestClient) -> None:
    document = client.get("/openapi.json").json()
    schemas = document["components"]["schemas"]
    for name in ("ImpactThresholdStats", "CoreWindStats", "ClosestApproach", "ImpactStatsResponse"):
        assert name in schemas, f"OpenAPI 缺少契约模型: {name}"
    closest_properties = schemas["ClosestApproach"]["properties"]
    for field in ("distance_km", "bearing_deg", "compass", "mean_wind", "mean_pressure"):
        assert field in closest_properties
    # M11a：closest_note 进契约（closest 为 null 时的原因文案）
    impact_properties = schemas["ImpactStatsResponse"]["properties"]
    assert "closest_note" in impact_properties
    core_properties = schemas["CoreWindStats"]["properties"]
    for field in ("label", "hit_members", "total_members", "fraction"):
        assert field in core_properties


def test_impact_stats_unknown_dataset_404(client: TestClient) -> None:
    assert _impact(client, "nope", lat=10.0, lon=130.0).status_code == 404


def test_impact_stats_observation_kind_400(client: TestClient) -> None:
    meta = _upload(client, "obs.csv", OBS_CSV.encode(), kind="observation").json()
    response = _impact(client, meta["dataset_id"], lat=18.0, lon=131.5)
    assert response.status_code == 400
    assert "仅适用于预报数据集" in response.json()["detail"]


def test_impact_stats_missing_lat_lon_422(client: TestClient) -> None:
    meta = _upload(client, "impact.csv", IMPACT_CSV.encode()).json()
    assert _impact(client, meta["dataset_id"]).status_code == 422


def test_impact_stats_latitude_out_of_range_400(client: TestClient) -> None:
    meta = _upload(client, "impact.csv", IMPACT_CSV.encode()).json()
    response = _impact(client, meta["dataset_id"], lat=100.0, lon=132.4)
    assert response.status_code == 400
    assert "目标纬度超出范围" in response.json()["detail"]


def test_impact_stats_missing_radius_columns_400(client: TestClient) -> None:
    meta = _upload(client, "members.csv", MEMBERS.read_bytes()).json()
    response = _impact(client, meta["dataset_id"], lat=17.5, lon=132.0)
    assert response.status_code == 400
    assert "缺少风圈字段" in response.json()["detail"]
    assert "不提供距离回退" in response.json()["detail"]


def test_impact_stats_rejects_mixed_storms(client: TestClient) -> None:
    meta = _upload(client, "multi.csv", MULTI_IMPACT_CSV.encode()).json()
    response = _impact(client, meta["dataset_id"], lat=17.5, lon=132.0)
    assert response.status_code == 400
    assert "检测到多个 storm" in response.json()["detail"]


@pytest.mark.skipif(not REAL.is_file(), reason="WNV3 配对 CSV 未放入 demo_src，跳过真实抽核")
def test_impact_stats_real_wnv3_spot_check(client: TestClient) -> None:
    meta = _upload(client, "wnv3.csv", REAL.read_bytes()).json()
    response = _impact(client, meta["dataset_id"], lat=19.05, lon=-104.32, storm="EP212026")
    assert response.status_code == 200
    body = response.json()
    by_key = {t["threshold_kt"]: t for t in body["thresholds"]}
    assert by_key[34]["total_members"] == 64
    assert by_key[34]["hit_members"] == 47
    assert by_key[34]["fraction"] == pytest.approx(47 / 64)
    assert by_key[50]["hit_members"] == 7
    assert by_key[64]["hit_members"] == 1
    # M7d 核心强风区锁定值：独立 pandas 复算（裸 CSV + 自写 haversine）得 2/64；
    # 真实文件 rmw 无缺失、39 行 ≤0（ATCF 惯例 0.0=无核心区），均按不命中留在分母
    core = body["core_wind"]
    assert core["hit_members"] == 2 and core["total_members"] == 64
    assert core["fraction"] == pytest.approx(2 / 64)
    closest = body["closest"]
    assert closest["lead_h"] == 54.0
    assert closest["distance_km"] == pytest.approx(140.09, abs=0.05)
    assert closest["bearing_deg"] == pytest.approx(213.58, abs=0.05)
    assert closest["compass"] == "SSW"
