"""Grounding for the verify skill: a bad quote drops that row, not the run."""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import re
import subprocess
import sys
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


def claims_from_checks(checks_path: pathlib.Path) -> pathlib.Path:
    doc = json.loads(checks_path.read_text())
    items = doc if isinstance(doc, list) else list(doc.get("checks") or [])
    claims = []
    for index, check in enumerate(items, 1):
        check.setdefault("claim_id", f"L{index}")
        claims.append({
            "id": check["claim_id"],
            "quote": check.get("report_quote") or "",
            "importance": check.get("importance") or "material",
        })
    if isinstance(doc, dict):
        doc["checks"] = items
        checks_path.write_text(json.dumps(doc))
    else:
        checks_path.write_text(json.dumps({"checks": items}))
    path = checks_path.parent / "claims.json"
    path.write_text(json.dumps({"claims": claims}))
    return path


def run_accept(*args: str) -> int:
    args = list(args)
    if "--claims" not in args and "--checks" in args:
        checks_path = pathlib.Path(args[args.index("--checks") + 1])
        args.extend(["--claims", str(claims_from_checks(checks_path))])
    if "--findings" not in args and "--checks" in args:
        sibling = pathlib.Path(args[args.index("--checks") + 1]).parent / "findings.json"
        if sibling.is_file():
            args.extend(["--findings", str(sibling)])
    argv = sys.argv
    sys.argv = ["accept.py", *args]
    try:
        return accept.main()
    finally:
        sys.argv = argv


