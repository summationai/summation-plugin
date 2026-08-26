"""Drive shipped extract.py then page.py on the planted weekly-sales report."""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
EXTRACT = ROOT / "skills/verify/scripts/extract.py"
PAGE = ROOT / "skills/verify/scripts/page.py"
PACKAGED = ROOT / "plugins/summation/skills/verify/scripts/page.py"
REPORT = ROOT / "tests/fixtures/verify/weekly-sales-snapshot.html"
GRADE = ROOT / "tests/fixtures/verify/weekly-sales-grade.json"


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, check=False)


class PageUtilityTests(unittest.TestCase):
    def test_extract_then_page_writes_checkpoint1_html(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            visible = tmp_path / "report-visible.txt"
            findings = tmp_path / "findings.json"
            out_dir = tmp_path / "artifact"
            self.assertEqual(_run([
                sys.executable, str(EXTRACT),
                "--report", str(REPORT),
                "--visible", str(visible),
                "--out", str(findings),
            ]).returncode, 0, "extract must succeed on the planted HTML")
            proc = _run([
                sys.executable, str(PAGE),
                "--findings", str(findings),
                "--grade", str(GRADE),
                "--out-dir", str(out_dir),
            ])
            self.assertEqual(proc.returncode, 0, proc.stderr)
            html = (out_dir / "grade-artifact.html").read_text()
            self.assertIn("FIX FIRST", html)
            self.assertIn("4.6%", html)
            self.assertIn("350,490.34", html.replace("$", ""))
            self.assertIn("Week ending 2026-04-04", html)
            self.assertNotIn("Period: Not stated", html)
            self.assertNotIn("Report date: Not stated", html)
            self.assertNotIn("data-card-id=\"C-TITLE\"", html)
            self.assertNotIn(">Weekly Sales Snapshot", html)
            artifact = json.loads((out_dir / "grade-artifact.json").read_text())
            self.assertEqual(artifact["verdict"], "fix_first")
            cards = {row["id"]: row["verdict"] for row in artifact["evidence_checks"]}
            self.assertEqual(cards["C-TOTAL"], "contradicted")
            self.assertEqual(cards["C-YOY"], "confirmed")

    def test_page_rejects_false_arithmetic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            visible = tmp_path / "report-visible.txt"
            findings = tmp_path / "findings.json"
            grade_path = tmp_path / "grade.json"
            self.assertEqual(_run([
                sys.executable, str(EXTRACT),
                "--report", str(REPORT),
                "--visible", str(visible),
                "--out", str(findings),
            ]).returncode, 0)
            grade = json.loads(GRADE.read_text())
            grade["cards"][0]["calculation"]["result"] = 1
            grade_path.write_text(json.dumps(grade) + "\n")
            proc = _run([
                sys.executable, str(PAGE),
                "--findings", str(findings),
                "--grade", str(grade_path),
                "--out-dir", str(tmp_path / "artifact"),
            ])
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("calculation", proc.stderr)

    def test_packaged_plugin_copy_matches(self) -> None:
        self.assertEqual(PAGE.read_bytes(), PACKAGED.read_bytes())
