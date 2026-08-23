"""Fail-closed artifact for the verify skill. jsonschema required to write."""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "verify" / "scripts"
FIX = ROOT / "tests" / "fixtures" / "verify" / "tiny-findings.json"

sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("verify_render", SCRIPTS / "render.py")
render = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(render)


class RenderTests(unittest.TestCase):
    def test_tiny_fixture_is_fix_first(self) -> None:
        raw = json.loads(FIX.read_text())
        self.assertEqual(render.verdict_of(raw), "fix_first")
        art = render.artifact_from_findings(
            raw, run_id="sf-001", generated_at="2026-08-17T00:00:00Z")
        self.assertEqual(art["source"]["path"], "2026-04-04-weekly-sales-snapshot.html")
        page = render.html_of(art)
        self.assertNotIn("/Users/", page)
        self.assertNotIn("Layer 1", page)
        self.assertNotIn("Layer 2", page)

    def test_receipted_contradiction_is_fix_first(self) -> None:
        raw = {
            "findings": [],
            "coverage": {
                "claims_in_ledger": 11,
                "claims_reached_by_a_check": 11,
                "extractor_checkable_fraction": 1.0,
                "engine_checkable_fraction": 1.0,
                "checks_registered": 1,
                "checks_with_findings": 0,
                "checks_found_nothing": 1,
                "checks_errored": 0,
            },
            "source": {"path": "clean.html", "format": "html", "sha256": "abc"},
            "findings_truncated": False,
        }
        layer2 = [{
            "id": "C1",
            "type": "semantic",
            "basis": "evidence",
            "verdict": "contradicted",
            "importance": "material",
            "severity": "high",
            "report_quote": "The kickoff is Thursday.",
            "evidence_file": "evidence.json",
            "evidence_quote": "kickoff Wednesday",
            "explanation": "The report names the wrong day.",
        }]
        art = render.artifact_from_findings(
            raw, run_id="t", generated_at="2026-08-20T00:00:00Z", layer2=layer2)
        self.assertEqual(art["verdict"], "fix_first")
        page = render.html_of(art, raw)
        self.assertIn("Do not rely on this report yet", page)

    def test_cli_writes_html_and_json(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            out = pathlib.Path(raw)
            argv = sys.argv
            sys.argv = [
                "render.py",
                "--findings", str(FIX),
                "--out-dir", str(out),
                "--run-id", "test-run",
            ]
            try:
                code = render.main()
            finally:
                sys.argv = argv
            self.assertEqual(code, 0)
            html = (out / "grade-artifact.html").read_text()
            art = json.loads((out / "grade-artifact.json").read_text())
            self.assertEqual(art["verdict"], "fix_first")
            self.assertIn("Report assessment", html)


if __name__ == "__main__":
    unittest.main()
