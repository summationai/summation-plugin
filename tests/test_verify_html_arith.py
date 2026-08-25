"""HTML table footing for the verify skill. Planted $9,000 gap must fire."""
from __future__ import annotations

import importlib.util
import json
import pathlib
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "verify" / "scripts" / "html_arith.py"
PLANTED = ROOT / "tests" / "fixtures" / "verify" / "weekly-sales-snapshot.html"
CLEAN = ROOT / "tests" / "fixtures" / "verify" / "weekly-sales-snapshot-clean.html"


def load():
    spec = importlib.util.spec_from_file_location("verify_html_arith", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


html_arith = load()


class HtmlArithTests(unittest.TestCase):
    def test_planted_snapshot_names_the_footing_gap(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            out = pathlib.Path(raw) / "findings.json"
            import sys
            argv = sys.argv
            sys.argv = ["html_arith.py", "--report", str(PLANTED), "--out", str(out)]
            try:
                code = html_arith.main()
            finally:
                sys.argv = argv
            self.assertEqual(code, 0)
            doc = json.loads(out.read_text())
            footing = [f for f in doc["findings"] if f["check_id"] == "ari_total_footing"]
            self.assertTrue(footing)
            self.assertAlmostEqual(abs(footing[0]["detail"]["discrepancy"]), 9000.0)
            self.assertEqual(doc["source"]["path"], PLANTED.name)
            self.assertEqual(doc["coverage"]["claims_in_ledger"], 0)
            self.assertGreaterEqual(doc["coverage"]["checks_registered"], 1)

    def test_clean_twin_stays_quiet(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            out = pathlib.Path(raw) / "findings.json"
            import sys
            argv = sys.argv
            sys.argv = ["html_arith.py", "--report", str(CLEAN), "--out", str(out)]
            try:
                code = html_arith.main()
            finally:
                sys.argv = argv
            self.assertEqual(code, 0)
            doc = json.loads(out.read_text())
            self.assertEqual(doc["findings"], [])
            self.assertFalse(doc["agentic_only"])
            self.assertEqual(doc["coverage"]["claims_in_ledger"], 0)

    def test_pdf_writes_an_agentic_stub(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            report = pathlib.Path(raw) / "board.pdf"
            report.write_bytes(b"%PDF-fake")
            out = pathlib.Path(raw) / "findings.json"
            import sys
            argv = sys.argv
            sys.argv = ["html_arith.py", "--report", str(report), "--out", str(out)]
            try:
                code = html_arith.main()
            finally:
                sys.argv = argv
            self.assertEqual(code, 0)
            doc = json.loads(out.read_text())
            self.assertTrue(doc["agentic_only"])
            self.assertFalse(doc["agentic_scan_completed"])
            self.assertEqual(doc["findings"], [])
            self.assertEqual(doc["source"]["format"], "pdf")


if __name__ == "__main__":
    unittest.main()
