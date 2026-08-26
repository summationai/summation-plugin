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
            self.assertIn("table-layout:fixed", html)
            self.assertIn(".receipt-math td{", html)
            self.assertIn("word-break:normal", html)
            self.assertIn("overflow-wrap:break-word", html)
            self.assertIn(".receipt-math td.v{white-space:normal", html)

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

    def test_page_keeps_percentage_point_unit_on_rate_delta(self) -> None:
        grade = {
            "summary": "Change the margin note from 3% to 3 pp.",
            "report_period": "Week ending 2026-08-15",
            "report_date": "2026-08-15",
            "cards": [{
                "id": "C-WOW",
                "label": "Week-over-week gross margin change",
                "quote": "Note: gross margin improved 3% week over week.",
                "verdict": "contradicted",
                "explanation": "40.0% to 43.0% is 3 pp, not a 3% relative change.",
                "location": "Note below the table",
                "report_value": "3%",
                "operands": [
                    {
                        "label": "Gross margin, prior week",
                        "value": "40.0%",
                        "location": "Prior-week gross margin cell",
                    },
                    {
                        "label": "Gross margin, current week",
                        "value": "43.0%",
                        "location": "Current-week gross margin cell",
                    },
                ],
                "calculation": {"expression": "43.0 - 40.0", "result": "3 pp"},
            }],
            "next": [{
                "kind": "correct_report",
                "text": (
                    "Change the note from “gross margin improved 3% week over week” "
                    "to “gross margin improved 3 pp week over week.”"
                ),
                "quote": "3%",
                "card_ids": ["C-WOW"],
            }],
        }
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            visible = tmp_path / "report-visible.txt"
            findings = tmp_path / "findings.json"
            grade_path = tmp_path / "grade.json"
            out_dir = tmp_path / "artifact"
            self.assertEqual(_run([
                sys.executable, str(EXTRACT),
                "--report", str(REPORT),
                "--visible", str(visible),
                "--out", str(findings),
            ]).returncode, 0)
            grade_path.write_text(json.dumps(grade) + "\n")
            proc = _run([
                sys.executable, str(PAGE),
                "--findings", str(findings),
                "--grade", str(grade_path),
                "--out-dir", str(out_dir),
            ])
            self.assertEqual(proc.returncode, 0, proc.stderr)
            html = (out_dir / "grade-artifact.html").read_text()
            self.assertIn("FIX FIRST", html)
            self.assertIn("3 pp", html)
            self.assertIn("43.0 - 40.0 = 3 pp", html)
            self.assertIn("improved 3 pp week over week", html)
            self.assertNotIn("7.5%", html)

    def test_packaged_plugin_copy_matches(self) -> None:
        self.assertEqual(PAGE.read_bytes(), PACKAGED.read_bytes())
        render = ROOT / "skills/verify/scripts/render.py"
        packaged_render = ROOT / "plugins/summation/skills/verify/scripts/render.py"
        self.assertEqual(render.read_bytes(), packaged_render.read_bytes())