class AcceptTests(unittest.TestCase):
    def test_fallback_verdicts_match_schema(self) -> None:
        schema = json.loads(
            (ROOT / "skills" / "verify" / "schema.v1.json").read_text())
        enum = schema["properties"]["evidence_checks"]["items"]["properties"]["verdict"]["enum"]
        self.assertEqual(accept.FALLBACK_VERDICTS, frozenset(enum))
        self.assertEqual(accept.KNOWN_VERDICTS, frozenset(enum))
        self.assertEqual(
            accept.load_known_verdicts(pathlib.Path("/no/such/schema.json")),
            accept.FALLBACK_VERDICTS,
        )

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
            code = run_accept(
                "--report", str(report),
                "--checks", str(checks),
                "--evidence-dir", str(folder),
                "--out", str(out),
            )
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
            code = run_accept(
                "--report", str(report),
                "--checks", str(checks),
                "--evidence-dir", str(folder),
                "--out", str(folder / "receipts.json"),
            )
            self.assertEqual(code, 0)
            payload = json.loads((folder / "receipts.json").read_text())
            self.assertEqual(payload["grounded"], 1)
            self.assertEqual(payload["checks"][0]["evidence_receipt_mode"], "json-pointers")

    def test_parse_date_iso_and_month_name(self) -> None:
        from datetime import date
        self.assertEqual(accept.parse_date("2026-08-14"), date(2026, 8, 14))
        self.assertEqual(accept.parse_date("August 11, 2026"), date(2026, 8, 11))
        self.assertEqual(accept.parse_date("11 August 2026"), date(2026, 8, 11))
        self.assertTrue(accept.is_currency_claim(
            "Data is current through August 11, 2026."))
        self.assertFalse(accept.is_currency_claim(
            "Source snapshot: CRM revenue export, 2026-07-05."))

    def test_as_of_field_grounds_currency_date(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            (folder / "report.md").write_text(
                "Data is current through August 11, 2026.")
            (folder / "snap.json").write_text('{"as_of": "2026-08-14"}\n')
            (folder / "checks.json").write_text(json.dumps({"checks": [{
                "id": "C1",
                "claim_id": "L1",
                "type": "staleness",
                "basis": "evidence",
                "verdict": "not_checkable",
                "importance": "material",
                "report_quote": "Data is current through August 11, 2026.",
                "explanation": "No live source was queried.",
            }]}))
            self.assertEqual(run_accept(
                "--report", str(folder / "report.md"),
                "--checks", str(folder / "checks.json"),
                "--evidence-dir", str(folder),
                "--out", str(folder / "receipts.json"),
            ), 0)
            payload = json.loads((folder / "receipts.json").read_text())
            self.assertEqual(payload["claims"][0]["outcome"], "contradicted")
            check = next(
                row for row in payload["checks"] if row.get("verdict") == "contradicted")
            self.assertEqual(check["type"], "staleness")
            self.assertEqual(check["evidence_json"][0]["pointer"], "/as_of")

    def test_generic_date_field_grounds_currency_date(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            (folder / "report.md").write_text(
                "Data is current as of 2026-08-01.")
            (folder / "snap.json").write_text('{"date": "2026-08-09"}\n')
            (folder / "checks.json").write_text(json.dumps({"checks": [{
                "id": "C1",
                "claim_id": "L1",
                "type": "semantic",
                "basis": "evidence",
                "verdict": "not_checkable",
                "importance": "material",
                "report_quote": "Data is current as of 2026-08-01.",
                "explanation": "No warehouse query ran.",
            }]}))
            self.assertEqual(run_accept(
                "--report", str(folder / "report.md"),
                "--checks", str(folder / "checks.json"),
                "--evidence-dir", str(folder),
                "--out", str(folder / "receipts.json"),
            ), 0)
            payload = json.loads((folder / "receipts.json").read_text())
            self.assertEqual(payload["claims"][0]["outcome"], "contradicted")
            check = next(
                row for row in payload["checks"] if row.get("verdict") == "contradicted")
            self.assertEqual(check["evidence_json"][0]["pointer"], "/date")

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
            code = run_accept(
                "--report", str(report),
                "--report-text", str(sidecar),
                "--checks", str(checks),
                "--out", str(folder / "receipts.json"),
            )
            self.assertEqual(code, 0)
            payload = json.loads((folder / "receipts.json").read_text())
            self.assertEqual(payload["grounded"], 1)

    def test_missing_verdict_is_discarded_not_contradicted(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            (folder / "report.md").write_text("Revenue grew 12%.")
            (folder / "q3.json").write_text('{"revenue_yoy": 0.12}\n')
            (folder / "checks.json").write_text(json.dumps({"checks": [{
                "id": "C9",
                "type": "semantic",
                "basis": "evidence",
                "report_quote": "Revenue grew 12%.",
                "evidence_file": "q3.json",
                "evidence_quote": '"revenue_yoy": 0.12',
                "explanation": "Matches.",
            }]}))
            code = run_accept(
                "--report", str(folder / "report.md"),
                "--checks", str(folder / "checks.json"),
                "--evidence-dir", str(folder),
                "--out", str(folder / "receipts.json"),
            )
            self.assertEqual(code, 0)
            payload = json.loads((folder / "receipts.json").read_text())
            self.assertEqual(payload["grounded"], 0)
            self.assertEqual(payload["discarded"][0]["id"], "C9")
            self.assertIn("verdict is missing or unknown", payload["discarded"][0]["problems"])
            self.assertNotEqual(payload["discarded"][0].get("verdict"), "contradicted")

    def test_changed_since_report_without_attempt_is_discarded(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            (folder / "report.md").write_text("Inventory on hand is 4,200.")
            (folder / "live.json").write_text('{"on_hand": 5100, "as_of": "2026-08-23"}\n')
            (folder / "checks.json").write_text(json.dumps({"checks": [{
                "id": "C10",
                "type": "staleness",
                "basis": "evidence",
                "verdict": "changed_since_report",
                "importance": "material",
                "report_quote": "Inventory on hand is 4,200.",
                "evidence_file": "live.json",
                "evidence_json": [{"pointer": "/on_hand", "value": 5100}],
                "explanation": "The warehouse now shows 5100.",
            }]}))
            code = run_accept(
                "--report", str(folder / "report.md"),
                "--checks", str(folder / "checks.json"),
                "--evidence-dir", str(folder),
                "--out", str(folder / "receipts.json"),
            )
            self.assertEqual(code, 0)
            payload = json.loads((folder / "receipts.json").read_text())
            self.assertEqual(payload["grounded"], 0)
            problems = payload["discarded"][0]["problems"]
            self.assertIn("changed_since_report has no reconstruction attempt", problems)
            self.assertIn("changed_since_report has no current value", problems)
            self.assertIn("changed_since_report has no current as-of date", problems)

    def test_well_formed_changed_since_report_is_kept(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            (folder / "report.md").write_text("Inventory on hand is 4,200.")
            (folder / "live.json").write_text('{"on_hand": 5100, "as_of": "2026-08-23"}\n')
            (folder / "checks.json").write_text(json.dumps({"checks": [{
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
            }]}))
            code = run_accept(
                "--report", str(folder / "report.md"),
                "--checks", str(folder / "checks.json"),
                "--evidence-dir", str(folder),
                "--out", str(folder / "receipts.json"),
            )
            self.assertEqual(code, 0)
            payload = json.loads((folder / "receipts.json").read_text())
            self.assertEqual(payload["grounded"], 1)
            self.assertEqual(payload["checks"][0]["verdict"], "changed_since_report")

    def test_claim_quote_not_in_report_is_discarded(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            (folder / "report.md").write_text("Alpha is 1.")
            (folder / "claims.json").write_text(json.dumps({
                "claims": [
                    {"id": "L1", "quote": "Alpha is 1.", "importance": "material"},
                    {"id": "L2", "quote": "Beta is 99.", "importance": "material"},
                ],
            }))
            (folder / "checks.json").write_text(json.dumps({"checks": [{
                "id": "C1",
                "claim_id": "L1",
                "type": "semantic",
                "basis": "report",
                "verdict": "not_checkable",
                "importance": "material",
                "report_quote": "Alpha is 1.",
                "explanation": "No evidence.",
            }]}))
            code = run_accept(
                "--report", str(folder / "report.md"),
                "--claims", str(folder / "claims.json"),
                "--checks", str(folder / "checks.json"),
                "--out", str(folder / "receipts.json"),
            )
            self.assertEqual(code, 0)
            payload = json.loads((folder / "receipts.json").read_text())
            self.assertEqual(payload["claims_in_ledger"], 1)
            discarded = payload["discarded_claims"][0]
            self.assertEqual(discarded["id"], "L2")
            self.assertIn("claim quote not found in visible report text", discarded["problems"])

    def test_unknown_claim_id_is_discarded(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            (folder / "report.md").write_text("Alpha is 1.")
            (folder / "claims.json").write_text(json.dumps({
                "claims": [{"id": "L1", "quote": "Alpha is 1.", "importance": "material"}],
            }))
            (folder / "checks.json").write_text(json.dumps({"checks": [{
                "id": "C1",
                "claim_id": "L99",
                "type": "semantic",
                "basis": "report",
                "verdict": "not_checkable",
                "importance": "material",
                "report_quote": "Alpha is 1.",
                "explanation": "No evidence.",
            }]}))
            code = run_accept(
                "--report", str(folder / "report.md"),
                "--claims", str(folder / "claims.json"),
                "--checks", str(folder / "checks.json"),
                "--out", str(folder / "receipts.json"),
            )
            self.assertEqual(code, 0)
            payload = json.loads((folder / "receipts.json").read_text())
            self.assertEqual(payload["grounded"], 0)
            self.assertIn("claim_id 'L99' is not in the ledger", payload["discarded"][0]["problems"])

    def test_current_value_must_match_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            (folder / "report.md").write_text("Inventory on hand is 4,200.")
            (folder / "live.json").write_text('{"on_hand": 10613, "as_of": "2026-08-23"}\n')
            (folder / "checks.json").write_text(json.dumps({"checks": [{
                "id": "C12",
                "type": "staleness",
                "basis": "evidence",
                "verdict": "changed_since_report",
                "importance": "material",
                "report_quote": "Inventory on hand is 4,200.",
                "evidence_file": "live.json",
                "evidence_json": [{"pointer": "/on_hand", "value": 10613}],
                "explanation": "Current on-hand is 9999.",
                "reconstruction_attempt": "No history table remains.",
                "current_value": 9999,
                "current_as_of": "2026-08-23",
            }]}))
            code = run_accept(
                "--report", str(folder / "report.md"),
                "--checks", str(folder / "checks.json"),
                "--evidence-dir", str(folder),
                "--out", str(folder / "receipts.json"),
            )
            self.assertEqual(code, 0)
            payload = json.loads((folder / "receipts.json").read_text())
            self.assertEqual(payload["grounded"], 0)
            self.assertIn(
                "current_value does not match the receipt",
                payload["discarded"][0]["problems"],
            )

    def test_current_as_of_must_match_evidence_date(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            (folder / "report.md").write_text("Inventory on hand is 4,200.")
            (folder / "live.json").write_text(
                '{"on_hand": 10613, "as_of": "2026-08-23"}\n')
            (folder / "checks.json").write_text(json.dumps({"checks": [{
                "id": "C13",
                "type": "staleness",
                "basis": "evidence",
                "verdict": "changed_since_report",
                "importance": "material",
                "report_quote": "Inventory on hand is 4,200.",
                "evidence_file": "live.json",
                "evidence_json": [{"pointer": "/on_hand", "value": 10613}],
                "explanation": "Current on-hand is 10613.",
                "reconstruction_attempt": "No history table remains.",
                "current_value": 10613,
                "current_as_of": "2019-01-01",
            }]}))
            code = run_accept(
                "--report", str(folder / "report.md"),
                "--checks", str(folder / "checks.json"),
                "--evidence-dir", str(folder),
                "--out", str(folder / "receipts.json"),
            )
            self.assertEqual(code, 0)
            payload = json.loads((folder / "receipts.json").read_text())
            self.assertEqual(payload["grounded"], 0)
            self.assertIn(
                "current_as_of does not match evidence date",
                payload["discarded"][0]["problems"],
            )

    def test_numeric_equality_cases(self) -> None:
        self.assertTrue(accept.quantities_equal("$4.2M", 4200000))
        self.assertTrue(accept.quantities_equal("1,200", 1200))
        self.assertTrue(accept.quantities_equal("29%", 29))
        self.assertFalse(accept.quantities_equal("29%", 0.29))
        self.assertTrue(accept.quantities_equal("(1,200)", -1200))
        self.assertFalse(accept.quantities_equal(100, 200))
        self.assertTrue(accept.quote_in_text("$4.2M", "Revenue was 4200000 this quarter."))
        with tempfile.TemporaryDirectory() as raw:
            evidence = pathlib.Path(raw) / "n.json"
            evidence.write_text('{"rev": 4200000}\n')
            ok, canonical = accept.json_pointer_receipt(
                evidence, [{"pointer": "/rev", "value": "4.2M"}])
            self.assertTrue(ok)
            self.assertEqual(canonical[0]["value"], 4200000)

    def test_not_checkable_is_reached_not_confirmed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            (folder / "report.md").write_text("Alpha is 1.")
            (folder / "claims.json").write_text(json.dumps({
                "claims": [{"id": "L1", "quote": "Alpha is 1.", "importance": "material"}],
            }))
            (folder / "checks.json").write_text(json.dumps({"checks": [{
                "id": "C1",
                "claim_id": "L1",
                "type": "semantic",
                "basis": "report",
                "verdict": "not_checkable",
                "importance": "material",
                "report_quote": "Alpha is 1.",
                "explanation": "No warehouse snapshot remains for this figure.",
            }]}))
            code = run_accept(
                "--report", str(folder / "report.md"),
                "--claims", str(folder / "claims.json"),
                "--checks", str(folder / "checks.json"),
                "--out", str(folder / "receipts.json"),
            )
            self.assertEqual(code, 0)
            payload = json.loads((folder / "receipts.json").read_text())
            self.assertEqual(payload["claims_in_ledger"], 1)
            self.assertEqual(payload["claims_reached_by_a_check"], 1)
            self.assertEqual(payload["claims"][0]["outcome"], "not_checkable")
            self.assertEqual(payload["semantic_status"], "complete")

    def test_named_missing_claims_file_is_exit_2(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            (folder / "report.md").write_text("Alpha is 1.")
            (folder / "checks.json").write_text(json.dumps({"checks": []}))
            code = run_accept(
                "--report", str(folder / "report.md"),
                "--checks", str(folder / "checks.json"),
                "--claims", str(folder / "missing-claims.json"),
                "--out", str(folder / "receipts.json"),
            )
            self.assertEqual(code, 2)

    def test_confirmed_and_contradicted_must_match_receipt_values(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            (folder / "report.md").write_text("Revenue grew 12% year over year.")
            (folder / "q3.json").write_text('{"revenue_yoy": 0.098}\n')
            (folder / "claims.json").write_text(json.dumps({
                "claims": [{
                    "id": "L1",
                    "quote": "Revenue grew 12% year over year.",
                    "importance": "material",
                }],
            }))
            mismatch = {
                "id": "C1",
                "claim_id": "L1",
                "type": "semantic",
                "basis": "evidence",
                "importance": "material",
                "report_quote": "Revenue grew 12% year over year.",
                "evidence_file": "q3.json",
                "evidence_json": [{"pointer": "/revenue_yoy", "value": 0.098}],
                "explanation": "The file shows 9.8%.",
            }
            (folder / "checks.json").write_text(json.dumps({
                "checks": [{**mismatch, "verdict": "confirmed"}],
            }))
            self.assertEqual(run_accept(
                "--report", str(folder / "report.md"),
                "--claims", str(folder / "claims.json"),
                "--checks", str(folder / "checks.json"),
                "--evidence-dir", str(folder),
                "--out", str(folder / "confirmed.json"),
            ), 0)
            confirmed = json.loads((folder / "confirmed.json").read_text())
            self.assertEqual(confirmed["grounded"], 0)
            self.assertIn(
                "report and evidence unit classes are not compatible",
                confirmed["discarded"][0]["problems"],
            )
            (folder / "match.json").write_text('{"revenue_yoy": 12}\n')
            (folder / "checks.json").write_text(json.dumps({"checks": [{
                **mismatch,
                "verdict": "contradicted",
                "evidence_file": "match.json",
                "evidence_json": [{"pointer": "/revenue_yoy", "value": 12}],
                "explanation": "The file shows 12%.",
            }]}))
            self.assertEqual(run_accept(
                "--report", str(folder / "report.md"),
                "--claims", str(folder / "claims.json"),
                "--checks", str(folder / "checks.json"),
                "--evidence-dir", str(folder),
                "--out", str(folder / "contradicted.json"),
            ), 0)
            contradicted = json.loads((folder / "contradicted.json").read_text())
            self.assertEqual(contradicted["grounded"], 0)
            self.assertIn(
                "contradicted verdict is not supported by the receipt values",
                contradicted["discarded"][0]["problems"],
            )

    def test_percent_cannot_confirm_a_bare_count(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            (folder / "report.md").write_text(
                "Revenue is down 4.6% against the same week last year.")
            (folder / "live.json").write_text('{"units_now": 10613}\n')
            (folder / "claims.json").write_text(json.dumps({
                "claims": [{
                    "id": "L1",
                    "quote": "Revenue is down 4.6% against the same week last year.",
                    "importance": "material",
                }],
            }))
            (folder / "checks.json").write_text(json.dumps({"checks": [{
                "id": "C1",
                "claim_id": "L1",
                "type": "semantic",
                "basis": "evidence",
                "verdict": "confirmed",
                "importance": "material",
                "report_quote": "Revenue is down 4.6% against the same week last year.",
                "evidence_file": "live.json",
                "evidence_json": [{"pointer": "/units_now", "value": 10613}],
                "explanation": "The live file has a number.",
            }]}))
            code = run_accept(
                "--report", str(folder / "report.md"),
                "--claims", str(folder / "claims.json"),
                "--checks", str(folder / "checks.json"),
                "--evidence-dir", str(folder),
                "--out", str(folder / "receipts.json"),
            )
            self.assertEqual(code, 0)
            payload = json.loads((folder / "receipts.json").read_text())
            self.assertEqual(payload["grounded"], 0)
            self.assertIn(
                "report and evidence unit classes are not compatible",
                payload["discarded"][0]["problems"],
            )
            self.assertEqual(accept.unit_class("4.6%"), "percent")
            self.assertEqual(accept.unit_class(10613), "count")
            self.assertFalse(accept.unit_classes_compatible("4.6%", 10613))
            self.assertTrue(accept.quantities_equal("12%", 12))
            self.assertTrue(accept.quantities_equal("$4.2M", 4200000))

    def test_evidence_path_must_stay_inside_evidence_dir(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            evidence = folder / "evidence"
            evidence.mkdir()
            report = folder / "report.md"
            report.write_text("Revenue grew 12%.")
            (evidence / "q3.json").write_text('{"revenue_yoy": 0.12}\n')
            outside = folder / "outside.json"
            outside.write_text('{"revenue_yoy": 0.12}\n')
            (folder / "claims.json").write_text(json.dumps({
                "claims": [{"id": "L1", "quote": "Revenue grew 12%.",
                            "importance": "material"}],
            }))

            def row(evidence_file: str) -> dict:
                return {
                    "id": "C1",
                    "claim_id": "L1",
                    "type": "semantic",
                    "basis": "evidence",
                    "verdict": "confirmed",
                    "importance": "material",
                    "report_quote": "Revenue grew 12%.",
                    "evidence_file": evidence_file,
                    "evidence_json": [{"pointer": "/revenue_yoy", "value": 0.12}],
                    "explanation": "The file matches.",
                }

            (folder / "checks.json").write_text(json.dumps({
                "checks": [row("../outside.json")],
            }))
            self.assertEqual(run_accept(
                "--report", str(report),
                "--claims", str(folder / "claims.json"),
                "--checks", str(folder / "checks.json"),
                "--evidence-dir", str(evidence),
                "--out", str(folder / "traversal.json"),
            ), 0)
            traversal = json.loads((folder / "traversal.json").read_text())
            self.assertEqual(traversal["grounded"], 0)
            self.assertIn(
                "evidence_file is outside the evidence directory",
                traversal["discarded"][0]["problems"],
            )

            (folder / "checks.json").write_text(json.dumps({
                "checks": [row(str(outside))],
            }))
            self.assertEqual(run_accept(
                "--report", str(report),
                "--claims", str(folder / "claims.json"),
                "--checks", str(folder / "checks.json"),
                "--evidence-dir", str(evidence),
                "--out", str(folder / "absolute.json"),
            ), 0)
            absolute = json.loads((folder / "absolute.json").read_text())
            self.assertEqual(absolute["grounded"], 0)
            self.assertIn(
                "evidence_file is an absolute path",
                absolute["discarded"][0]["problems"],
            )

            (folder / "checks.json").write_text(json.dumps({
                "checks": [row("q3.json")],
            }))
            # A same-folder report used as evidence.
            (folder / "report-as-ev.json").write_text(json.dumps({
                "checks": [{
                    **row("report.md"),
                    "evidence_json": [],
                    "evidence_quote": "Revenue grew 12%.",
                }],
            }))
            self.assertEqual(run_accept(
                "--report", str(report),
                "--claims", str(folder / "claims.json"),
                "--checks", str(folder / "report-as-ev.json"),
                "--evidence-dir", str(folder),
                "--out", str(folder / "report-ev.json"),
            ), 0)
            report_ev = json.loads((folder / "report-ev.json").read_text())
            self.assertEqual(report_ev["grounded"], 0)
            self.assertIn(
                "report file is not valid evidence",
                report_ev["discarded"][0]["problems"],
            )

            link = evidence / "link.json"
            try:
                os.symlink(outside, link)
            except OSError:
                self.skipTest("symlinks are not available")
            (folder / "checks.json").write_text(json.dumps({
                "checks": [row("link.json")],
            }))
            self.assertEqual(run_accept(
                "--report", str(report),
                "--claims", str(folder / "claims.json"),
                "--checks", str(folder / "checks.json"),
                "--evidence-dir", str(evidence),
                "--out", str(folder / "symlink.json"),
            ), 0)
            linked = json.loads((folder / "symlink.json").read_text())
            self.assertEqual(linked["grounded"], 0)
            self.assertIn(
                "evidence_file is outside the evidence directory",
                linked["discarded"][0]["problems"],
            )

    def test_documented_html_and_binary_accept_commands(self) -> None:
        skill = (ROOT / "skills" / "verify" / "SKILL.md").read_text()
        html_part = skill.split("If the report is HTML", 1)[1]
        html_block = re.search(r"```bash\n(.*?)```", html_part, re.S).group(1)
        self.assertNotIn("--report-text", html_block)
        binary_part = skill.split("If the report is PDF", 1)[1]
        binary_block = re.search(r"```bash\n(.*?)```", binary_part, re.S).group(1)
        self.assertIn("--report-text", binary_block)
        with tempfile.TemporaryDirectory() as raw:
            run = pathlib.Path(raw)
            report_dir = run / "report"
            evidence = run / "evidence"
            report_dir.mkdir()
            evidence.mkdir()
            html = report_dir / "weekly.html"
            html.write_text("<p>Revenue grew 12% year over year.</p>")
            (evidence / "q3.json").write_text('{"revenue_yoy": 12}\n')
            claims = run / "claims.json"
            checks = run / "checks.json"
            claims.write_text(json.dumps({
                "claims": [{
                    "id": "L1",
                    "quote": "Revenue grew 12% year over year.",
                    "importance": "material",
                }],
            }))
            checks.write_text(json.dumps({"checks": [{
                "id": "C1",
                "claim_id": "L1",
                "type": "semantic",
                "basis": "evidence",
                "verdict": "confirmed",
                "importance": "material",
                "report_quote": "Revenue grew 12% year over year.",
                "evidence_file": "q3.json",
                "evidence_json": [{"pointer": "/revenue_yoy", "value": 12}],
                "explanation": "The file matches the report.",
            }]}))
            html_cmd = [
                sys.executable, str(SCRIPT),
                "--report", str(html),
                "--claims", str(claims),
                "--checks", str(checks),
                "--evidence-dir", str(evidence),
                "--out", str(run / "receipts-html.json"),
            ]
            html_proc = subprocess.run(html_cmd, capture_output=True, text=True)
            self.assertEqual(html_proc.returncode, 0, html_proc.stderr)
            html_payload = json.loads((run / "receipts-html.json").read_text())
            self.assertEqual(html_payload["grounded"], 1)
            missing = subprocess.run(
                html_cmd[:-2] + [
                    "--report-text", str(run / "report-visible.txt"),
                    "--out", str(run / "receipts-missing-sidecar.json"),
                ],
                capture_output=True, text=True,
            )
            self.assertEqual(missing.returncode, 0, missing.stderr)

            pdf = report_dir / "deck.pdf"
            pdf.write_bytes(b"%PDF-fake")
            sidecar = run / "report-visible.txt"
            sidecar.write_text("Revenue grew 12% year over year.")
            binary_proc = subprocess.run([
                sys.executable, str(SCRIPT),
                "--report", str(pdf),
                "--report-text", str(sidecar),
                "--claims", str(claims),
                "--checks", str(checks),
                "--evidence-dir", str(evidence),
                "--out", str(run / "receipts-pdf.json"),
            ], capture_output=True, text=True)
            self.assertEqual(binary_proc.returncode, 0, binary_proc.stderr)
            pdf_payload = json.loads((run / "receipts-pdf.json").read_text())
            self.assertEqual(pdf_payload["grounded"], 1)

    def test_as_of_date_must_be_on_same_record_as_current_value(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            (folder / "report.md").write_text("Inventory on hand is 4,200.")
            (folder / "live.json").write_text(json.dumps({
                "rows": [
                    {"on_hand": 10613},
                    {"as_of": "2026-08-23", "note": "unrelated"},
                ],
            }))
            (folder / "claims.json").write_text(json.dumps({
                "claims": [{"id": "L1", "quote": "Inventory on hand is 4,200.",
                            "importance": "material"}],
            }))
            (folder / "checks.json").write_text(json.dumps({"checks": [{
                "id": "C1",
                "claim_id": "L1",
                "type": "staleness",
                "basis": "evidence",
                "verdict": "changed_since_report",
                "importance": "material",
                "report_quote": "Inventory on hand is 4,200.",
                "evidence_file": "live.json",
                "evidence_json": [{"pointer": "/rows/0/on_hand", "value": 10613}],
                "explanation": "Current on-hand is 10613.",
                "reconstruction_attempt": "No history table remains.",
                "current_value": 10613,
                "current_as_of": "2026-08-23",
            }]}))
            self.assertEqual(run_accept(
                "--report", str(folder / "report.md"),
                "--claims", str(folder / "claims.json"),
                "--checks", str(folder / "checks.json"),
                "--evidence-dir", str(folder),
                "--out", str(folder / "receipts.json"),
            ), 0)
            payload = json.loads((folder / "receipts.json").read_text())
            self.assertEqual(payload["grounded"], 0)
            self.assertIn(
                "current_as_of is not on the same record as the current value",
                payload["discarded"][0]["problems"],
            )

    def test_presentation_must_cite_accepted_check_ids(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            (folder / "report.md").write_text("Alpha is 1.")
            (folder / "ev.json").write_text('{"alpha": 1}\n')
            (folder / "claims.json").write_text(json.dumps({
                "claims": [{"id": "L1", "quote": "Alpha is 1.",
                            "importance": "material"}],
            }))
            check = {
                "id": "C1",
                "claim_id": "L1",
                "type": "semantic",
                "basis": "evidence",
                "verdict": "confirmed",
                "importance": "material",
                "report_quote": "Alpha is 1.",
                "evidence_file": "ev.json",
                "evidence_json": [{"pointer": "/alpha", "value": 1}],
                "explanation": "Alpha matches.",
            }
            action = {
                "id": "A1",
                "text": "Keep Alpha as written.",
                "report_quote": "Alpha is 1.",
            }
            (folder / "checks.json").write_text(json.dumps({
                "checks": [check],
                "presentation": {
                    "summary": "Alpha holds.",
                    "check_ids": ["C1"],
                    "actions": [{**action, "check_ids": ["C1"]}],
                    "limits": [],
                },
            }))
            self.assertEqual(run_accept(
                "--report", str(folder / "report.md"),
                "--claims", str(folder / "claims.json"),
                "--checks", str(folder / "checks.json"),
                "--evidence-dir", str(folder),
                "--out", str(folder / "ok.json"),
            ), 0)
            ok = json.loads((folder / "ok.json").read_text())
            self.assertEqual(ok["grounded"], 1)
            self.assertEqual(ok["presentation"]["check_ids"], ["C1"])
            self.assertEqual(ok["presentation"]["actions"][0]["check_ids"], ["C1"])
            self.assertEqual(ok["presentation_problems"], [])

            (folder / "checks.json").write_text(json.dumps({
                "checks": [check],
                "presentation": {
                    "summary": "Alpha holds.",
                    "actions": [action],
                    "limits": [],
                },
            }))
            self.assertEqual(run_accept(
                "--report", str(folder / "report.md"),
                "--claims", str(folder / "claims.json"),
                "--checks", str(folder / "checks.json"),
                "--evidence-dir", str(folder),
                "--out", str(folder / "missing.json"),
            ), 0)
            missing = json.loads((folder / "missing.json").read_text())
            problems = missing["presentation_problems"]
            self.assertTrue(any("has no check ids" in item for item in problems))
            self.assertTrue(
                missing["presentation"] is None
                or not missing["presentation"].get("actions")
            )

            (folder / "checks.json").write_text(json.dumps({
                "checks": [check],
                "presentation": {
                    "summary": "Alpha holds.",
                    "check_ids": ["C99"],
                    "actions": [{**action, "check_ids": ["C99"]}],
                    "limits": [],
                },
            }))
            self.assertEqual(run_accept(
                "--report", str(folder / "report.md"),
                "--claims", str(folder / "claims.json"),
                "--checks", str(folder / "checks.json"),
                "--evidence-dir", str(folder),
                "--out", str(folder / "unknown.json"),
            ), 0)
            unknown = json.loads((folder / "unknown.json").read_text())
            self.assertTrue(any(
                "unknown check id" in item
                for item in unknown["presentation_problems"]))


if __name__ == "__main__":
    unittest.main()
