"""页面路由（M3 地图工作台首页；数据集上传与选择在同一页面完成）。

M5：注入集合统计配置（强度分级/堆叠层级/p 档位/低分母阈值），单一事实来源为
core.ensemble 常量，前端不再硬编码（口径见 docs/M5口径验证记录_20261016.md）。
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from typhoon_track.core import (
    CATEGORY_STACK_BOTTOM_UP,
    DEFAULT_P_VALUES,
    DISSIPATED_COLOR,
    DISSIPATED_KEY,
    DISSIPATED_LABEL,
    LOW_DENOMINATOR_FRACTION,
    UNKNOWN_COLOR,
    UNKNOWN_KEY,
    WIND_CATEGORIES,
)


def stats_config_json() -> str:
    """由 core.ensemble 常量生成注入页面的统计配置（TD 下限 -inf 以 null 传输）。"""
    payload = {
        "categories": [
            {
                "key": c.key,
                "label": c.label,
                "minKt": None if c.min_kt == -math.inf else c.min_kt,
                "color": c.color,
            }
            for c in WIND_CATEGORIES
        ],
        "stackBottomUp": list(CATEGORY_STACK_BOTTOM_UP),
        "dissipated": {"key": DISSIPATED_KEY, "label": DISSIPATED_LABEL, "color": DISSIPATED_COLOR},
        "unknown": {"key": UNKNOWN_KEY, "label": "风速缺失", "color": UNKNOWN_COLOR},
        "pValues": list(DEFAULT_P_VALUES),
        "lowDenominatorFraction": LOW_DENOMINATOR_FRACTION,
    }
    return json.dumps(payload, ensure_ascii=False)


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
            {"datasets": store.list(), "tile_config": tile_json, "stats_config": stats_config_json()},
        )
