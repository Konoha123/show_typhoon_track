"""FastAPI 应用工厂与默认实例（uvicorn typhoon_track.api.app:app）。"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI

from typhoon_track.service.datasets import DatasetStore

from . import routes_api, routes_pages

WEB_DIR = Path(__file__).resolve().parents[1] / "web"


def default_store() -> DatasetStore:
    """默认数据集目录：仓库根目录下 uploads/（.gitignore 已忽略）。"""
    return DatasetStore(Path(__file__).resolve().parents[2] / "uploads")


def create_app(store: DatasetStore | None = None) -> FastAPI:
    app = FastAPI(title="typhoon-track", version="0.1.0")
    app.state.store = store if store is not None else default_store()
    routes_api.register(app)
    routes_pages.register(app, templates_dir=WEB_DIR / "templates")
    return app


app = create_app()
