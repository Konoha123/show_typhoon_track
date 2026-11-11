"""一键打包 Web 服务为 PyInstaller onedir 可执行目录（M14）。

用法（在 show-typhoon-track 环境内、项目根目录执行，Windows/Linux 同命令）::

    python scripts/build_exe.py

设计口径（决策与冒烟证据见 docs/打包方案验收记录_20261111.md）：
- onedir：产物 ``dist/typhoon-track/``（可执行文件 + ``_internal/`` 运行时），启动快、数据稳定；
- ``configs/`` 与 ``places/places.example.csv`` 外置于产物目录（可编辑，与源码运行同语义）；
- ``uploads/`` 由服务首次运行在可执行文件旁自动创建（数据持久，依赖 M14a 冻结感知路径）；
- 打包配方单源收敛于本脚本：``typhoon-track.spec`` 为本脚本按需生成的构建过程产物
  （``.gitignore`` 以 ``*.spec`` 忽略，不入库）；
- excludes 裁剪 uvloop/httptools/watchfiles/websockets（uvicorn 自动回退 asyncio/h11，
  行为等价）与 tkinter；hiddenimports 兜底 uvicorn 字符串导入目标 ``typhoon_track.api.app``
  与 python-multipart（版本迁移期新旧模块名双写）；
- 保留控制台（console=True）：uvicorn 日志与出错诊断信息可见。
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

APP_NAME = "typhoon-track"
ENTRY = "app.py"
SPEC_PATH = ROOT / f"{APP_NAME}.spec"
BUILD_DIR = ROOT / "build"
DIST_DIR = ROOT / "dist"
DIST_APP = DIST_DIR / APP_NAME

# datas：（源路径相对项目根, 目标路径相对包内根）；spec 由本脚本生成，相对路径按 spec 所在目录解析
DATAS: list[tuple[str, str]] = [
    ("typhoon_track/web/templates", "typhoon_track/web/templates"),
    ("typhoon_track/web/static", "typhoon_track/web/static"),
]

HIDDEN_IMPORTS: list[str] = [
    "typhoon_track.api.app",  # uvicorn.run 以字符串导入，静态分析可能漏收
    "python_multipart",  # python-multipart 0.0.12+ 模块名
    "multipart",  # 旧模块名（版本迁移期双写，未命中仅告警）
]

EXCLUDES: list[str] = [
    "uvloop",
    "httptools",
    "watchfiles",
    "websockets",
    "tkinter",
]

# 外置于产物目录的运行时文件/目录（可编辑，随分发）
EXTERNAL_DIRS = ["configs"]
EXTERNAL_FILES = ["places/places.example.csv"]

# 产物自检清单（相对 DIST_APP；_internal 下为包内 datas 落点）
CHECK_PATHS: list[str] = [
    "_internal/typhoon_track/web/templates/index.html",
    "_internal/typhoon_track/web/static/app.js",
    "_internal/typhoon_track/web/static/vendor/leaflet.js",
    "configs/server.json",
    "configs/tiles.toml",
    "places/places.example.csv",
]

SPEC_TEMPLATE = """\
# -*- mode: python ; coding: utf-8 -*-
# 本文件由 scripts/build_exe.py 生成（构建过程产物，被 .gitignore 的 *.spec 忽略）。
# 打包配方单源在 scripts/build_exe.py，手工修改本文件会在下次构建时被覆盖。

datas = {datas!r}

a = Analysis(
    [{entry!r}],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports={hidden!r},
    hookspath=[],
    hooksconfig={{}},
    runtime_hooks=[],
    excludes={excludes!r},
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name={name!r},
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name={name!r},
)
"""


def _clean_previous() -> None:
    for target in (BUILD_DIR, DIST_APP, SPEC_PATH):
        if target.is_dir():
            shutil.rmtree(target)
        elif target.is_file():
            target.unlink()


def _write_spec() -> None:
    SPEC_PATH.write_text(
        SPEC_TEMPLATE.format(
            datas=DATAS,
            entry=ENTRY,
            hidden=HIDDEN_IMPORTS,
            excludes=EXCLUDES,
            name=APP_NAME,
        ),
        encoding="utf-8",
    )


def _run_pyinstaller() -> None:
    command = [sys.executable or "python", "-m", "PyInstaller", "--noconfirm", "--clean", str(SPEC_PATH)]
    print(f"[build] {' '.join(command)}")
    result = subprocess.run(command, cwd=ROOT, check=False)
    if result.returncode != 0:
        print(f"[build] PyInstaller 失败（退出码 {result.returncode}）；请确认已安装 pyinstaller>=6.0")
        raise SystemExit(result.returncode)


def _copy_external_files() -> None:
    for rel_dir in EXTERNAL_DIRS:
        src = ROOT / rel_dir
        if not src.is_dir():
            print(f"[build] 缺少外置目录 {rel_dir}，中止")
            raise SystemExit(1)
        shutil.copytree(src, DIST_APP / rel_dir, dirs_exist_ok=True)
    for rel_file in EXTERNAL_FILES:
        src = ROOT / rel_file
        if not src.is_file():
            print(f"[build] 缺少外置文件 {rel_file}，中止")
            raise SystemExit(1)
        dest = DIST_APP / rel_file
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)


def _verify(exe_name: str) -> None:
    checks = [exe_name, *CHECK_PATHS]
    missing = [rel for rel in checks if not (DIST_APP / rel).exists()]
    if missing:
        print(f"[build] 产物自检失败，缺失：{missing}")
        raise SystemExit(1)
    print("[build] 产物自检通过")


def main() -> None:
    exe_name = f"{APP_NAME}.exe" if sys.platform == "win32" else APP_NAME
    _clean_previous()
    _write_spec()
    _run_pyinstaller()
    _copy_external_files()
    _verify(exe_name)
    print(
        f"[build] 完成：{DIST_APP}\n"
        f"[build] 运行：双击/执行 {DIST_APP / exe_name}，服务就绪后自动打开浏览器"
        "（监听与瓦片配置见产物目录 configs/；预存地点复制 places/places.example.csv 为 places.csv 启用）"
    )


if __name__ == "__main__":
    main()
