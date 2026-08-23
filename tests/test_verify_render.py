"""Fail-closed artifact for the verify skill."""
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
PLANTED = ROOT / "tests" / "fixtures" / "verify" / "weekly-sales-snapshot.html"

sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("verify_render", SCRIPTS / "render.py")
render = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(render)

try:
    import jsonschema  # noqa: F401
except ImportError:
    jsonschema = None

HAS_JSONSCHEMA = jsonschema is not None

accept_spec = importlib.util.spec_from_file_location(
    "verify_accept", SCRIPTS / "accept.py")
accept = importlib.util.module_from_spec(accept_spec)
assert accept_spec.loader is not None
accept_spec.loader.exec_module(accept)

arith_spec = importlib.util.spec_from_file_location(
    "verify_html_arith", SCRIPTS / "html_arith.py")
html_arith = importlib.util.module_from_spec(arith_spec)
assert arith_spec.loader is not None
arith_spec.loader.exec_module(html_arith)


def run_mod(mod, name: str, args: list[str]) -> int:
    argv = sys.argv
    sys.argv = [name, *args]
    try:
        return mod.main()
    finally:
        sys.argv = argv


class RenderVerdictTests(unittest.TestCase):
    def test_tiny_fixture_verdict_is_fix_first(self) -> None:
        raw = json.loads(FIX.read_text())
        self.assertEqual(render.verdict_of(raw), "fix_first")

    def test_d_finding_is_fix_first_without_a_synthetic_ledger(self) -> None:
        raw = {
            "findings": [{
                "check_id": "ari_total_footing",
                "family": "internal_arithmetic",
                "tier": "D",
                "statement": "gap",
                "claim_ids": [],
            }],
            "coverage": {
                "claims_in_ledger": 0,
                "claims_reached_by_a_check": 0,
                "extractor_checkable_fraction": 1.0,
                "engine_checkable_fraction": 1.0,
                "checks_registered": 2,
                "checks_with_findings": 1,
                "checks_found_nothing": 1,
                "checks_errored": 0,
            },
            "source": {"path": "report.html", "format": "html"},
            "findings_truncated": False,
        }
        self.assertEqual(render.verdict_of(raw), "fix_first")


SCHEMA = ROOT / "skills" / "verify" / "schema.v1.json"


def schema_claim_verdicts() -> list:
    schema = json.loads(SCHEMA.read_text())
    return list(
        schema["properties"]["evidence_checks"]["items"]["properties"]["verdict"]["enum"]
    )


def _minimal_art(evidence_checks: list) -> dict:
    contradicted = [row for row in evidence_checks if row.get("verdict") == "contradicted"]
    return {
        "schema_version": "grade-artifact/v1",
        "run_id": "parity",
        "generated_at": "2026-08-23T00:00:00Z",
        "source": {"path": "report.md", "format": "md"},
        "source_result": None,
        "verdict": "needs_review",
        "score": None,
        "findings": [],
        "evidence_checks": evidence_checks,
        "evidence_findings": contradicted,
        "evidence_coverage": {
            "document_claims_total": len(evidence_checks),
            "document_claims_reached": len(evidence_checks),
            "claim_outcomes_proposed": len(evidence_checks),
            "material_claims_reviewed": len(evidence_checks),
            "supporting_claims_reviewed": 0,
            "confirmed": 0,
            "contradicted": 0,
            "not_checkable": 0,
            "evidence_confirmed": 0,
            "evidence_contradicted": 0,
            "evidence_not_checkable": 0,
            "report_confirmed": 0,
            "report_contradicted": 0,
            "report_not_checkable": 0,
            "validated_outcomes": len(evidence_checks),
            "receipt_failures": 0,
            "evidence_files_supplied": 0,
            "evidence_files_cited": [],
            "provenance_groups": [],
            "source_independence": "not_assessed",
        },
        "decision": None,
        "actions": [],
        "decision_limits": [],
        "diagnostics": [],
        "checks": {
            "registered": 0,
            "with_findings": 0,
            "found_nothing": 0,
            "errored": 0,
            "skipped_note": "",
        },
        "verification": {
            "document": {"status": "not_run", "detail": None},
            "semantic": {"status": "complete", "detail": None},
            "live_source": {"status": "not_run", "detail": None},
        },
        "limitations": [],
        "offer": {"text": "Next: stop.", "accepted": None},
    }


def _check(verdict: str, **extra) -> dict:
    row = {
        "id": f"id-{verdict}",
        "type": "semantic",
        "basis": "evidence",
        "verdict": verdict,
        "importance": "material",
        "severity": "high" if verdict == "contradicted" else None,
        "report_quote": f"Visible quote for {verdict}.",
        "report_quote_2": None,
        "evidence_file": "live.json",
        "evidence_quote": f"evidence for {verdict}",
        "evidence_json": [],
        "evidence_receipts": [],
        "evidence_receipt_mode": "verbatim",
        "explanation": f"Explanation for {verdict}.",
        "reconstruction_attempt": None,
        "current_value": None,
        "current_as_of": None,
    }
    row.update(extra)
    return row


