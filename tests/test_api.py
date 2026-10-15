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
    assert "数据集管理" in response.text


def test_upload_forecast_and_query_tracks(client: TestClient) -> None:
    response = _upload(client, "mean.csv", MEAN.read_bytes())
    assert response.status_code == 201
    meta = response.json()
    assert meta["kind"] == "forecast"
    assert meta["rows"] == 5

    tracks = client.get(f"/api/datasets/{meta['dataset_id']}/tracks")
    assert tracks.status_code == 200
    assert tracks.json()["count"] == 5

    filtered = client.get(
        f"/api/datasets/{meta['dataset_id']}/tracks",
        params={"storm": "syn202601", "at_lead_hours": 48},
    )
    body = filtered.json()
    assert body["count"] == 1
    assert body["rows"][0]["wind"] == 94
    assert body["filters"] == {"storm": "syn202601", "at_lead_hours": 48}


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

    ep = client.get(
        f"/api/datasets/{meta['dataset_id']}/tracks",
        params={"storm": "EP202026", "member": "0", "at_lead_hours": 24},
    ).json()
    assert ep["count"] == 1
    assert ep["rows"][0]["lat"] == pytest.approx(19.77, abs=0.01)
    assert ep["rows"][0]["lon_signed"] == pytest.approx(-108.44, abs=0.01)
    assert ep["rows"][0]["wind"] == pytest.approx(57.4, abs=0.1)
