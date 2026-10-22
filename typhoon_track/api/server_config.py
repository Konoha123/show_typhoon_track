"""Web 服务监听配置（configs/server.json，pydantic 解析；供根目录 app.py 薄封装消费）。"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError, field_validator

from .app import PROJECT_ROOT


class ServerConfig(BaseModel):
    """服务监听配置：host 仅非空校验（uvicorn 自身解析失败会报错），port ∈ [1, 65535]。"""

    host: str
    port: int = Field(ge=1, le=65535)

    @field_validator("host")
    @classmethod
    def _host_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("host 不能为空")
        return value

    @classmethod
    def load(cls, config_path: str | Path | None = None) -> ServerConfig:
        """读取 configs/server.json；缺文件即报错（不回退默认值、不自动生成模板）。"""
        path = Path(config_path) if config_path is not None else PROJECT_ROOT / "configs" / "server.json"
        if not path.is_file():
            raise ValueError(f"服务配置文件不存在: {path}")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ValueError(f"服务配置文件不是合法 JSON: {path}（{error.msg}，第 {error.lineno} 行）") from error
        try:
            return cls.model_validate(data)
        except ValidationError as error:
            raise ValueError(f"服务配置校验失败: {path}\n{error}") from error
