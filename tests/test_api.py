"""api：HTTP 集成测试（TestClient + 临时数据集目录）。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from typhoon_track.api.app import create_app
from typhoon_track.service.datasets import DatasetStore

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "demo_src"
MEAN = DEMO / "sample_synthetic_ensemble_mean.csv"
REAL = DEMO / "FNV3P2_2026_10_14T00_00_paired (1).csv"

OBS_CSV = (
    "storm_name,valid_time,lat,lon,vmax_kt,minimum_sea_level_pressure_hpa\n"
    "DEMO,2026-07-01T00:00:00Z,18.2,131.5,40,998\n"
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


def test_index_page_renders(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "台风轨迹工作台" in response.text
    # 瓦片配置注入页面（来自根目录 config.toml，不硬编码）
    assert "server.arcgisonline.com" in response.text
    assert "/static/vendor/leaflet.js" in response.text
    # M4 曲线联动：图表容器与 uPlot vendor 引用
    assert 'id="chart"' in response.text
    assert "/static/vendor/uPlot.iife.min.js" in response.text
    assert "/static/vendor/uPlot.min.css" in response.text
    # M5d：统计配置注入（分级/堆叠层级来自 core.ensemble 单源）+ p 控件 + 统计图表卡
    assert "window.STATS_CONFIG" in response.text
    assert "stackBottomUp" in response.text
    assert 'id="p-select"' in response.text
    assert 'id="p-apply"' in response.text
    for card in ("pressure-wrap", "stack-wrap", "radius-wrap"):
        assert f'id="{card}"' in response.text


def test_static_vendor_served(client: TestClient) -> None:
    js = client.get("/static/vendor/leaflet.js")
    assert js.status_code == 200
    assert "javascript" in js.headers["content-type"]
    assert "Leaflet 1.9.4" in js.text
    css = client.get("/static/vendor/leaflet.css")
    assert css.status_code == 200
    own = client.get("/static/app.js")
    assert own.status_code == 200
    uplot_js = client.get("/static/vendor/uPlot.iife.min.js")
    assert uplot_js.status_code == 200
    assert "uPlot" in uplot_js.text
    assert client.get("/static/vendor/uPlot.min.css").status_code == 200


def test_upload_forecast_and_query_tracks(client: TestClient) -> None:
    response = _upload(client, "mean.csv", MEAN.read_bytes())
    assert response.status_code == 201
    meta = response.json()
    assert meta["kind"] == "forecast"
    assert meta["rows"] == 5

    tracks = client.get(f"/api/datasets/{meta['dataset_id']}/tracks")
    assert tracks.status_code == 200
    body = tracks.json()
    assert body["count"] == 5
    # 缺失字段保真：首行 SW 风圈缺失 → 显式 null（不臆造 0）
    assert body["rows"][0]["r34_sw"] is None
    # 未按气旋筛选 → 无洋区（M9 storm_basin）
    assert body["storm_basin"] is None

    filtered = client.get(
        f"/api/datasets/{meta['dataset_id']}/tracks",
        params={"storm": "syn202601", "at_lead_hours": 48},
    )
    body = filtered.json()
    assert body["count"] == 1
    assert body["rows"][0]["wind"] == 94
    # 结构化回显：字段齐全，未提供的条件为 null
    assert body["filters"]["storm"] == "syn202601"
    assert body["filters"]["at_lead_hours"] == 48
    assert body["filters"]["member"] is None
    # 合成前缀 SYN 不在 ATCF 码表 → 未识别为 null（不臆造洋区）
    assert body["storm_basin"] is None


def test_openapi_documents_structured_contracts(client: TestClient) -> None:
    document = client.get("/openapi.json").json()
    schemas = document["components"]["schemas"]
    for name in ("DatasetMeta", "DatasetListResponse", "TrackFilters",
                 "TrackPoint", "TracksResponse", "Place", "PlacesResponse"):
        assert name in schemas, f"OpenAPI 缺少契约模型: {name}"
    assert "storm" in schemas["TrackPoint"]["properties"]
    # M9：洋区字段进契约文档（气旋侧前缀直映 + 地点侧 8 码）
    assert "storm_basin" in schemas["TracksResponse"]["properties"]
    assert "basin" in schemas["Place"]["properties"]


def test_upload_observation_kind(client: TestClient) -> None:
    response = _upload(client, "obs.csv", OBS_CSV.encode(), kind="observation")
    assert response.status_code == 201
    assert response.json()["kind"] == "observation"


def test_upload_invalid_csv_returns_400(client: TestClient) -> None:
    response = _upload(client, "bad.csv", b"not,a,csv\n1,2\n")
    assert response.status_code == 400
    assert response.json()["detail"]


def test_upload_unknown_kind_returns_400(client: TestClient) -> None:
    response = _upload(client, "mean.csv", MEAN.read_bytes(), kind="bogus")
    assert response.status_code == 400
    assert "未知 kind" in response.json()["detail"]


def test_unknown_dataset_returns_404(client: TestClient) -> None:
    assert client.get("/api/datasets/nope").status_code == 404
    assert client.get("/api/datasets/nope/tracks").status_code == 404


def test_list_datasets(client: TestClient) -> None:
    _upload(client, "mean.csv", MEAN.read_bytes())
    _upload(client, "obs.csv", OBS_CSV.encode(), kind="observation")
    body = client.get("/api/datasets").json()["datasets"]
    assert len(body) == 2
    assert {d["kind"] for d in body} == {"forecast", "observation"}


def test_tracks_no_match_returns_400(client: TestClient) -> None:
    meta = _upload(client, "mean.csv", MEAN.read_bytes()).json()
    response = client.get(
        f"/api/datasets/{meta['dataset_id']}/tracks", params={"storm": "NOPE"}
    )
    assert response.status_code == 400
    assert "未找到气旋" in response.json()["detail"]


@pytest.mark.skipif(not REAL.is_file(), reason="原始 Weather Lab CSV 未放入 demo_src")
def test_real_upload_and_query(client: TestClient) -> None:
    response = _upload(client, REAL.name, REAL.read_bytes())
    assert response.status_code == 201
    meta = response.json()
    assert meta["rows"] == 4592
    assert len(meta["summary"]["storms"]) == 4

    wp = client.get(
        f"/api/datasets/{meta['dataset_id']}/tracks", params={"storm": "WP962026"}
    ).json()
    assert wp["count"] == 2451  # 全部 50 个成员（意面图取数路径）
    assert wp["storm_basin"] == "WP"  # M9：真实 track_id 前缀直映

    ep = client.get(
        f"/api/datasets/{meta['dataset_id']}/tracks",
        params={"storm": "EP202026", "member": "0", "at_lead_hours": 24},
    ).json()
    assert ep["count"] == 1
    assert ep["rows"][0]["lat"] == pytest.approx(19.77, abs=0.01)
    assert ep["rows"][0]["lon_signed"] == pytest.approx(-108.44, abs=0.01)
    assert ep["rows"][0]["wind"] == pytest.approx(57.4, abs=0.1)
    assert ep["storm_basin"] == "EP"
