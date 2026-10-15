"""页面路由（M2 最小管理页：上传 + 数据集列表；M3 落地地图页）。"""

from __future__ import annotations

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
        return templates.TemplateResponse(
            request, "index.html", {"datasets": store.list()}
        )
