"""页面路由（M3 地图工作台首页；数据集上传与选择在同一页面完成）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates


def register(app: FastAPI, *, templates_dir: Path) -> None:
    templates = Jinja2Templates(directory=str(templates_dir))

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> HTMLResponse:
        store: Any = app.state.store
        tile_config = app.state.tile_config
        tile_json = json.dumps(
            {
                "urlTemplate": tile_config.url_template,
                "attribution": tile_config.attribution,
                "maxZoom": tile_config.max_zoom,
            },
            ensure_ascii=False,
        )
        return templates.TemplateResponse(
            request,
            "index.html",
            {"datasets": store.list(), "tile_config": tile_json},
        )
