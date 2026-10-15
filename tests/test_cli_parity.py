"""重组 CLI（python -m typhoon_track）与 demo_src/wnc_csv_demo.py 的行为一致性对照。

按 AGENTS.md“重组后行为一致性验证纪律”长期保留：相同输入与参数下，
退出码、stdout、stderr 逐字节一致，--output 导出产物逐字节一致。
参数矩阵 × 数据集矩阵（合成 + 真实，真实文件缺失自动跳过）。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DEMO_SCRIPT = ROOT / "demo_src" / "wnc_csv_demo.py"
MEAN = ROOT / "demo_src" / "sample_synthetic_ensemble_mean.csv"
MEMBERS = ROOT / "demo_src" / "sample_synthetic_ensemble.csv"
REAL = ROOT / "demo_src" / "FNV3P2_2026_10_14T00_00_paired (1).csv"

DATASETS: dict[str, Path | None] = {"mean": MEAN, "members": MEMBERS, "real": REAL}

# (用例id, 数据集, 参数, 是否带 --output 导出)
CASES: list[tuple[str, str, list[str], bool]] = [
    ("mean-default", "mean", [], False),
    ("mean-inspect", "mean", ["--inspect"], False),
    ("mean-list-tracks", "mean", ["--list-tracks"], False),
    ("mean-storm-window-export", "mean", ["--storm", "syn202601", "--max-lead-hours", "48"], True),
    ("mean-at-48-export", "mean", ["--at-lead-hours", "48"], True),
    ("mean-column-override", "mean", ["--column", "wind=maximum_sustained_wind_speed_knots"], False),
    ("mean-max-rows-2", "mean", ["--max-rows", "2"], False),
    ("mean-at-49-empty", "mean", ["--at-lead-hours", "49"], False),
    ("mean-unknown-storm", "mean", ["--storm", "NOPE"], False),
    ("mean-member-column-missing", "mean", ["--member", "01"], False),
    ("mean-bad-column-arg", "mean", ["--column", "wind"], False),
    ("members-mixing-rejected", "members", [], False),
    ("members-select-01", "members", ["--member", "01"], False),
    ("members-select-01-init", "members", ["--member", "01", "--init", "2026-07-01T00:00Z"], False),
    ("members-no-such-member", "members", ["--member", "9"], False),
    ("real-list-tracks", "real", ["--list-tracks"], False),
    ("real-inspect", "real", ["--inspect"], False),
    ("real-point-export", "real",
     ["--storm", "EP202026", "--member", "0", "--at-lead-hours", "24"], True),
    ("real-window", "real", ["--storm", "WP962026", "--member", "9", "--max-lead-hours", "48"], False),
    ("real-mixing-rejected", "real", ["--storm", "EP202026"], False),
]


def _run(command: list[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(command, capture_output=True, cwd=ROOT, check=False)


@pytest.mark.parametrize(
    "case_id,dataset,args,use_export",
    CASES,
    ids=[c[0] for c in CASES],
)
def test_cli_parity(
    case_id: str,
    dataset: str,
    args: list[str],
    use_export: bool,
    tmp_path: Path,
) -> None:
    csv = DATASETS[dataset]
    assert csv is not None
    if not csv.is_file():
        pytest.skip("原始 Weather Lab CSV 未放入 demo_src，跳过实测对照")

    export = tmp_path / "export.csv"
    common = args + (["--output", str(export)] if use_export else [])

    old = _run([sys.executable, str(DEMO_SCRIPT), str(csv), *common])
    first_export = export.read_bytes() if use_export and export.is_file() else None

    new = _run([sys.executable, "-m", "typhoon_track", str(csv), *common])

    assert new.returncode == old.returncode, f"退出码不一致: {case_id}"
    assert new.stdout == old.stdout, f"stdout 不一致: {case_id}"
    assert new.stderr == old.stderr, f"stderr 不一致: {case_id}"
    if use_export:
        assert export.read_bytes() == first_export, f"导出 CSV 不一致: {case_id}"


@pytest.mark.parametrize(
    "lead_args",
    [
        ["--lead-unit", "seconds", "--at-lead-hours", "24"],
        ["--at-lead-hours", "24"],  # 单位未知：stderr 提示 + 退出码 2
    ],
    ids=["seconds-known", "unit-unknown"],
)
def test_cli_parity_numeric_lead(lead_args: list[str], tmp_path: Path) -> None:
    csv = tmp_path / "lead.csv"
    csv.write_text("track_id,lead_time,vmax_kt\nT1,0,30\nT1,86400,65\n", encoding="utf-8")

    old = _run([sys.executable, str(DEMO_SCRIPT), str(csv), *lead_args])
    new = _run([sys.executable, "-m", "typhoon_track", str(csv), *lead_args])

    assert new.returncode == old.returncode
    assert new.stdout == old.stdout
    assert new.stderr == old.stderr


def test_cli_parity_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "nope.csv"
    old = _run([sys.executable, str(DEMO_SCRIPT), str(missing)])
    new = _run([sys.executable, "-m", "typhoon_track", str(missing)])

    assert new.returncode == old.returncode == 2
    assert new.stdout == old.stdout
    assert new.stderr == old.stderr
