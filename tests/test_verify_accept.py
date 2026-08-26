"""Focused acceptance tests for the public-receipt architecture boundary."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import pathlib
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "verify" / "scripts"


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


accept = load("accept")
inventory = load("inventory")

REPORT = "KPI summary as of 2026-04-04. On-time delivery was 94%."
CLAIM_LABEL = "Reported on-time delivery rate"


def claim(*, claim_id: str = "L1", label: str = CLAIM_LABEL) -> dict:
    return {
        "id": claim_id,
        "quote": "On-time delivery was 94%.",
        "public_label": label,
        "importance": "material",
        "classification": "material_claim",
        "inventory_ids": ["INV1"],
    }


def source_for(path: pathlib.Path, *, source_id: str = "status-snapshot",
               kind: str = "supplied_file") -> dict:
    row = {
        "id": source_id,
        "kind": kind,
        "label": "Project status snapshot",
        "evidence_file": path.name,
        "result_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
    if kind == "live_tool":
        row["retrieval"] = {
            "retrieved_at": "2026-08-25T13:10:00Z",
            "tool": "status_api.get_week",
            "arguments": {"week": "2026-W34"},
        }
    return row


def evidence_check(*, verdict: str = "confirmed") -> dict:
    return {
        "id": "C1",
        "claim_id": "L1",
        "type": "semantic",
        "basis": "evidence",
        "verdict": verdict,
        "importance": "material",
        "addressed_clause_refs": [{
            "partition_id": "summary", "candidate_id": "K1", "clause_id": "C1",
        }],
        "report_quote": "On-time delivery was 94%.",
        "evidence_json": [
            {"pointer": "/on_time", "value": 94},
            {"pointer": "/total", "value": 100},
        ],
        "public_receipt": {
            "report_operand": {
                "label": CLAIM_LABEL,
                "value": "94%",
                "location": "KPI summary, on-time delivery line",
            },
            "decisive_operands": [
                {
                    "label": "On-time deliveries",
                    "value": 94,
                    "location": "Project status snapshot, delivery totals",
                },
                {
                    "label": "Total deliveries",
                    "value": 100,
                    "location": "Project status snapshot, delivery totals",
                },
            ],
            "calculation": {"expression": "94 / 100 * 100", "result": "94%"},
            "explanation": (
                "The retained delivery totals calculate to the same rate shown in the report."
            ),
            "source_id": "status-snapshot",
        },
    }


def same_population_alignment() -> dict:
    return {
        "status": "same_population",
        "reason": (
            "The retained source names the same report week as the dated report."
        ),
        "links": [{
            "dimension": "report_period",
            "report_quote": "KPI summary as of 2026-04-04.",
            "source_receipt": {
                "pointer": "/period", "value": "2026-04-04",
            },
        }],
    }


def unreconciled_alignment() -> dict:
    return {
        "status": "unreconciled",
        "reason": (
            "The supplied metric has no report period or scope that links it to "
            "the dated report population."
        ),
        "missing_dimensions": ["report_period", "scope"],
        "conflict_receipts": [{"pointer": "/on_time", "value": 94}],
        "reconciliation_action": (
            "Reconcile the supplied metric period and scope with the report before "
            "changing either value."
        ),
    }


def not_checkable_check() -> dict:
    return {
        "id": "C1",
        "claim_id": "L1",
        "type": "semantic",
        "basis": "report",
        "verdict": "not_checkable",
        "importance": "material",
        "addressed_clause_refs": [{
            "partition_id": "summary", "candidate_id": "K1", "clause_id": "C1",
        }],
        "report_quote": "On-time delivery was 94%.",
        "public_receipt": {
            "report_operand": {
                "label": CLAIM_LABEL,
                "value": "94%",
                "location": "KPI summary, on-time delivery line",
            },
            "decisive_operands": [],
            "explanation": (
                "No approved source was available to verify the reported delivery rate."
            ),
        },
    }


def write_invalid_preflight_bundle(folder: pathlib.Path) -> dict[str, pathlib.Path]:
    """Write one check with an invalid notice and missing evidence source link."""
    report = folder / "report.md"
    report_quote = (
        "Revenue KPI $359,490.34 and segment table Total $359,490.34."
    )
    report.write_text(report_quote + "\n")
    evidence = folder / "revenue.json"
    evidence.write_text('{"segment_alpha":218385.67,"segment_beta":132104.67}\n')
    findings = folder / "findings.json"
    findings.write_text(json.dumps({
        "inventory": {
            "complete": True,
            "items": [
                {
                    "id": "INV-KPI", "displayed": "$359,490.34",
                    "quote": "$359,490.34", "location": "Revenue KPI tile",
                    "importance": "unclassified",
                },
                {
                    "id": "INV-TOTAL", "displayed": "$359,490.34",
                    "quote": "$359,490.34", "location": "segment table Total row",
                    "importance": "unclassified",
                },
            ],
        },
    }))
    member_refs = [
        {"partition_id": "kpi", "candidate_id": "K1", "clause_id": "TOTAL"},
        {"partition_id": "table", "candidate_id": "T1", "clause_id": "TOTAL"},
    ]
    claims = folder / "claims.json"
    claims.write_text(json.dumps({
        "claims": [{
            "id": "L1", "quote": report_quote,
            "public_label": "Total weekly revenue", "importance": "material",
            "classification": "material_claim",
            "inventory_ids": ["INV-KPI", "INV-TOTAL"],
            "member_refs": member_refs,
        }],
        "coordinator": {
            "partition_results": [
                {
                    "partition_id": "kpi",
                    "candidates": [{
                        "id": "K1", "quote": "$359,490.34",
                        "public_label": "Total weekly revenue",
                        "importance": "material", "classification": "material_claim",
                        "inventory_ids": ["INV-KPI"],
                        "clauses": [{
                            "id": "TOTAL", "quote": "$359,490.34",
                            "public_label": "Total weekly revenue",
                        }],
                    }],
                },
                {
                    "partition_id": "table",
                    "candidates": [{
                        "id": "T1", "quote": "$359,490.34",
                        "public_label": "Total weekly revenue",
                        "importance": "material", "classification": "material_claim",
                        "inventory_ids": ["INV-TOTAL"],
                        "clauses": [{
                            "id": "TOTAL", "quote": "$359,490.34",
                            "public_label": "Total weekly revenue",
                        }],
                    }],
                },
            ],
            "membership": [
                {**member_refs[0], "canonical_claim_id": "L1"},
                {**member_refs[1], "canonical_claim_id": "L1"},
            ],
            "verifier_assignments": [{"verifier_id": "V1", "claim_ids": ["L1"]}],
        },
    }))
    statement = (
        "Both displayed totals must change from $359,490.34 to $350,490.34."
    )
    check = {
        "id": "C1", "claim_id": "L1", "type": "arithmetic",
        "basis": "evidence", "verdict": "contradicted",
        "importance": "material", "severity": "high",
        "report_quote": report_quote,
        "addressed_clause_refs": member_refs,
        "evidence_json": [
            {"pointer": "/segment_alpha", "value": 218385.67},
            {"pointer": "/segment_beta", "value": 132104.67},
        ],
        "correction_notice": {
            "statement": statement,
            "report_value": "$359,490.34",
            "replacement_value": "$350,490.34",
            "locations": ["Revenue KPI tile", "segment table Total row"],
        },
        "public_receipt": {
            "report_operand": {
                "label": "Total weekly revenue", "value": "$359,490.34",
                "location": "Revenue KPI tile and segment table Total row",
            },
            "decisive_operands": [
                {
                    "label": "Segment Alpha revenue", "value": "$218,385.67",
                    "location": "segment table, Segment Alpha row",
                },
                {
                    "label": "Segment Beta revenue", "value": "$132,104.67",
                    "location": "segment table, Segment Beta row",
                },
            ],
            "calculation": {
                "expression": "218385.67 + 132104.67",
                "result": "$350,490.34",
            },
            "explanation": (
                "The two segment values total $350,490.34, not $359,490.34. "
                + statement
            ),
        },
    }
    checks = folder / "checks.json"
    checks.write_text(json.dumps({
        "sources": [source_for(evidence, source_id="revenue-source")],
        "checks": [check],
        "presentation": {
            "summary": "The accepted result requires the displayed total to be corrected.",
            "check_ids": ["C1"],
            "actions": [{
                "id": "A1", "kind": "correct_report", "text": statement,
                "report_quote": report_quote, "check_ids": ["C1"],
            }],
            "limits": [],
        },
    }))
    return {
        "report": report, "claims": claims, "checks": checks,
        "findings": findings, "evidence_dir": folder,
    }


def run_cli_bundle(paths: dict[str, pathlib.Path], out: pathlib.Path, *,
                   preflight: bool) -> int:
    argv = sys.argv
    sys.argv = [
        "accept.py", "--report", str(paths["report"]),
        "--claims", str(paths["claims"]), "--checks", str(paths["checks"]),
        "--findings", str(paths["findings"]),
        "--evidence-dir", str(paths["evidence_dir"]), "--out", str(out),
    ]
    if preflight:
        sys.argv.insert(1, "--preflight-only")
    try:
        return accept.main()
    finally:
        sys.argv = argv


class ExactGroundingTests(unittest.TestCase):
    def test_schema_is_the_only_verdict_source_and_load_failure_is_fatal(self) -> None:
        self.assertFalse(hasattr(accept, "FALLBACK_VERDICTS"))
        self.assertEqual(
            accept.KNOWN_VERDICTS,
            frozenset({
                "confirmed", "contradicted", "not_checkable",
                "changed_since_report",
            }),
        )
        with tempfile.TemporaryDirectory() as raw:
            with self.assertRaises(RuntimeError):
                accept.load_known_verdicts(pathlib.Path(raw) / "missing.json")

    def test_deleted_discovery_apis_do_not_exist(self) -> None:
        for name in (
            "json_field_receipt", "_DATE_KEYS", "_dates_on_object",
            "_dates_on_same_record", "_csv_dates_for_value",
            "_parent_record", "_json_objects",
        ):
            self.assertFalse(hasattr(accept, name), name)

    def test_exact_quote_normalizes_only_visible_text(self) -> None:
        self.assertTrue(accept.quote_in_text(
            "On-time delivery was 94%.",
            "<p>On-time   delivery was <strong>94%</strong>.</p>",
        ))
        self.assertFalse(accept.quote_in_text("$4.2M", "Revenue was 4200000."))
        self.assertFalse(accept.quote_in_text("94", "On-time delivery was 94%."))
        self.assertFalse(accept.quote_in_text("10", "Inventory was 10,481."))

    def test_numeric_equivalence_is_allowed_after_an_explicit_pointer(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = pathlib.Path(raw) / "revenue.json"
            path.write_text('{"revenue": 4200000}\n')
            matched, canonical = accept.json_pointer_receipt(
                path, [{"pointer": "/revenue", "value": "$4.2M"}])
            self.assertTrue(matched)
            self.assertEqual(canonical, [{"pointer": "/revenue", "value": 4200000}])

    def test_json_field_fragments_cannot_ground_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            evidence = folder / "status.json"
            evidence.write_text('{"on_time": 94, "total": 100}\n')
            sources, problems = accept.validate_sources(
                folder, [source_for(evidence)], folder / "report.md")
            self.assertEqual(problems, [])
            check = evidence_check()
            check.pop("evidence_json")
            check["evidence_quote"] = '"on_time": 94, ... "total": 100'
            kept, dropped = accept.validate_receipts(
                REPORT, folder, [check], {"L1"}, folder / "report.md",
                sources=sources, claim_labels={"L1": CLAIM_LABEL})
            self.assertEqual(kept, [])
            self.assertIn(
                "evidence receipt needs exact pointers or a grounded exact quote",
                dropped[0]["problems"],
            )

    def test_exact_normalized_evidence_quote_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            evidence = folder / "status.txt"
            evidence.write_text("On-time deliveries 94; total deliveries 100.\n")
            sources, problems = accept.validate_sources(
                folder, [source_for(evidence)], folder / "report.md")
            self.assertEqual(problems, [])
            check = evidence_check()
            check.pop("evidence_json")
            check["evidence_quote"] = "On-time deliveries 94; total deliveries 100."
            kept, dropped = accept.validate_receipts(
                REPORT, folder, [check], {"L1"}, folder / "report.md",
                sources=sources, claim_labels={"L1": CLAIM_LABEL})
            self.assertEqual(dropped, [])
            self.assertEqual(kept[0]["evidence_receipt_mode"], "exact-quote")


class SourceAndClaimTests(unittest.TestCase):
    def test_checks_document_requires_top_level_sources(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = pathlib.Path(raw) / "checks.json"
            path.write_text('{"checks": []}\n')
            with self.assertRaisesRegex(ValueError, "sources"):
                accept.load_checks(path)

    def test_host_authored_severity_is_exact_and_not_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            evidence = folder / "status.json"
            evidence.write_text('{"on_time": 94, "total": 100}\n')
            sources, problems = accept.validate_sources(
                folder, [source_for(evidence)], folder / "report.md")
            self.assertEqual(problems, [])
            check = evidence_check()
            check["severity"] = "medium"
            kept, dropped = accept.validate_receipts(
                REPORT, folder, [check], {"L1"}, folder / "report.md",
                sources=sources, claim_labels={"L1": CLAIM_LABEL})
            self.assertEqual(dropped, [])
            self.assertEqual(kept[0]["severity"], "medium")
            check["severity"] = "major"
            kept, dropped = accept.validate_receipts(
                REPORT, folder, [check], {"L1"}, folder / "report.md",
                sources=sources, claim_labels={"L1": CLAIM_LABEL})
            self.assertEqual(kept, [])
            self.assertIn("check severity is unknown", dropped[0]["problems"])

    def test_dated_evidence_contradiction_requires_grounded_same_population(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            evidence = folder / "status.json"
            evidence.write_text('{"on_time": 92, "total": 100}\n')
            sources, source_problems = accept.validate_sources(
                folder, [source_for(evidence)], folder / "report.md")
            self.assertEqual(source_problems, [])
            check = evidence_check(verdict="contradicted")
            check["evidence_json"][0]["value"] = 92
            check["public_receipt"]["decisive_operands"][0]["value"] = 92
            check["public_receipt"]["calculation"] = {
                "expression": "92 / 100 * 100", "result": "92%",
            }
            check["public_receipt"]["explanation"] = (
                "The retained delivery total calculates to a different rate than the report."
            )
            kept, dropped = accept.validate_receipts(
                REPORT, folder, [check], {"L1"}, folder / "report.md",
                sources=sources, claim_labels={"L1": CLAIM_LABEL},
                report_date="2026-04-04", report_period="Week ending 2026-04-04",
            )
            self.assertEqual(kept, [])
            self.assertIn(
                "dated evidence contradiction requires population_alignment",
                dropped[0]["problems"],
            )

    def test_same_population_alignment_resolves_only_exact_agent_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            evidence = folder / "status.json"
            evidence.write_text(
                '{"period":"2026-04-04","on_time":92,"total":100}\n')
            sources, source_problems = accept.validate_sources(
                folder, [source_for(evidence)], folder / "report.md")
            self.assertEqual(source_problems, [])
            check = evidence_check(verdict="contradicted")
            check["evidence_json"][0]["value"] = 92
            check["public_receipt"]["decisive_operands"][0]["value"] = 92
            check["public_receipt"]["calculation"] = {
                "expression": "92 / 100 * 100", "result": "92%",
            }
            check["public_receipt"]["explanation"] = (
                "The retained delivery total calculates to a different rate than the report."
            )
            check["population_alignment"] = same_population_alignment()
            kept, dropped = accept.validate_receipts(
                REPORT, folder, [check], {"L1"}, folder / "report.md",
                sources=sources, claim_labels={"L1": CLAIM_LABEL},
                report_date="2026-04-04", report_period="Week ending 2026-04-04",
            )
            self.assertEqual(dropped, [])
            self.assertEqual(
                kept[0]["population_alignment"]["links"][0]["source_receipt"],
                {"pointer": "/period", "value": "2026-04-04"},
            )

            check["population_alignment"]["links"][0]["source_receipt"]["pointer"] = "/missing"
            kept, dropped = accept.validate_receipts(
                REPORT, folder, [check], {"L1"}, folder / "report.md",
                sources=sources, claim_labels={"L1": CLAIM_LABEL},
                report_date="2026-04-04", report_period="Week ending 2026-04-04",
            )
            self.assertEqual(kept, [])
            self.assertIn(
                "population_alignment.links[0].source_receipt did not match the retained source",
                dropped[0]["problems"],
            )

    def test_unreconciled_population_cannot_be_a_contradiction(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            evidence = folder / "status.json"
            evidence.write_text('{"on_time":92,"total":100}\n')
            sources, _ = accept.validate_sources(
                folder, [source_for(evidence)], folder / "report.md")
            check = evidence_check(verdict="contradicted")
            check["evidence_json"][0]["value"] = 92
            check["public_receipt"]["decisive_operands"][0]["value"] = 92
            check["population_alignment"] = unreconciled_alignment()
            kept, dropped = accept.validate_receipts(
                REPORT, folder, [check], {"L1"}, folder / "report.md",
                sources=sources, claim_labels={"L1": CLAIM_LABEL},
                report_date="2026-04-04", report_period="Week ending 2026-04-04",
            )
            self.assertEqual(kept, [])
            self.assertIn(
                "unreconciled population cannot have verdict 'contradicted'; use not_checkable",
                dropped[0]["problems"],
            )

    def test_source_digest_kind_and_retrieval_are_exact(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            evidence = folder / "status.json"
            evidence.write_text('{"on_time": 94}\n')
            static = source_for(evidence)
            accepted, discarded = accept.validate_sources(folder, [static])
            self.assertEqual(discarded, [])
            self.assertEqual(accepted[0]["kind"], "supplied_file")
            bad_digest = dict(static, result_sha256="0" * 64)
            accepted, discarded = accept.validate_sources(folder, [bad_digest])
            self.assertEqual(accepted, [])
            self.assertIn("does not match", " ".join(discarded[0]["problems"]))
            bad_static = dict(static, retrieval={
                "retrieved_at": "2026-08-25T13:10:00Z",
                "tool": "status_api.get_week", "arguments": {},
            })
            accepted, discarded = accept.validate_sources(folder, [bad_static])
            self.assertEqual(accepted, [])
            self.assertIn("must not declare live retrieval", " ".join(discarded[0]["problems"]))
            null_static = dict(static, retrieval=None)
            accepted, discarded = accept.validate_sources(folder, [null_static])
            self.assertEqual(accepted, [])
            self.assertIn("must not declare live retrieval", " ".join(discarded[0]["problems"]))
            live = source_for(evidence, kind="live_tool")
            accepted, discarded = accept.validate_sources(folder, [live])
            self.assertEqual(discarded, [])
            self.assertEqual(accepted[0], live)
            invalid_time = source_for(evidence, kind="live_tool")
            invalid_time["retrieval"]["retrieved_at"] = "2026-99-99T13:10:00Z"
            accepted, discarded = accept.validate_sources(folder, [invalid_time])
            self.assertEqual(accepted, [])
            self.assertIn("retrieved_at", " ".join(discarded[0]["problems"]))

    def test_source_labels_reject_private_or_vague_values(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            evidence = folder / "status.json"
            evidence.write_text('{}\n')
            for label in ("supplied evidence", "/private/tmp/status.json"):
                row = source_for(evidence)
                row["label"] = label
                accepted, discarded = accept.validate_sources(folder, [row])
                self.assertEqual(accepted, [])
                self.assertTrue(discarded[0]["problems"])

    def test_claim_requires_public_safe_label_and_exact_quote(self) -> None:
        kept, dropped = accept.validate_claims(REPORT, [claim()])
        self.assertEqual(dropped, [])
        self.assertEqual(kept[0]["public_label"], CLAIM_LABEL)
        for bad in ("", "row 2", "/metrics/on_time"):
            kept, dropped = accept.validate_claims(REPORT, [claim(label=bad)])
            self.assertEqual(kept, [])
            self.assertTrue(any("public_label" in p for p in dropped[0]["problems"]))
        row = claim()
        row["quote"] = "On-time delivery was 95%."
        kept, dropped = accept.validate_claims(REPORT, [row])
        self.assertEqual(kept, [])
        self.assertIn("claim quote not found", " ".join(dropped[0]["problems"]))

    def test_missing_inventory_classification_fails_closed(self) -> None:
        row = claim()
        row.pop("classification")
        kept, dropped = accept.validate_claims(REPORT, [row])
        self.assertEqual(kept, [])
        self.assertEqual(
            dropped[0]["problems"],
            ["claim classification is missing or unknown"],
        )

    def test_non_object_claim_fails_closed_with_exact_reason(self) -> None:
        kept, dropped = accept.validate_claims(REPORT, ["not-a-claim"])
        self.assertEqual(kept, [])
        self.assertEqual(dropped[0]["problems"], ["claim is not an object"])

    def test_inventory_coverage_uses_only_exact_ids_not_quote_fuzzing(self) -> None:
        inv = {
            "complete": True,
            "items": [{
                "id": "INV1", "displayed": "$4.2M", "location": "line1",
                "importance": "material", "classification": "material_claim",
            }],
        }
        ledger = [{
            "id": "L1", "quote": "A different visible sentence.",
            "inventory_ids": ["INV1"], "importance": "material",
            "classification": "material_claim",
            "outcome": "not_checkable",
        }]
        self.assertFalse(hasattr(inventory, "item_matches_claim"))
        covered = inventory.cover(inv, ledger)
        self.assertEqual(covered["accounted"], 1)
        self.assertEqual(covered["completed"], 1)


class ReceiptTests(unittest.TestCase):
    def validate(self, folder: pathlib.Path, check: dict, source: dict | None = None,
                 *, report: str = REPORT, label: str = CLAIM_LABEL):
        sources = []
        if source is not None:
            sources, source_drops = accept.validate_sources(
                folder, [source], folder / "report.md")
            self.assertEqual(source_drops, [])
        return accept.validate_receipts(
            report, folder, [check], {"L1"}, folder / "report.md",
            sources=sources, claim_labels={"L1": label},
            report_date="2026-04-04",
        )

    def test_evidence_receipt_and_claim_label_handoff_are_exact(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            evidence = folder / "status.json"
            evidence.write_text('{"on_time": 94, "total": 100}\n')
            kept, dropped = self.validate(folder, evidence_check(), source_for(evidence))
            self.assertEqual(dropped, [])
            self.assertEqual(kept[0]["public_receipt"], evidence_check()["public_receipt"])
            wrong = evidence_check()
            wrong["public_receipt"]["report_operand"]["label"] = "Delivery percentage"
            kept, dropped = self.validate(folder, wrong, source_for(evidence))
            self.assertEqual(kept, [])
            self.assertIn(
                "public_receipt.report_operand.label does not match claim public_label",
                dropped[0]["problems"],
            )

    def test_public_receipt_fails_closed_for_vague_private_or_missing_copy(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            evidence = folder / "status.json"
            evidence.write_text('{"on_time": 94, "total": 100}\n')
            source = source_for(evidence)
            cases = []
            for label in ("row 2", "operand 1", "item 3", "value 4"):
                row = evidence_check()
                row["public_receipt"]["decisive_operands"][0]["label"] = label
                cases.append(row)
            row = evidence_check()
            row["public_receipt"]["report_operand"]["location"] = "/metrics/on_time"
            cases.append(row)
            row = evidence_check()
            row["public_receipt"]["explanation"] = "Confirmed."
            cases.append(row)
            for check in cases:
                kept, dropped = self.validate(folder, check, source)
                self.assertEqual(kept, [])
                self.assertTrue(dropped[0]["problems"])

    def test_evidence_basis_requires_retained_source_and_exact_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            kept, dropped = self.validate(pathlib.Path(raw), evidence_check())
            self.assertEqual(kept, [])
            self.assertTrue(any("source_id" in p for p in dropped[0]["problems"]))

    def test_evidence_basis_not_checkable_still_requires_retained_source(self) -> None:
        check = not_checkable_check()
        check["basis"] = "evidence"
        with tempfile.TemporaryDirectory() as raw:
            kept, dropped = self.validate(pathlib.Path(raw), check)
        self.assertEqual(kept, [])
        self.assertIn(
            "public_receipt.source_id is required for evidence basis",
            dropped[0]["problems"],
        )

    def test_report_basis_recomputes_only_agent_authored_arithmetic(self) -> None:
        report = "On-time delivery was 94%; 94 deliveries out of 100 total."
        check = evidence_check()
        check["basis"] = "report"
        check.pop("evidence_json")
        check["report_quote"] = report
        check["public_receipt"].pop("source_id")
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            kept, dropped = self.validate(folder, check, report=report)
            self.assertEqual(dropped, [])
            self.assertEqual(kept[0]["public_receipt"]["calculation"]["result"], "94%")
            wrong = json.loads(json.dumps(check))
            wrong["public_receipt"]["calculation"]["result"] = "95%"
            kept, dropped = self.validate(folder, wrong, report=report)
            self.assertEqual(kept, [])
            self.assertIn("computed expression", " ".join(dropped[0]["problems"]))

    def test_numeric_report_arithmetic_cannot_confirm_unequal_result(self) -> None:
        report = (
            "Revenue KPI $359,490.34. Segment Alpha $218,385.67. "
            "Segment Beta $132,104.67."
        )
        check = {
            "id": "C1",
            "claim_id": "L1",
            "type": "arithmetic",
            "basis": "report",
            "verdict": "confirmed",
            "importance": "material",
            "report_quote": report,
            "public_receipt": {
                "report_operand": {
                    "label": "Total weekly revenue",
                    "value": "$359,490.34",
                    "location": "Revenue KPI and segment table Total row",
                },
                "decisive_operands": [
                    {
                        "label": "Segment Alpha weekly revenue",
                        "value": "$218,385.67",
                        "location": "Segment table, Segment Alpha row",
                    },
                    {
                        "label": "Segment Beta weekly revenue",
                        "value": "$132,104.67",
                        "location": "Segment table, Segment Beta row",
                    },
                ],
                "calculation": {
                    "expression": "218385.67 + 132104.67",
                    "result": "$350,490.34",
                },
                "explanation": (
                    "The two segment values sum to a different amount than the total shown in the report."
                ),
            },
        }
        with tempfile.TemporaryDirectory() as raw:
            kept, dropped = self.validate(
                pathlib.Path(raw), check, report=report, label="Total weekly revenue")
        self.assertEqual(kept, [])
        self.assertIn(
            "confirmed report-basis arithmetic result does not equal the report operand",
            dropped[0]["problems"],
        )

    def test_numeric_report_arithmetic_accepts_declared_contradiction(self) -> None:
        report = (
            "Revenue KPI $359,490.34. Segment Alpha $218,385.67. "
            "Segment Beta $132,104.67."
        )
        check = {
            "id": "C1",
            "claim_id": "L1",
            "type": "arithmetic",
            "basis": "report",
            "verdict": "contradicted",
            "importance": "material",
            "severity": "high",
            "report_quote": report,
            "public_receipt": {
                "report_operand": {
                    "label": "Total weekly revenue",
                    "value": "$359,490.34",
                    "location": "Revenue KPI and segment table Total row",
                },
                "decisive_operands": [
                    {
                        "label": "Segment Alpha weekly revenue",
                        "value": "$218,385.67",
                        "location": "Segment table, Segment Alpha row",
                    },
                    {
                        "label": "Segment Beta weekly revenue",
                        "value": "$132,104.67",
                        "location": "Segment table, Segment Beta row",
                    },
                ],
                "calculation": {
                    "expression": "218385.67 + 132104.67",
                    "result": "$350,490.34",
                },
                "explanation": (
                    "The two segment values sum to a different amount than the total shown in both report locations."
                ),
            },
        }
        with tempfile.TemporaryDirectory() as raw:
            kept, dropped = self.validate(
                pathlib.Path(raw), check, report=report, label="Total weekly revenue")
        self.assertEqual(dropped, [])
        self.assertEqual(kept[0]["verdict"], "contradicted")

    def test_not_checkable_requires_public_receipt_and_no_decisive_operands(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            kept, dropped = self.validate(folder, not_checkable_check())
            self.assertEqual(dropped, [])
            self.assertEqual(kept[0]["verdict"], "not_checkable")
            missing = not_checkable_check()
            missing.pop("public_receipt")
            kept, dropped = self.validate(folder, missing)
            self.assertEqual(kept, [])
            self.assertIn("public_receipt is missing", " ".join(dropped[0]["problems"]))
            fake = not_checkable_check()
            fake["public_receipt"]["decisive_operands"] = [{
                "label": "Unverified value", "value": 94,
                "location": "Unknown source",
            }]
            kept, dropped = self.validate(folder, fake)
            self.assertEqual(kept, [])
            self.assertIn("must be empty", " ".join(dropped[0]["problems"]))

    def test_report_quote_2_is_rejected(self) -> None:
        check = not_checkable_check()
        check["report_quote_2"] = "KPI summary as of 2026-04-04."
        with tempfile.TemporaryDirectory() as raw:
            kept, dropped = self.validate(pathlib.Path(raw), check)
        self.assertEqual(kept, [])
        self.assertTrue(any(
            problem.startswith("report_quote_2 is not accepted")
            for problem in dropped[0]["problems"]
        ))


class TemporalTests(unittest.TestCase):
    def temporal(self, *, date_receipt: dict) -> dict:
        return {
            "id": "C1", "claim_id": "L1", "type": "staleness",
            "basis": "evidence", "verdict": "changed_since_report",
            "importance": "material",
            "report_quote": "Inventory was 10,481 units as of 2026-04-04.",
            "report_value": 10481, "report_date": "2026-04-04",
            "current_value": 10613, "current_as_of": "2026-08-23",
            "reconstruction_attempt": (
                "The approved history source was checked, but no report-date row was retained."
            ),
            "evidence_json": [{"pointer": "/units", "value": 10613}],
            "date_receipt": date_receipt,
            "public_receipt": {
                "report_operand": {
                    "label": "Reported inventory units", "value": 10481,
                    "location": "Inventory summary, units line",
                },
                "decisive_operands": [
                    {
                        "label": "Report date", "value": "2026-04-04",
                        "location": "Inventory summary, as-of date",
                    },
                    {
                        "label": "Later recorded inventory units", "value": 10613,
                        "location": "Inventory snapshot, units field",
                    },
                    {
                        "label": "Later snapshot date", "value": "2026-08-23",
                        "location": "Inventory snapshot, as-of field",
                    },
                ],
                "explanation": (
                    "The later snapshot records 10,613 units after the report recorded 10,481 units."
                ),
                "reconstruction_attempt": (
                    "The approved history source was checked, but no report-date row was retained."
                ),
                "source_id": "status-snapshot",
            },
        }

    def validate(self, folder: pathlib.Path, check: dict, evidence: pathlib.Path):
        sources, dropped = accept.validate_sources(
            folder, [source_for(evidence)], folder / "report.md")
        self.assertEqual(dropped, [])
        return accept.validate_receipts(
            check["report_quote"], folder, [check], {"L1"}, folder / "report.md",
            sources=sources, claim_labels={"L1": "Reported inventory units"},
            report_date="2026-04-04",
        )

    def test_temporal_date_pointer_is_resolved_exactly(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            evidence = folder / "status.json"
            evidence.write_text('{"units": 10613, "as_of": "2026-08-23"}\n')
            check = self.temporal(date_receipt={
                "pointer": "/as_of", "value": "2026-08-23"})
            kept, dropped = self.validate(folder, check, evidence)
            self.assertEqual(dropped, [])
            self.assertEqual(kept[0]["date_receipt"]["value"], "2026-08-23")
            check["date_receipt"]["pointer"] = "/unrelated_date"
            kept, dropped = self.validate(folder, check, evidence)
            self.assertEqual(kept, [])
            self.assertIn("date_receipt pointer", " ".join(dropped[0]["problems"]))

    def test_temporal_date_quote_is_resolved_exactly(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            evidence = folder / "status.txt"
            evidence.write_text("Units 10613 recorded on 2026-08-23.\n")
            check = self.temporal(date_receipt={"quote": "recorded on 2026-08-23"})
            check.pop("evidence_json")
            check["evidence_quote"] = "Units 10613 recorded on 2026-08-23."
            kept, dropped = self.validate(folder, check, evidence)
            self.assertEqual(dropped, [])
            self.assertEqual(kept[0]["date_receipt"], check["date_receipt"])

    def test_temporal_missing_or_mismatched_date_receipt_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            evidence = folder / "status.json"
            evidence.write_text('{"units": 10613, "as_of": "2026-08-23"}\n')
            for date_receipt in ({}, {"pointer": "/as_of", "value": "2026-08-22"}):
                check = self.temporal(date_receipt=date_receipt)
                kept, dropped = self.validate(folder, check, evidence)
                self.assertEqual(kept, [])
                self.assertTrue(any("date_receipt" in p for p in dropped[0]["problems"]))


class LedgerTests(unittest.TestCase):
    def test_arithmetic_use_stays_internal_and_does_not_complete_claim(self) -> None:
        ledger = [claim() | {"outcome": "not_reached", "check_id": None}]
        checks, updated = accept.attach_arithmetic_uses(
            ledger, [], [{"inventory_ids": ["INV1"]}])
        self.assertEqual(checks, [])
        self.assertEqual(updated[0]["outcome"], "not_reached")
        self.assertIsNone(updated[0]["check_id"])
        self.assertEqual(updated[0]["arithmetic_inventory_ids"], ["INV1"])
        self.assertNotIn("found_by", updated[0])
        self.assertNotIn("verification_mode", updated[0])

    def test_one_canonical_claim_cannot_have_mixed_outcomes(self) -> None:
        checks = [
            {"id": "C1", "claim_id": "L1", "verdict": "confirmed"},
            {"id": "C2", "claim_id": "L1", "verdict": "contradicted"},
        ]
        row = accept.attach_claim_outcomes([claim()], checks)[0]
        self.assertEqual(row["outcome"], "not_reached")
        self.assertIsNone(row["check_id"])

    def test_explicit_structural_context_is_outside_material_ledger(self) -> None:
        inv = {
            "complete": True,
            "items": [
                {
                    "id": "INV1", "displayed": "Weekly status", "quote": "Weekly status",
                    "location": "line1", "importance": "unclassified",
                },
                {
                    "id": "INV2", "displayed": "Owner 07", "quote": "Owner 07",
                    "location": "line2", "importance": "unclassified",
                },
                {
                    "id": "INV3", "displayed": "Week ending April 4, 2026",
                    "quote": "Week ending April 4, 2026", "location": "line3",
                    "importance": "unclassified",
                },
                {
                    "id": "INV4", "displayed": "Revenue", "quote": "Revenue",
                    "location": "line4", "importance": "unclassified",
                },
                {
                    "id": "INV5", "displayed": "Data is current through April 4, 2026.",
                    "quote": "Data is current through April 4, 2026.", "location": "line5",
                    "importance": "unclassified",
                },
            ],
        }
        candidates = []
        membership = []
        for index, inventory_id in enumerate(("INV1", "INV2", "INV3", "INV4"), 1):
            item = inv["items"][index - 1]
            candidates.append({
                "id": f"S{index}",
                "quote": item["displayed"],
                "classification": "structural_context",
                "importance": "supporting",
                "reason": "This visible item organizes the report and is not an analytical assertion.",
                "inventory_ids": [inventory_id],
            })
            membership.append({
                "partition_id": "report-shell",
                "candidate_id": f"S{index}",
                "canonical_claim_id": None,
            })
        candidates.append({
            "id": "M1",
            "quote": "Data is current through April 4, 2026.",
            "public_label": "Reported data currency date",
            "classification": "material_claim",
            "importance": "material",
            "inventory_ids": ["INV5"],
            "clauses": [{
                "id": "C1", "quote": "Data is current through April 4, 2026.",
                "public_label": "Reported data currency date",
            }],
        })
        membership.append({
            "partition_id": "report-shell",
            "candidate_id": "M1",
            "clause_id": "C1",
            "canonical_claim_id": "L1",
        })
        claims = [{
            "id": "L1",
            "quote": "Data is current through April 4, 2026.",
            "public_label": "Reported data currency date",
            "classification": "material_claim",
            "importance": "material",
            "inventory_ids": ["INV5"],
            "member_refs": [{
                "partition_id": "report-shell", "candidate_id": "M1",
                "clause_id": "C1",
            }],
        }]
        coordinator = {
            "partition_results": [{
                "partition_id": "report-shell",
                "candidates": candidates,
            }],
            "membership": membership,
            "verifier_assignments": [{"verifier_id": "V1", "claim_ids": ["L1"]}],
        }
        handoff, problems = accept.validate_coordinator_handoff(
            claims, coordinator, inv)
        self.assertEqual(problems, [])
        self.assertEqual(len(handoff["structural_context"]), 4)
        self.assertEqual(handoff["material_claim_ids"], ["L1"])

        grounded, discarded = accept.validate_claims(
            " ".join(item["displayed"] for item in inv["items"]), claims)
        self.assertEqual(discarded, [])
        ledger = accept.attach_claim_outcomes(
            grounded, [{"id": "C1", "claim_id": "L1", "verdict": "not_checkable"}])
        discarded_claims = []
        ledger = accept.apply_host_classifications(
            ledger, discarded_claims, inv,
            structural_context=handoff["structural_context"],
        )
        self.assertEqual(discarded_claims, [])
        covered = inventory.cover(
            inv, ledger, structural_context=handoff["structural_context"])
        self.assertEqual(covered["missing"], [])
        self.assertEqual(covered["material"], 1)
        self.assertEqual([row["id"] for row in ledger], ["L1"])
        self.assertTrue(all(
            item["classification"] == "structural_context"
            for item in inv["items"][:4]
        ))

    def test_duplicate_inventory_assignment_fails_closed(self) -> None:
        inv = {
            "complete": True,
            "items": [{
                "id": "INV1", "displayed": "Revenue was $10.",
                "quote": "Revenue was $10.", "location": "line1",
                "importance": "unclassified",
            }],
        }
        claims = [
            {
                "id": "L1", "quote": "Revenue was $10.",
                "public_label": "Reported revenue", "importance": "material",
                "classification": "material_claim", "inventory_ids": ["INV1"],
                "member_refs": [{
                    "partition_id": "p1", "candidate_id": "A", "clause_id": "C1",
                }],
            },
            {
                "id": "L2", "quote": "Revenue was $10.",
                "public_label": "Second reported revenue", "importance": "material",
                "classification": "material_claim", "inventory_ids": ["INV1"],
                "member_refs": [{
                    "partition_id": "p2", "candidate_id": "B", "clause_id": "C1",
                }],
            },
        ]
        coordinator = {
            "partition_results": [
                {"partition_id": "p1", "candidates": [{
                    "id": "A", "quote": "Revenue was $10.",
                    "public_label": "Reported revenue", "importance": "material",
                    "classification": "material_claim", "inventory_ids": ["INV1"],
                    "clauses": [{
                        "id": "C1", "quote": "Revenue was $10.",
                        "public_label": "Reported revenue",
                    }],
                }]},
                {"partition_id": "p2", "candidates": [{
                    "id": "B", "quote": "Revenue was $10.",
                    "public_label": "Second reported revenue", "importance": "material",
                    "classification": "material_claim", "inventory_ids": ["INV1"],
                    "clauses": [{
                        "id": "C1", "quote": "Revenue was $10.",
                        "public_label": "Second reported revenue",
                    }],
                }]},
            ],
            "membership": [
                {"partition_id": "p1", "candidate_id": "A", "clause_id": "C1",
                 "canonical_claim_id": "L1"},
                {"partition_id": "p2", "candidate_id": "B", "clause_id": "C1",
                 "canonical_claim_id": "L2"},
            ],
            "verifier_assignments": [
                {"verifier_id": "V1", "claim_ids": ["L1"]},
                {"verifier_id": "V2", "claim_ids": ["L2"]},
            ],
        }
        _handoff, problems = accept.validate_coordinator_handoff(
            claims, coordinator, inv)
        self.assertIn("inventory id 'INV1' is assigned more than once", problems)

    def test_supporting_provenance_stays_outside_material_ledger(self) -> None:
        inv = {
            "complete": True,
            "items": [{
                "id": "INV1", "displayed": "Source snapshot: CRM export",
                "quote": "Source snapshot: CRM export", "location": "line1",
                "importance": "material",
            }],
        }
        supporting = [{
            "id": "S1", "quote": "Source snapshot: CRM export",
            "public_label": "CRM export provenance",
            "importance": "supporting", "classification": "supporting_provenance",
            "reason": "This line identifies the source only.",
            "inventory_ids": ["INV1"], "outcome": "not_reached", "check_id": None,
        }]
        discarded = []
        kept = accept.apply_host_classifications(supporting, discarded, inv)
        self.assertEqual(discarded, [])
        self.assertEqual(kept[0]["importance"], "supporting")
        self.assertEqual(inv["items"][0]["importance"], "supporting")


class PresentationTests(unittest.TestCase):
    def test_customer_presentation_requires_an_exact_host_action(self) -> None:
        action = {
            "id": "A1",
            "kind": "review_before_share",
            "text": "Review the delivery receipt before sharing the report.",
            "report_quote": "On-time delivery was 94%.",
            "check_ids": ["C1"],
        }
        accepted, problems = accept.validate_presentation(
            {"presentation": {
                "summary": "The accepted receipt supports the report value before sharing.",
                "check_ids": ["C1"],
                "actions": [action], "limits": [],
            }},
            REPORT, {"C1"}, accepted_checks=[evidence_check()],
        )
        self.assertEqual(problems, [])
        self.assertEqual(accepted["actions"], [action])

        for document in (
            {},
            {"presentation": {"summary": "", "actions": [], "limits": []}},
            {"presentation": {
                "summary": "", "actions": [action | {"id": "next"}], "limits": [],
            }},
        ):
            with self.subTest(document=document):
                accepted, problems = accept.validate_presentation(
                    document, REPORT, {"C1"})
                self.assertIsNone(accepted)
                self.assertTrue(problems)

    def test_repeated_correction_statement_must_be_in_receipt_and_next_action(self) -> None:
        statement = (
            "Both the Revenue KPI tile and the segment table Total row repeat "
            "$359,490.34, and both must change to $350,490.34."
        )
        check = {
            "id": "C-TOTAL",
            "verdict": "contradicted",
            "correction_notice": {
                "statement": statement,
                "report_value": "$359,490.34",
                "replacement_value": "$350,490.34",
                "locations": ["Revenue KPI tile", "segment table Total row"],
            },
        }
        action = {
            "id": "A1",
            "kind": "correct_report",
            "text": statement + " Recheck the report before sharing it.",
            "report_quote": "On-time delivery was 94%.",
            "check_ids": ["C-TOTAL"],
        }
        accepted, problems = accept.validate_presentation(
            {"presentation": {
                "summary": "The accepted contradiction requires a report correction before sharing.",
                "check_ids": ["C-TOTAL"],
                "actions": [action], "limits": [],
            }},
            REPORT, {"C-TOTAL"}, accepted_checks=[check],
        )
        self.assertEqual(problems, [])
        self.assertEqual(accepted["actions"], [action])
        action["text"] = "Correct the displayed total before sharing the report."
        _accepted, problems = accept.validate_presentation(
            {"presentation": {
                "summary": "The accepted contradiction requires a report correction before sharing.",
                "check_ids": ["C-TOTAL"],
                "actions": [action], "limits": [],
            }},
            REPORT, {"C-TOTAL"}, accepted_checks=[check],
        )
        self.assertEqual(problems, [
            "presentation.actions does not include the exact correction statement "
            "for check 'C-TOTAL'",
        ])

    def test_visible_confirmations_are_selected_by_host_ids_not_severity(self) -> None:
        high = evidence_check()
        high["id"] = "C-HIGH"
        high["claim_id"] = "L-HIGH"
        high["severity"] = "high"
        low = evidence_check()
        low["id"] = "C-LOW"
        low["claim_id"] = "L-LOW"
        low["severity"] = "low"
        action = {
            "id": "A1", "kind": "review_before_share",
            "text": "Review the accepted receipts before sharing the report.",
            "report_quote": "On-time delivery was 94%.",
            "check_ids": ["C-HIGH"],
        }
        accepted, problems = accept.validate_presentation(
            {"presentation": {
                "summary": "The selected confirmation supplies decision-relevant checking context.",
                "check_ids": ["C-LOW"],
                "actions": [action], "limits": [],
            }},
            REPORT, {"C-HIGH", "C-LOW"}, accepted_checks=[high, low],
        )
        self.assertEqual(problems, [])
        self.assertEqual(accepted["check_ids"], ["C-LOW"])

        error = evidence_check(verdict="contradicted")
        error["id"] = "C-ERR"
        error["claim_id"] = "L-ERR"
        _accepted, problems = accept.validate_presentation(
            {"presentation": {
                "summary": "The accepted results require review before this report is shared.",
                "check_ids": ["C-ERR"],
                "actions": [action], "limits": [],
            }},
            REPORT, {"C-HIGH", "C-LOW", "C-ERR"},
            accepted_checks=[high, low, error],
        )
        self.assertIn(
            "presentation must select at least one visible confirmed check",
            problems,
        )

    def test_unreconciled_conflict_requires_exact_reconciliation_action(self) -> None:
        check = not_checkable_check()
        check["basis"] = "evidence"
        check["public_receipt"]["source_id"] = "status-snapshot"
        check["population_alignment"] = unreconciled_alignment()
        action = {
            "id": "A1", "kind": "correct_report",
            "text": "Replace the report value with the supplied value.",
            "report_quote": "On-time delivery was 94%.",
            "check_ids": ["C1"],
        }
        _accepted, problems = accept.validate_presentation(
            {"presentation": {
                "summary": "The source conflict must be reconciled before either value changes.",
                "check_ids": ["C1"],
                "actions": [action], "limits": [],
            }},
            REPORT, {"C1"}, accepted_checks=[check],
        )
        self.assertIn(
            "presentation.actions[0] cannot use correct_report for an unreconciled population",
            problems,
        )
        self.assertIn(
            "presentation.actions has no reconcile_before_change action for check 'C1'",
            problems,
        )

        action.update({
            "kind": "reconcile_before_change",
            "text": unreconciled_alignment()["reconciliation_action"],
        })
        accepted, problems = accept.validate_presentation(
            {"presentation": {
                "summary": "The source conflict must be reconciled before either value changes.",
                "check_ids": ["C1"],
                "actions": [action], "limits": [],
            }},
            REPORT, {"C1"}, accepted_checks=[check],
        )
        self.assertEqual(problems, [])
        self.assertEqual(accepted["actions"][0]["kind"], "reconcile_before_change")

    def test_concise_verdict_summary_is_required_and_grounded_to_accepted_ids(self) -> None:
        action = {
            "id": "A1", "kind": "review_before_share",
            "text": "Review the accepted receipt before sharing the report.",
            "report_quote": "On-time delivery was 94%.", "check_ids": ["C1"],
        }
        for summary, ids, expected in (
            ("", ["C1"], "presentation.summary is missing or not substantive"),
            ("This summary has enough words but cites no accepted check.", [],
             "presentation.summary has no check ids"),
            ("This summary cites an outcome that was not accepted.", ["UNKNOWN"],
             "presentation.summary references unknown check id 'UNKNOWN'"),
        ):
            with self.subTest(summary=summary):
                _accepted, problems = accept.validate_presentation(
                    {"presentation": {
                        "summary": summary, "check_ids": ids,
                        "actions": [action], "limits": [],
                    }},
                    REPORT, {"C1"}, accepted_checks=[evidence_check()],
                )
                self.assertIn(expected, problems)


class CliTests(unittest.TestCase):
    def test_preflight_returns_notice_and_source_link_reasons_in_first_pass(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            paths = write_invalid_preflight_bundle(folder)
            out = folder / "preflight.json"
            self.assertEqual(run_cli_bundle(paths, out, preflight=True), 2)
            reasons = json.loads(out.read_text())["repair_reasons"]
            self.assertEqual(reasons, [
                "evidence-verifier check 'C1' correction_notice.statement does not "
                "contain locations[0]",
                "evidence-verifier check 'C1' correction_notice.statement does not "
                "contain locations[1]",
                "evidence-verifier check 'C1' public_receipt.source_id is required "
                "for evidence basis",
                "evidence-verifier check 'C1' "
                "public_receipt.decisive_operands[0].value is not grounded",
                "evidence-verifier check 'C1' "
                "public_receipt.decisive_operands[1].value is not grounded",
                "presentation.summary references unknown check id 'C1'",
                "presentation.actions[0] references unknown check id 'C1'",
                "presentation.actions has no accepted action",
                "inventory occurrence 'INV-KPI' assigned to 'L1': material inventory "
                "item has no completed outcome",
                "inventory occurrence 'INV-TOTAL' assigned to 'L1': material inventory "
                "item has no completed outcome",
            ])

    def test_preflight_and_acceptance_reject_same_unchanged_invalid_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            paths = write_invalid_preflight_bundle(folder)
            preflight_out = folder / "preflight.json"
            acceptance_out = folder / "receipts.json"
            self.assertEqual(
                run_cli_bundle(paths, preflight_out, preflight=True), 2)
            self.assertEqual(
                run_cli_bundle(paths, acceptance_out, preflight=False), 2)
            preflight = json.loads(preflight_out.read_text())
            acceptance = json.loads(acceptance_out.read_text())
            self.assertEqual(preflight["repair_reasons"], acceptance["repair_reasons"])

    def test_cli_preflight_returns_exact_repair_reasons_before_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            report = folder / "report.md"
            report.write_text("On-time delivery was 94%.\n")
            claims = folder / "claims.json"
            claims.write_text(json.dumps({"claims": [claim()]}))
            checks = folder / "checks.json"
            bad = not_checkable_check()
            bad["public_receipt"]["calculation"] = {
                "expression": "1 + 1", "result": "two projects",
            }
            checks.write_text(json.dumps({"sources": [], "checks": [bad]}))
            out = folder / "preflight.json"
            argv = sys.argv
            sys.argv = [
                "accept.py", "--preflight-only", "--report", str(report),
                "--claims", str(claims), "--checks", str(checks),
                "--out", str(out),
            ]
            try:
                code = accept.main()
            finally:
                sys.argv = argv
            self.assertEqual(code, 2)
            doc = json.loads(out.read_text())
            self.assertEqual(doc["status"], "failed")
            self.assertEqual(doc["repair_reasons"], [
                "coordinator handoff is missing or not an object",
                "evidence-verifier check 'C1' "
                "public_receipt.calculation.result is not a public numeric value",
                "evidence-verifier check 'C1' public_receipt.calculation is not "
                "allowed for not_checkable",
                "presentation is missing",
                "inventory occurrence 'INV1' assigned to 'L1': material inventory "
                "item has no completed outcome",
            ])

    def test_cli_retains_public_label_and_exact_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            report = folder / "report.md"
            report.write_text("On-time delivery was 94%.\n")
            evidence = folder / "status.json"
            evidence.write_text('{"on_time": 94, "total": 100}\n')
            claims = folder / "claims.json"
            canonical = claim() | {
                "member_refs": [{
                    "partition_id": "summary", "candidate_id": "K1",
                    "clause_id": "C1",
                }],
            }
            claims.write_text(json.dumps({
                "claims": [canonical],
                "coordinator": {
                    "partition_results": [{
                        "partition_id": "summary",
                        "candidates": [{
                            "id": "K1",
                            "quote": "On-time delivery was 94%.",
                            "public_label": CLAIM_LABEL,
                            "importance": "material",
                            "classification": "material_claim",
                            "inventory_ids": ["INV1"],
                            "clauses": [{
                                "id": "C1",
                                "quote": "On-time delivery was 94%.",
                                "public_label": CLAIM_LABEL,
                            }],
                        }],
                    }],
                    "membership": [{
                        "partition_id": "summary",
                        "candidate_id": "K1",
                        "clause_id": "C1",
                        "canonical_claim_id": "L1",
                    }],
                    "verifier_assignments": [{
                        "verifier_id": "V1",
                        "claim_ids": ["L1"],
                    }],
                },
            }))
            checks = folder / "checks.json"
            checks.write_text(json.dumps({
                "sources": [source_for(evidence)], "checks": [evidence_check()],
                "presentation": {
                    "summary": (
                        "The accepted receipt supports the displayed delivery rate."
                    ),
                    "check_ids": ["C1"],
                    "actions": [{
                        "id": "A1",
                        "kind": "review_before_share",
                        "text": (
                            "Review the accepted delivery receipt before sharing "
                            "the report."
                        ),
                        "report_quote": "On-time delivery was 94%.",
                        "check_ids": ["C1"],
                    }],
                    "limits": [],
                },
            }))
            out = folder / "receipts.json"
            argv = sys.argv
            sys.argv = [
                "accept.py", "--report", str(report), "--claims", str(claims),
                "--checks", str(checks), "--evidence-dir", str(folder),
                "--out", str(out),
            ]
            try:
                code = accept.main()
            finally:
                sys.argv = argv
            self.assertEqual(code, 0)
            doc = json.loads(out.read_text())
            self.assertEqual(doc["discarded_claims"], [])
            self.assertEqual(doc["semantic_status"], "complete")
            self.assertEqual(doc["claims"][0]["public_label"], CLAIM_LABEL)
            self.assertEqual(doc["checks"][0]["public_receipt"], evidence_check()["public_receipt"])

    def test_cli_records_missing_coordinator_as_a_fail_closed_repair_reason(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            report = folder / "report.md"
            report.write_text("On-time delivery was 94%.\n")
            claims = folder / "claims.json"
            claims.write_text(json.dumps({"claims": [claim()]}))
            checks = folder / "checks.json"
            checks.write_text(json.dumps({
                "sources": [], "checks": [not_checkable_check()],
            }))
            out = folder / "receipts.json"
            argv = sys.argv
            sys.argv = [
                "accept.py", "--report", str(report), "--claims", str(claims),
                "--checks", str(checks), "--out", str(out),
            ]
            try:
                code = accept.main()
            finally:
                sys.argv = argv
            self.assertEqual(code, 2)
            doc = json.loads(out.read_text())
            self.assertEqual(doc["semantic_status"], "failed")
            self.assertIn(
                "coordinator handoff is missing or not an object",
                doc["repair_reasons"],
            )
            self.assertEqual(
                doc["discarded_claims"][-1]["problems"],
                ["coordinator handoff is missing or not an object"],
            )


if __name__ == "__main__":
    unittest.main()
