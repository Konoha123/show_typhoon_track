"""api.app.load_tile_config：瓦片配置加载与防错配置检查。"""

from __future__ import annotations

from pathlib import Path

import pytest

from typhoon_track.api.app import PROJECT_ROOT, load_tile_config


def test_load_repo_default_config() -> None:
    config = load_tile_config()
    assert config.url_template.startswith("https://")
    assert "{z}" in config.url_template and "{x}" in config.url_template and "{y}" in config.url_template
    assert config.attribution
    assert config.max_zoom >= 1
    assert (PROJECT_ROOT / "config.toml").is_file()


def test_load_from_custom_path(tmp_path: Path) -> None:
    custom = tmp_path / "config.toml"
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
