"""api/service：预存地点热读取与 GET /api/places 集成测试（M9 起含 basin 洋区列）。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from typhoon_track.api.app import create_app
from typhoon_track.service.datasets import DatasetStore
from typhoon_track.service.places import load_places

PLACES_CSV = (
    "# 预存地点\n"
    "name,lat,lon,basin,note\n"
    "东京,35.6895,139.6917,WP,关东\n"
    "那霸,26.2124,127.6809,wp\n"  # note 可选；basin 大小写归一
    "# 注释行忽略\n"
)


@pytest.fixture
def places_path(tmp_path: Path) -> Path:
    path = tmp_path / "places" / "places.csv"
    path.parent.mkdir(parents=True)
    path.write_text(PLACES_CSV, encoding="utf-8")
    return path


def make_client(places_path: Path) -> TestClient:
    return TestClient(create_app(DatasetStore(places_path.parent.parent / "uploads"),
                                 places_path=places_path))


def test_places_endpoint_parses_rows(places_path: Path) -> None:
    response = make_client(places_path).get("/api/places")
    assert response.status_code == 200
    payload = response.json()
    assert payload["available"] is True
    assert payload["warnings"] == []
    assert [p["name"] for p in payload["places"]] == ["东京", "那霸"]
    assert payload["places"][0] == {
        "name": "东京", "lat": 35.6895, "lon": 139.6917, "basin": "WP", "note": "关东",
    }
    assert payload["places"][1]["basin"] == "WP"  # 小写归一
    assert payload["places"][1]["note"] is None


def test_places_missing_file_degrades_to_warning(tmp_path: Path) -> None:
    result = load_places(tmp_path / "absent.csv")
    assert result.available is False
    assert result.places == ()
    assert result.warnings and "未找到" in result.warnings[0]
    response = TestClient(
        create_app(DatasetStore(tmp_path / "uploads"), places_path=tmp_path / "absent.csv")
    ).get("/api/places")
    assert response.status_code == 200
    assert response.json()["available"] is False
    assert response.json()["places"] == []


def test_places_bad_rows_skipped_with_warnings(tmp_path: Path) -> None:
    path = tmp_path / "places.csv"
    path.write_text(
        "name,lat,lon,basin,note\n"
        "好点,10.0,20.0,EP,ok\n"
        "坏坐标,abc,20.0,EP\n"
        "越界,91.0,20.0,EP\n"
        "经度越界,10.0,200.0,EP\n"
        ",10.0,20.0,EP\n"
        "缺洋区,11.0,21.0,\n"  # basin 缺失 = 错误数据（M9 决策）
        "非法洋区,12.0,22.0,XX\n"
        "好点,11.0,21.0,EP\n",  # 与首行重名：跳过
        encoding="utf-8",
    )
    payload = TestClient(
        create_app(DatasetStore(tmp_path / "uploads"), places_path=path)
    ).get("/api/places").json()
    assert [p["name"] for p in payload["places"]] == ["好点"]
    assert payload["places"][0]["lat"] == 10.0
    assert payload["places"][0]["basin"] == "EP"
    assert len(payload["warnings"]) == 7  # 非数值/纬度越界/经度越界/空名/缺洋区/非法洋区/重名
    assert any("basin 缺失或非法" in w for w in payload["warnings"])
    assert any("合法值" in w for w in payload["warnings"])


def test_places_missing_basin_column_warns_and_skips_all(tmp_path: Path) -> None:
    # 整表缺 basin 列：非配置错误（200），单条汇总 warning 且地点为空（向后暴露旧格式）
    path = tmp_path / "places.csv"
    path.write_text("name,lat,lon,note\n东京,35.6895,139.6917,关东\n", encoding="utf-8")
    response = TestClient(
        create_app(DatasetStore(tmp_path / "uploads"), places_path=path)
    ).get("/api/places")
    assert response.status_code == 200
    payload = response.json()
    assert payload["available"] is True
    assert payload["places"] == []
    assert len(payload["warnings"]) == 1
    assert "缺少 basin 列" in payload["warnings"][0]


def test_places_missing_columns_rejected(tmp_path: Path) -> None:
    path = tmp_path / "places.csv"
    path.write_text("name,latitude,lon\nA,10,20\n", encoding="utf-8")
    response = TestClient(
        create_app(DatasetStore(tmp_path / "uploads"), places_path=path)
    ).get("/api/places")
    assert response.status_code == 400
    assert "缺少必要列" in response.json()["detail"]


def test_places_basin_na_code_survives_parsing(tmp_path: Path) -> None:
    # M9-R1 回归：pandas 默认 NA 标记字符串集含 "NA"，与北大西洋洋区码冲突——
    # 修复前 basin="NA" 被解析为缺失，38 个 NA 地点整行误跳（用户真实数据首现）
    path = tmp_path / "places.csv"
    path.write_text(
        "name,lat,lon,basin,note\n"
        "迈阿密,25.77427,-80.19366,NA,美国\n"
        "东京,35.6895,139.6917,WP,日本\n",
        encoding="utf-8",
    )
    payload = TestClient(
        create_app(DatasetStore(tmp_path / "uploads"), places_path=path)
    ).get("/api/places").json()
    assert payload["warnings"] == []
    assert [p["basin"] for p in payload["places"]] == ["NA", "WP"]
    assert payload["places"][0]["name"] == "迈阿密"


def test_places_warning_line_numbers_match_original_file(tmp_path: Path) -> None:
    # M9-R1 行号修正：warning 按原文件实际行号报告（注释行与空行跳过不编号）
    path = tmp_path / "places.csv"
    path.write_text(
        "# 首部注释一\n"
        "# 首部注释二\n"
        "name,lat,lon,basin,note\n"
        "好点,10.0,20.0,WP,ok\n"
        "# 中间注释\n"
        "坏洋区,10.0,20.0,XX\n"
        "\n"
        ",11.0,21.0,WP\n",  # 第 8 行空名（第 7 行空行不产出记录、不占编号）
        encoding="utf-8",
    )
    payload = TestClient(
        create_app(DatasetStore(tmp_path / "uploads"), places_path=path)
    ).get("/api/places").json()
    assert [p["name"] for p in payload["places"]] == ["好点"]
    assert len(payload["warnings"]) == 2
    assert payload["warnings"][0].startswith("第 6 行 basin 缺失或非法")
    assert payload["warnings"][1].startswith("第 8 行 name 为空")


def test_places_empty_file_rejected(tmp_path: Path) -> None:
    path = tmp_path / "places.csv"
    path.write_text("", encoding="utf-8")
    response = TestClient(
        create_app(DatasetStore(tmp_path / "uploads"), places_path=path)
    ).get("/api/places")
    assert response.status_code == 400
    assert "为空" in response.json()["detail"]


def test_places_hot_reload_without_restart(places_path: Path) -> None:
    client = make_client(places_path)
    assert [p["name"] for p in client.get("/api/places").json()["places"]] == ["东京", "那霸"]
    places_path.write_text(
        "name,lat,lon,basin\n大阪,34.6937,135.5023,WP\n", encoding="utf-8"
    )
    payload = client.get("/api/places").json()
    assert [p["name"] for p in payload["places"]] == ["大阪"]
