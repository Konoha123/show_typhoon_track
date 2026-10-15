#!/usr/bin/env python3
"""Integration tests against the user-provided genuine Weather Lab export.

This file is optional; tests skip cleanly if the large real CSV is not present.
Run: python -m unittest -v test_wnc_csv_demo.py test_wnc_csv_real.py
"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

import wnc_csv_demo as m

ROOT = Path(__file__).resolve().parent
REAL = ROOT / "FNV3P2_2026_10_14T00_00_paired (1).csv"
SCRIPT = ROOT / "wnc_csv_demo.py"


@unittest.skipUnless(REAL.is_file(), "原始 Weather Lab CSV 未放入当前目录，跳过实测验收")
class TestRealWeatherLabExport(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), str(REAL), *map(str, args)],
                              capture_output=True, text=True)

    def test_original_comment_prefix_and_schema(self):
        df = m.read_csv(REAL)
        self.assertEqual(df.shape, (4592, 23))
        self.assertEqual(df.columns[0], "init_time")
        mapping = m.make_mapping(df.columns, [])
        self.assertEqual(mapping["lead"], "lead_time_hours")
        self.assertEqual(mapping["member"], "sample")
        out = m.normalize(df, mapping, lead_unit=None)
        m.validate_track_table(out)
        self.assertEqual(out["lead_h"].max(), 360)
        self.assertEqual(out["storm"].nunique(), 4)
        self.assertEqual(out["member"].nunique(), 50)

    def test_list_tracks_counts(self):
        result = self.run_cli("--list-tracks")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("WP962026: 2451 行", result.stdout)
        self.assertIn("EP202026: 763 行", result.stdout)
        self.assertIn("EP212026: 1142 行", result.stdout)
        self.assertIn("WP282026: 236 行", result.stdout)
        self.assertIn("sample=0 不是集合均值", result.stdout)

    def test_single_member_24hour_export(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "selected.csv"
            r = self.run_cli("--storm", "EP202026", "--member", "0",
                             "--at-lead-hours", "24", "--output", output)
            self.assertEqual(r.returncode, 0, r.stderr)
            d = pd.read_csv(output)
            self.assertEqual(len(d), 1)
            self.assertEqual(d.loc[0, "storm"], "EP202026")
            self.assertEqual(d.loc[0, "member"], 0)
            self.assertAlmostEqual(d.loc[0, "lead_h"], 24)
            self.assertAlmostEqual(d.loc[0, "lat"], 19.77)
            self.assertAlmostEqual(d.loc[0, "lon"], -108.44)
            self.assertAlmostEqual(d.loc[0, "wind"], 57.4)
            self.assertAlmostEqual(d.loc[0, "pressure"], 993.9)

    def test_multi_member_rejected(self):
        r = self.run_cli("--storm", "EP202026")
        self.assertEqual(r.returncode, 2)
        self.assertIn("--member", r.stderr)

    def test_window_24_hour_delta(self):
        r = self.run_cli("--storm", "WP962026", "--member", "9",
                         "--max-lead-hours", "48")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("56.9 kt", r.stdout)
        self.assertIn("987.8 hPa", r.stdout)
        self.assertIn("+23.6 kt", r.stdout)

    def test_mismatch_lead_time_rejected(self):
        df = m.read_csv(REAL).head(2)
        df.loc[df.index[-1], "lead_time_hours"] = "7"  # valid-init equals 6 h
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "bad.csv"
            df.to_csv(p, index=False)
            proc = subprocess.run([sys.executable, str(SCRIPT), str(p),
                                   "--storm", "EP202026", "--member", "0"],
                                  text=True, capture_output=True)
            self.assertEqual(proc.returncode, 2)
            self.assertIn("不一致", proc.stderr)


if __name__ == "__main__":
    unittest.main()
