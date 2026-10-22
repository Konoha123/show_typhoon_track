"""api.server_config：服务监听配置 pydantic 解析与防错检查（缺文件/非法 JSON/校验失败）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from typhoon_track.api.server_config import ServerConfig


def test_load_repo_default_config() -> None:
    config = ServerConfig.load()
    assert config.host.strip()
    assert 1 <= config.port <= 65535


def test_load_from_custom_path(tmp_path: Path) -> None:
    custom = tmp_path / "server.json"
    custom.write_text(json.dumps({"host": "0.0.0.0", "port": 9000}), encoding="utf-8")
    config = ServerConfig.load(custom)
    assert config.host == "0.0.0.0"
    assert config.port == 9000


def test_missing_config_file(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="服务配置文件不存在"):
        ServerConfig.load(tmp_path / "nope.json")


def test_invalid_json_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="不是合法 JSON"):
        ServerConfig.load(bad)


def test_port_out_of_range_rejected(tmp_path: Path) -> None:
    for port in (0, 65536):
        custom = tmp_path / f"server_{port}.json"
        custom.write_text(json.dumps({"host": "127.0.0.1", "port": port}), encoding="utf-8")
        with pytest.raises(ValueError, match="服务配置校验失败"):
            ServerConfig.load(custom)


def test_blank_host_rejected(tmp_path: Path) -> None:
    custom = tmp_path / "server.json"
    custom.write_text(json.dumps({"host": "  ", "port": 8000}), encoding="utf-8")
    with pytest.raises(ValueError, match="服务配置校验失败"):
        ServerConfig.load(custom)


def test_missing_host_field_rejected(tmp_path: Path) -> None:
    custom = tmp_path / "server.json"
    custom.write_text(json.dumps({"port": 8000}), encoding="utf-8")
    with pytest.raises(ValueError, match="服务配置校验失败"):
        ServerConfig.load(custom)
