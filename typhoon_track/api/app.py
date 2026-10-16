"""FastAPI 应用工厂与默认实例（uvicorn typhoon_track.api.app:app）。"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from typhoon_track.service.datasets import DatasetStore

from . import routes_api, routes_pages

WEB_DIR = Path(__file__).resolve().parents[1] / "web"
PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class TileConfig:
    """瓦片配置（来自根目录 config.toml，注入页面）。"""

    url_template: str
    attribution: str
    max_zoom: int


def load_tile_config(config_path: str | Path | None = None) -> TileConfig:
    """读取 config.toml 的 [tiles]；模板缺 {z}/{x}/{y} 占位符即报错，防止静默错配。"""
    path = Path(config_path) if config_path is not None else PROJECT_ROOT / "config.toml"
    if not path.is_file():
        raise ValueError(f"瓦片配置文件不存在: {path}")
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    tiles = data.get("tiles", {})
    url_template = str(tiles.get("url_template", ""))
    if not url_template or not all(tag in url_template for tag in ("{z}", "{x}", "{y}")):
        raise ValueError(f"config.toml [tiles] url_template 需含 {{z}}/{{x}}/{{y}} 占位符: {url_template!r}")
    return TileConfig(
        url_template=url_template,
        attribution=str(tiles.get("attribution", "")),
        max_zoom=int(tiles.get("max_zoom", 18)),
    )


def default_store() -> DatasetStore:
    """默认数据集目录：仓库根目录下 uploads/（.gitignore 已忽略）。"""
    return DatasetStore(PROJECT_ROOT / "uploads")


def default_places_path() -> Path:
    """默认预存地点文件：仓库根目录下 places/places.csv（用户手工维护，git 忽略）。"""
    return PROJECT_ROOT / "places" / "places.csv"


def create_app(
    store: DatasetStore | None = None, places_path: str | Path | None = None
) -> FastAPI:
    app = FastAPI(title="typhoon-track", version="0.1.0")
    app.state.store = store if store is not None else default_store()
    app.state.tile_config = load_tile_config()
    app.state.places_path = Path(places_path) if places_path is not None else default_places_path()
    app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")
    routes_api.register(app)
    routes_pages.register(app, templates_dir=WEB_DIR / "templates")
    return app


app = create_app()
