"""Drive shipped extract.py then page.py on the planted weekly-sales report."""
from __future__ import annotations

import hashlib
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
            math_value = html.split(".receipt-math td.v{", 1)[1].split("}", 1)[0]
            self.assertIn("white-space:normal", math_value)
            self.assertNotIn("nowrap", math_value)

    def test_page_wraps_long_report_value_in_receipt_math(self) -> None:
        long_value = (
            "Metric 26; Synthetics 20; Query 19; Log 15; RUM 3; "
            "Error-tracking 1; Total 84"
        )
        grade = {
            "summary": "The type table total is 84.",
            "report_period": "Week of August 17, 2026",
            "cards": [{
                "id": "C-TYPE",
                "label": "Type table total",
                "quote": long_value,
                "verdict": "confirmed",
                "explanation": "The six type rows sum to 84.",
                "location": "Type table",
                "report_value": long_value,
                "operands": [
                    {"label": "Metric alert", "value": "26", "location": "Type table"},
                    {"label": "Synthetics alert", "value": "20", "location": "Type table"},
                    {"label": "Query alert", "value": "19", "location": "Type table"},
                    {"label": "Log alert", "value": "15", "location": "Type table"},
                    {"label": "RUM alert", "value": "3", "location": "Type table"},
                    {"label": "Error-tracking alert", "value": "1", "location": "Type table"},
                ],
                "calculation": {
                    "expression": "26 + 20 + 19 + 15 + 3 + 1",
                    "result": "84",
                },
            }],
            "next": [{
                "kind": "review_before_share",
                "text": "Share the type table. The rows sum to 84.",
                "quote": long_value,
                "card_ids": ["C-TYPE"],
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
            self.assertIn(long_value, html)
            self.assertIn('td class="v">%s</td>' % long_value, html)
            math_value = html.split(".receipt-math td.v{", 1)[1].split("}", 1)[0]
            self.assertIn("white-space:normal", math_value)
            self.assertNotIn("nowrap", math_value)

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

    def test_page_writes_unable_to_grade_when_extract_has_no_text(self) -> None:
        png = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
            b"\x00\x00\x00\nIDATx\x9cc`\x00\x00\x00\x02\x00\x01"
            b"\xe5'\xde\xfc\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        grade = {
            "summary": "This file is a logo, not a readable report.",
            "verdict": "unable_to_grade",
            "cards": [{
                "id": "C-INTAKE",
                "label": "Readable report text",
                "quote": "logo.png",
                "verdict": "not_checkable",
                "explanation": "No visible-text reader for png.",
                "location": "Uploaded file",
                "report_value": "logo.png",
            }],
            "next": [{
                "kind": "review_before_share",
                "text": (
                    "Send an HTML, PDF, Excel, PowerPoint, or Markdown report."
                ),
                "quote": "logo.png",
                "card_ids": ["C-INTAKE"],
            }],
        }
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            report = tmp_path / "logo.png"
            report.write_bytes(png)
            visible = tmp_path / "report-visible.txt"
            findings = tmp_path / "findings.json"
            grade_path = tmp_path / "grade.json"
            out_dir = tmp_path / "artifact"
            extract = _run([
                sys.executable, str(EXTRACT),
                "--report", str(report),
                "--visible", str(visible),
                "--out", str(findings),
            ])
            self.assertEqual(extract.returncode, 2, extract.stderr)
            self.assertTrue(findings.is_file())
            payload = json.loads(findings.read_text())
            self.assertTrue(payload.get("intake_error"))
            grade_path.write_text(json.dumps(grade) + "\n")
            proc = _run([
                sys.executable, str(PAGE),
                "--findings", str(findings),
                "--grade", str(grade_path),
                "--out-dir", str(out_dir),
            ])
            self.assertEqual(proc.returncode, 0, proc.stderr)
            html = (out_dir / "grade-artifact.html").read_text()
            artifact = json.loads((out_dir / "grade-artifact.json").read_text())
            self.assertIn("UNABLE TO GRADE", html)
            self.assertEqual(artifact["verdict"], "unable_to_grade")
            self.assertIn("Send an HTML, PDF, Excel, PowerPoint, or Markdown report", html)
            self.assertNotIn("SAFE TO SHARE", html)
            self.assertNotIn("SHARE WITH CAVEATS", html)

    def test_page_prints_live_source_ran_when_grade_declares_live_tool(self) -> None:
        evidence = {
            "period": "Jul-26",
            "retrieved_at": "2026-08-26T20:57:25Z",
            "rates": [{"from_currency": "GBP", "rate": "1.337612"}],
        }
        grade = {
            "summary": "The July 2026 GBP planning rate matches currency_rates_input.",
            "report_period": "July 2026",
            "cards": [{
                "id": "C-GBP",
                "label": "GBP rate to USD",
                "quote": "1.337612",
                "verdict": "confirmed",
                "explanation": "get_currency_rates for Jul-26 returns GBP 1.337612.",
                "location": "GBP row",
                "report_value": "1.337612",
                "source_id": "SRC-get_currency_rates",
                "inventory_ids": ["INV1"],
                "operands": [{
                    "label": "GBP to USD in currency_rates_input",
                    "value": "1.337612",
                    "location": "currency_rates_input period Jul-26 GBP",
                }],
            }],
            "next": [{
                "kind": "review_before_share",
                "text": "Share the July 2026 FX note. The GBP rate matches.",
                "quote": "1.337612",
                "card_ids": ["C-GBP"],
            }],
            "sources": [{
                "id": "SRC-get_currency_rates",
                "kind": "live_tool",
                "label": "currency_rates_input",
                "evidence_file": "get_currency_rates.json",
                "retrieval": {
                    "retrieved_at": "2026-08-26T20:57:25Z",
                    "tool": "get_currency_rates",
                    "arguments": {"period": "Jul-26"},
                },
            }],
        }
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            visible = tmp_path / "report-visible.txt"
            findings = tmp_path / "findings.json"
            grade_path = tmp_path / "grade.json"
            evidence_dir = tmp_path / "evidence"
            evidence_dir.mkdir()
            evidence_path = evidence_dir / "get_currency_rates.json"
            evidence_path.write_text(json.dumps(evidence) + "\n")
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
                "--evidence-dir", str(evidence_dir),
                "--out-dir", str(out_dir),
            ])
            self.assertEqual(proc.returncode, 0, proc.stderr)
            html = (out_dir / "grade-artifact.html").read_text()
            artifact = json.loads((out_dir / "grade-artifact.json").read_text())
            self.assertIn("<b>Live source</b>Ran", html)
            self.assertIn("Live source", html)
            sources = artifact["sources"]
            live = [row for row in sources if row["kind"] == "live_tool"]
            self.assertEqual(len(live), 1)
            self.assertEqual(live[0]["evidence_file"], "get_currency_rates.json")
            self.assertEqual(
                live[0]["retrieval"]["tool"], "get_currency_rates")
            self.assertEqual(
                artifact["verification"]["live_source"]["status"], "complete")
            digest = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
            self.assertEqual(live[0]["result_sha256"], digest)

            grade.pop("sources")
            grade_path.write_text(json.dumps(grade) + "\n")
            silent = tmp_path / "artifact-silent"
            proc = _run([
                sys.executable, str(PAGE),
                "--findings", str(findings),
                "--grade", str(grade_path),
                "--evidence-dir", str(evidence_dir),
                "--out-dir", str(silent),
            ])
            self.assertEqual(proc.returncode, 0, proc.stderr)
            silent_html = (silent / "grade-artifact.html").read_text()
            silent_art = json.loads((silent / "grade-artifact.json").read_text())
            self.assertIn("<b>Live source</b>Did not run", silent_html)
            self.assertTrue(all(
                row["kind"] == "supplied_file"
                for row in silent_art["sources"]))

    def test_page_rejects_live_tool_without_the_evidence_file(self) -> None:
        grade = {
            "summary": "The GBP rate matches.",
            "report_period": "July 2026",
            "cards": [{
                "id": "C-GBP",
                "label": "GBP rate to USD",
                "quote": "1.337612",
                "verdict": "confirmed",
                "explanation": "Live rate matches.",
                "location": "GBP row",
                "report_value": "1.337612",
            }],
            "next": [{
                "kind": "review_before_share",
                "text": "Share the FX note.",
                "quote": "1.337612",
                "card_ids": ["C-GBP"],
            }],
            "sources": [{
                "id": "SRC-get_currency_rates",
                "kind": "live_tool",
                "label": "currency_rates_input",
                "evidence_file": "get_currency_rates.json",
                "retrieval": {
                    "retrieved_at": "2026-08-26T20:57:25Z",
                    "tool": "get_currency_rates",
                    "arguments": {"period": "Jul-26"},
                },
            }],
        }
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            visible = tmp_path / "report-visible.txt"
            findings = tmp_path / "findings.json"
            grade_path = tmp_path / "grade.json"
            evidence_dir = tmp_path / "evidence"
            evidence_dir.mkdir()
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
                "--evidence-dir", str(evidence_dir),
                "--out-dir", str(tmp_path / "artifact"),
            ])
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("evidence_file", proc.stderr)

    def test_packaged_plugin_copy_matches(self) -> None:
        self.assertEqual(PAGE.read_bytes(), PACKAGED.read_bytes())
        render = ROOT / "skills/verify/scripts/render.py"
        packaged_render = ROOT / "plugins/summation/skills/verify/scripts/render.py"
        self.assertEqual(render.read_bytes(), packaged_render.read_bytes())
