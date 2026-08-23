"""Grounding for the verify skill: a bad quote drops that row, not the run."""
from __future__ import annotations

import importlib.util
import json
import pathlib
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "verify" / "scripts" / "accept.py"


def load():
    spec = importlib.util.spec_from_file_location("verify_accept", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


accept = load()


class AcceptTests(unittest.TestCase):
    def test_keeps_verbatim_quote_and_drops_a_sloppy_one(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            report = folder / "report.html"
            report.write_text("<p>Revenue grew 12% year over year.</p>")
            evidence = folder / "q3.json"
            evidence.write_text('{"revenue_yoy": 0.098}\n')
            checks = folder / "checks.json"
            checks.write_text(json.dumps({"checks": [
                {
                    "id": "C1",
                    "type": "semantic",
                    "basis": "evidence",
                    "verdict": "contradicted",
                    "importance": "material",
                    "report_quote": "Revenue grew 12% year over year.",
                    "evidence_file": "q3.json",
                    "evidence_quote": '"revenue_yoy": 0.098',
                    "explanation": "The file shows 9.8%, not 12%.",
                },
                {
                    "id": "C2",
                    "type": "semantic",
                    "basis": "evidence",
                    "verdict": "contradicted",
                    "importance": "material",
                    "report_quote": "a paraphrase that is not in the report",
                    "evidence_file": "q3.json",
                    "evidence_quote": "missing",
                    "explanation": "Invented.",
                },
            ]}))
            out = folder / "receipts.json"
            rc = accept.main.__wrapped__ if hasattr(accept.main, "__wrapped__") else None
            # Call through argv.
            import sys
            argv = sys.argv
            sys.argv = [
                "accept.py",
                "--report", str(report),
                "--checks", str(checks),
                "--evidence-dir", str(folder),
                "--out", str(out),
            ]
            try:
                code = accept.main()
            finally:
                sys.argv = argv
            self.assertEqual(code, 0)
            payload = json.loads(out.read_text())
            self.assertEqual(payload["proposed"], 2)
            self.assertEqual(payload["grounded"], 1)
            self.assertEqual(payload["validated"][0]["id"], "C1")
            self.assertEqual(payload["discarded"][0]["id"], "C2")

    def test_json_pointer_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            report = folder / "report.md"
            report.write_text("Units sold were 10481.")
            (folder / "stats.json").write_text('{"units": 10481}\n')
            checks = folder / "checks.json"
            checks.write_text(json.dumps({"checks": [{
                "id": "C3",
                "type": "semantic",
                "basis": "evidence",
                "verdict": "confirmed",
                "importance": "material",
                "report_quote": "Units sold were 10481.",
                "evidence_file": "stats.json",
                "evidence_json": [{"pointer": "/units", "value": 10481}],
                "explanation": "The file matches the report.",
            }]}))
            import sys
            argv = sys.argv
            sys.argv = [
                "accept.py",
                "--report", str(report),
                "--checks", str(checks),
                "--evidence-dir", str(folder),
                "--out", str(folder / "receipts.json"),
            ]
            try:
                code = accept.main()
            finally:
                sys.argv = argv
            self.assertEqual(code, 0)
            payload = json.loads((folder / "receipts.json").read_text())
            self.assertEqual(payload["grounded"], 1)
            self.assertEqual(payload["checks"][0]["evidence_receipt_mode"], "json-pointers")

    def test_report_text_sidecar_for_binary_formats(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            report = folder / "deck.pdf"
            report.write_bytes(b"%PDF-fake")
            sidecar = folder / "report-visible.txt"
            sidecar.write_text("Board says margin is up 3%.")
            checks = folder / "checks.json"
            checks.write_text(json.dumps({"checks": [{
                "id": "C4",
                "type": "units",
                "basis": "report",
                "verdict": "not_checkable",
                "importance": "material",
                "report_quote": "Board says margin is up 3%.",
                "explanation": "No evidence file was supplied for the margin figure.",
            }]}))
            import sys
            argv = sys.argv
            sys.argv = [
                "accept.py",
                "--report", str(report),
                "--report-text", str(sidecar),
                "--checks", str(checks),
                "--out", str(folder / "receipts.json"),
            ]
            try:
                code = accept.main()
            finally:
                sys.argv = argv
            self.assertEqual(code, 0)
            payload = json.loads((folder / "receipts.json").read_text())
            self.assertEqual(payload["grounded"], 1)


if __name__ == "__main__":
    unittest.main()
