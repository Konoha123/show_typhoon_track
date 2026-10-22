"""api.app.load_tile_config：瓦片配置加载与防错配置检查；/static 静态资源缓存头。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from typhoon_track.api.app import PROJECT_ROOT, create_app, load_tile_config
from typhoon_track.service.datasets import DatasetStore


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(DatasetStore(tmp_path)))


def test_load_repo_default_config() -> None:
    config = load_tile_config()
    assert config.url_template.startswith("https://")
    assert "{z}" in config.url_template and "{x}" in config.url_template and "{y}" in config.url_template
    assert config.attribution
    assert config.max_zoom >= 1
    assert (PROJECT_ROOT / "configs" / "tiles.toml").is_file()


def test_load_from_custom_path(tmp_path: Path) -> None:
    custom = tmp_path / "tiles.toml"
    custom.write_text(
        '[tiles]\nurl_template = "https://example.com/{z}/{y}/{x}"\n'
        'attribution = "test"\nmax_zoom = 12\n',
        encoding="utf-8",
    )
    config = load_tile_config(custom)
    assert config.url_template == "https://example.com/{z}/{y}/{x}"
    assert config.max_zoom == 12


def test_missing_config_file(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="瓦片配置文件不存在"):
        load_tile_config(tmp_path / "nope.toml")


def test_template_without_placeholders_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "bad.toml"
    bad.write_text('[tiles]\nurl_template = "https://example.com/tiles"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="占位符"):
        load_tile_config(bad)


def test_static_assets_sent_no_cache(client) -> None:
    """M8-R1：/static 显式 no-cache，杜绝浏览器启发式缓存取到旧 CSS/JS（ETag 仍可 304）。"""
    response = client.get("/static/style.css")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers.get("etag")  # 再验证凭据仍在，未改动时回 304
