"""FastAPI 应用工厂与默认实例（uvicorn typhoon_track.api.app:app）。"""

from __future__ import annotations

import os
import tomllib
from collections.abc import MutableMapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Response
from fastapi.staticfiles import StaticFiles

from typhoon_track.service.datasets import DatasetStore

from . import routes_api, routes_pages

WEB_DIR = Path(__file__).resolve().parents[1] / "web"
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class NoCacheStaticFiles(StaticFiles):
    """静态资源显式 no-cache：强制浏览器每次再验证（ETag 命中回 304）。

    M8-R1 根因修复：StaticFiles 默认不带 Cache-Control，浏览器对子资源启用
    启发式缓存，更新 CSS/JS 后出现「新 HTML + 旧样式」组合（峰值栏常态展开、
    按钮占栏、地图被挤为零宽）。本机单人使用，304 再验证代价可忽略。
    类型经 fastapi 再导出/标准库别名书写，不直接依赖传递包 starlette（deptry DEP003）。
    """

    def file_response(
        self,
        full_path: os.PathLike[str],
        stat_result: os.stat_result,
        scope: MutableMapping[str, Any],
        status_code: int = 200,
    ) -> Response:
        response = super().file_response(full_path, stat_result, scope, status_code)
        response.headers["Cache-Control"] = "no-cache"
        return response


@dataclass(frozen=True)
class TileConfig:
    """瓦片配置（来自 configs/tiles.toml，注入页面）。"""

    url_template: str
    attribution: str
    max_zoom: int


def load_tile_config(config_path: str | Path | None = None) -> TileConfig:
    """读取 configs/tiles.toml 的 [tiles]；模板缺 {z}/{x}/{y} 占位符即报错，防止静默错配。"""
    path = Path(config_path) if config_path is not None else PROJECT_ROOT / "configs" / "tiles.toml"
    if not path.is_file():
        raise ValueError(f"瓦片配置文件不存在: {path}")
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    tiles = data.get("tiles", {})
    url_template = str(tiles.get("url_template", ""))
    if not url_template or not all(tag in url_template for tag in ("{z}", "{x}", "{y}")):
        raise ValueError(f"tiles.toml [tiles] url_template 需含 {{z}}/{{x}}/{{y}} 占位符: {url_template!r}")
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
    app.mount("/static", NoCacheStaticFiles(directory=WEB_DIR / "static"), name="static")
    routes_api.register(app)
    routes_pages.register(app, templates_dir=WEB_DIR / "templates")
    return app


app = create_app()
