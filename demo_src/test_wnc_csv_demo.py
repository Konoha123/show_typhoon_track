#!/usr/bin/env python3
"""Offline smoke / logic tests. Run: python -m unittest -v test_wnc_csv_demo.py"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

import wnc_csv_demo as m

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "wnc_csv_demo.py"
MEAN = HERE / "sample_synthetic_ensemble_mean.csv"
MEMBERS = HERE / "sample_synthetic_ensemble.csv"


class TestWncCsvDemo(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)],
                              text=True, capture_output=True)

    def test_mean_summary_and_24_hour_change(self):
        r = self.run_cli(MEAN)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("94 kt", r.stdout)
        self.assertIn("947 hPa", r.stdout)
        self.assertIn("+43 kt", r.stdout)
        self.assertIn("达到 30 kt 快速增强阈值: 是", r.stdout)

    def test_inspect_real_column_mapping(self):
        r = self.run_cli(MEAN, "--inspect")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("maximum_sustained_wind_speed_knots", r.stdout)
        self.assertIn("[原始列名]", r.stdout)

    def test_select_lead_and_export(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "selected.csv"
            r = self.run_cli(MEAN, "--at-lead-hours", 48, "--output", output)
            self.assertEqual(r.returncode, 0, r.stderr)
            result = pd.read_csv(output)
            self.assertEqual(len(result), 1)
            self.assertAlmostEqual(result.loc[0, "lead_h"], 48)
            self.assertEqual(result.loc[0, "wind"], 94)

    def test_ensemble_requires_member_selection(self):
        r = self.run_cli(MEMBERS)
        self.assertEqual(r.returncode, 2)
        self.assertIn("--member", r.stderr)
        r = self.run_cli(MEMBERS, "--member", "01")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_override_field(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "alt.csv"
            df = pd.read_csv(MEAN).rename(columns={"maximum_sustained_wind_speed_knots": "MY_KNOTS"})
            df.to_csv(p, index=False)
            r = self.run_cli(p, "--column", "wind=MY_KNOTS")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("94 kt", r.stdout)

    def test_no_guess_units(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "lead.csv"
            pd.DataFrame({"track_id": ["T1", "T1"], "lead_time": [0, 86400],
                          "vmax_kt": [30, 65]}).to_csv(p, index=False)
            raw = self.run_cli(p, "--at-lead-hours", 24)
            self.assertEqual(raw.returncode, 2)
            self.assertIn("--lead-unit", raw.stderr)
            fixed = self.run_cli(p, "--lead-unit", "seconds", "--at-lead-hours", 24)
            self.assertEqual(fixed.returncode, 0, fixed.stderr)
            self.assertIn("65 kt", fixed.stdout)

    def test_nonexistent_input(self):
        r = self.run_cli("/path/to/missing_wnc.csv")
        self.assertEqual(r.returncode, 2)
        self.assertIn("文件不存在", r.stderr)

    def test_repeated_valid_time_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "duplicate.csv"
            df = pd.read_csv(MEAN)
            pd.concat([df, df.head(1)], ignore_index=True).to_csv(p, index=False)
            r = self.run_cli(p)
            self.assertEqual(r.returncode, 2)
            self.assertIn("重复的 valid_time", r.stderr)

    def test_rich_radii_mapping(self):
        df = m.read_csv(MEAN)
        mapping = m.make_mapping(df.columns, [])
        self.assertEqual(mapping["r34_ne"], "radius_34_knot_winds_ne_km")


if __name__ == "__main__":
    unittest.main()