class HtmlParityTests(unittest.TestCase):
    def test_every_schema_claim_verdict_appears_in_html(self) -> None:
        verdicts = schema_claim_verdicts()
        self.assertTrue(verdicts)
        rows = []
        for verdict in verdicts:
            extra = {}
            if verdict == "changed_since_report":
                extra = {
                    "reconstruction_attempt": "No history table remains.",
                    "current_value": 10613,
                    "current_as_of": "2026-08-23",
                }
            rows.append(_check(verdict, **extra))
        page = render.html_of(_minimal_art(rows))
        for row in rows:
            with self.subTest(verdict=row["verdict"]):
                self.assertIn(
                    row["report_quote"], page,
                    f"{row['verdict']} quote missing from HTML",
                )
                self.assertIn(
                    row["explanation"], page,
                    f"{row['verdict']} explanation missing from HTML",
                )

    def test_unhandled_verdict_still_renders_a_card(self) -> None:
        row = _check("unmodeled_verdict")
        page = render.html_of(_minimal_art([row]))
        self.assertIn(row["report_quote"], page)
        self.assertIn(row["explanation"], page)
        self.assertIn("unmodeled_verdict", page)


@unittest.skipUnless(HAS_JSONSCHEMA, "jsonschema is not installed")
class RenderArtifactTests(unittest.TestCase):
    def test_tiny_fixture_is_fix_first(self) -> None:
        raw = json.loads(FIX.read_text())
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
            code = run_mod(render, "render.py", [
                "--findings", str(FIX),
                "--out-dir", str(out),
                "--run-id", "test-run",
            ])
            self.assertEqual(code, 0)
            html = (out / "grade-artifact.html").read_text()
            art = json.loads((out / "grade-artifact.json").read_text())
            self.assertEqual(art["verdict"], "fix_first")
            self.assertIn("Report assessment", html)

    def test_changed_since_report_writes_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            report = folder / "report.md"
            report.write_text("Inventory on hand is 4,200.")
            (folder / "live.json").write_text(
                '{"on_hand": 5100, "as_of": "2026-08-23"}\n')
            checks = {
                "checks": [{
                    "id": "C11",
                    "type": "staleness",
                    "basis": "evidence",
                    "verdict": "changed_since_report",
                    "importance": "material",
                    "report_quote": "Inventory on hand is 4,200.",
                    "evidence_file": "live.json",
                    "evidence_json": [{"pointer": "/on_hand", "value": 5100}],
                    "explanation": "Current on-hand is 5100 as of 2026-08-23.",
                    "reconstruction_attempt": (
                        "Queried inventory_history and the daily snapshot table; "
                        "neither retains 2026-04-04 on-hand."
                    ),
                    "current_value": 5100,
                    "current_as_of": "2026-08-23",
                }]
            }
            (folder / "checks.json").write_text(json.dumps(checks))
            self.assertEqual(run_mod(accept, "accept.py", [
                "--report", str(report),
                "--checks", str(folder / "checks.json"),
                "--evidence-dir", str(folder),
                "--out", str(folder / "receipts.json"),
            ]), 0)
            findings = {
                "findings": [],
                "coverage": {
                    "claims_in_ledger": 0,
                    "claims_reached_by_a_check": 0,
                    "extractor_checkable_fraction": 0.0,
                    "engine_checkable_fraction": 0.0,
                    "checks_registered": 0,
                    "checks_with_findings": 0,
                    "checks_found_nothing": 0,
                    "checks_errored": 0,
                },
                "source": {"path": "report.md", "format": "md", "sha256": "abc"},
                "findings_truncated": False,
                "agentic_only": True,
                "agentic_scan_completed": True,
                "extraction_method": "host-agent visible text",
            }
            (folder / "findings.json").write_text(json.dumps(findings))
            out = folder / "artifact"
            code = run_mod(render, "render.py", [
                "--findings", str(folder / "findings.json"),
                "--layer2", str(folder / "receipts.json"),
                "--out-dir", str(out),
                "--run-id", "csr-run",
            ])
            self.assertEqual(code, 0)
            self.assertTrue((out / "grade-artifact.html").is_file())
            art = json.loads((out / "grade-artifact.json").read_text())
            verdicts = {row["verdict"] for row in art["evidence_checks"]}
            self.assertIn("changed_since_report", verdicts)
            self.assertTrue(art["evidence_checks"][0]["reconstruction_attempt"])
            self.assertEqual(art["evidence_checks"][0]["current_value"], 5100)

    def test_ledger_count_matches_proposed_checks(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            report = folder / "report.md"
            report.write_text("Alpha is 1. Beta is 2. Gamma is 3. Delta is 4. Epsilon is 5.")
            (folder / "ev.json").write_text('{"alpha": 1}\n')
            rows = []
            for i, (name, quote) in enumerate([
                ("Alpha", "Alpha is 1."),
                ("Beta", "Beta is 2."),
                ("Gamma", "Gamma is 3."),
                ("Delta", "Delta is 4."),
                ("Epsilon", "Epsilon is 5."),
            ], start=1):
                rows.append({
                    "id": f"C{i}",
                    "type": "semantic",
                    "basis": "evidence",
                    "verdict": "confirmed",
                    "importance": "material",
                    "report_quote": quote,
                    "evidence_file": "ev.json",
                    "evidence_quote": '"alpha": 1',
                    "explanation": f"{name} matches.",
                })
            (folder / "checks.json").write_text(json.dumps({"checks": rows}))
            self.assertEqual(run_mod(accept, "accept.py", [
                "--report", str(report),
                "--checks", str(folder / "checks.json"),
                "--evidence-dir", str(folder),
                "--out", str(folder / "receipts.json"),
            ]), 0)
            receipts = json.loads((folder / "receipts.json").read_text())
            self.assertEqual(receipts["proposed"], 5)
            findings = {
                "findings": [],
                "coverage": {
                    "claims_in_ledger": 0,
                    "claims_reached_by_a_check": 0,
                    "extractor_checkable_fraction": 1.0,
                    "engine_checkable_fraction": 1.0,
                    "checks_registered": 0,
                    "checks_with_findings": 0,
                    "checks_found_nothing": 0,
                    "checks_errored": 0,
                },
                "source": {"path": "report.md", "format": "md", "sha256": "abc"},
                "findings_truncated": False,
                "agentic_only": True,
                "agentic_scan_completed": True,
            }
            (folder / "findings.json").write_text(json.dumps(findings))
            out = folder / "artifact"
            self.assertEqual(run_mod(render, "render.py", [
                "--findings", str(folder / "findings.json"),
                "--layer2", str(folder / "receipts.json"),
                "--out-dir", str(out),
                "--run-id", "ledger-run",
            ]), 0)
            art = json.loads((out / "grade-artifact.json").read_text())
            self.assertEqual(art["evidence_coverage"]["document_claims_total"], 5)
            self.assertEqual(art["evidence_coverage"]["claim_outcomes_proposed"], 5)

    def test_planted_html_with_changed_since_report_is_fix_first(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            report = folder / "report.html"
            report.write_text(PLANTED.read_text())
            (folder / "live.json").write_text(
                '{"on_hand": 10613, "as_of": "2026-08-23"}\n')
            (folder / "note.json").write_text(
                '{"note": "Both segments moved in the same direction."}\n')
            self.assertEqual(run_mod(html_arith, "html_arith.py", [
                "--report", str(report),
                "--out", str(folder / "findings.json"),
            ]), 0)
            findings = json.loads((folder / "findings.json").read_text())
            footing = [
                f for f in findings["findings"] if f["check_id"] == "ari_total_footing"]
            self.assertTrue(footing)
            self.assertAlmostEqual(abs(footing[0]["detail"]["discrepancy"]), 9000.0)
            (folder / "checks.json").write_text(json.dumps({"checks": [
                {
                    "id": "C19",
                    "type": "semantic",
                    "basis": "evidence",
                    "verdict": "confirmed",
                    "importance": "material",
                    "report_quote": "Both segments moved in the same direction.",
                    "evidence_file": "note.json",
                    "evidence_quote": "Both segments moved in the same direction.",
                    "explanation": "The evidence repeats the segment direction claim.",
                },
                {
                    "id": "C20",
                    "type": "staleness",
                    "basis": "evidence",
                    "verdict": "changed_since_report",
                    "importance": "material",
                    "report_quote": "Revenue is down 4.6% against the same week last year.",
                    "evidence_file": "live.json",
                    "evidence_json": [{"pointer": "/on_hand", "value": 10613}],
                    "explanation": "Current on-hand is 10613 as of 2026-08-23.",
                    "reconstruction_attempt": (
                        "Queried inventory_history and the daily snapshot table; "
                        "neither retains 2026-04-04 on-hand."
                    ),
                    "current_value": 10613,
                    "current_as_of": "2026-08-23",
                },
            ]}))
            self.assertEqual(run_mod(accept, "accept.py", [
                "--report", str(report),
                "--checks", str(folder / "checks.json"),
                "--evidence-dir", str(folder),
                "--out", str(folder / "receipts.json"),
            ]), 0)
            receipts = json.loads((folder / "receipts.json").read_text())
            self.assertEqual(receipts["grounded"], 2)
            out = folder / "artifact"
            self.assertEqual(run_mod(render, "render.py", [
                "--findings", str(folder / "findings.json"),
                "--layer2", str(folder / "receipts.json"),
                "--out-dir", str(out),
                "--run-id", "planted-csr",
            ]), 0)
            art = json.loads((out / "grade-artifact.json").read_text())
            self.assertEqual(art["verdict"], "fix_first")
            self.assertIn(
                "changed_since_report",
                {row["verdict"] for row in art["evidence_checks"]},
            )
            page = (out / "grade-artifact.html").read_text()
            self.assertIn("9,000", page)
            self.assertIn("Evidence confirmed", page)
            self.assertIn("Both segments moved in the same direction.", page)
            self.assertIn("Source changed after this report", page)
            self.assertIn("10,613", page)
            self.assertIn("2026-08-23", page)


if __name__ == "__main__":
    unittest.main()
