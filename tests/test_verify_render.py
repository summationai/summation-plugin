"""Focused renderer tests for exact public-receipt serialization."""
from __future__ import annotations

import copy
import importlib.util
import json
import pathlib
import re
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "verify" / "scripts"


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


render = load("render")
audit = load("artifact_audit")


def retained_source(*, kind: str = "supplied_file") -> dict:
    row = {
        "id": "status-snapshot",
        "kind": kind,
        "label": "Project status snapshot",
        "evidence_file": "status.json",
        "result_sha256": "a" * 64,
    }
    if kind == "live_tool":
        row["retrieval"] = {
            "retrieved_at": "2026-08-25T13:10:00Z",
            "tool": "status_api.get_week",
            "arguments": {"week": "2026-W34"},
        }
    return row


def public_receipt(label: str, report_value, *, source_id: str | None = "status-snapshot",
                   decisive: list[dict] | None = None,
                   explanation: str | None = None) -> dict:
    if decisive is None:
        decisive = [{
            "label": f"Recorded {label.lower()}",
            "value": report_value,
            "location": "Project status snapshot, retained field",
        }]
    row = {
        "report_operand": {
            "label": label,
            "value": report_value,
            "location": "Report summary, displayed value",
        },
        "decisive_operands": decisive,
        "explanation": explanation or (
            "The retained source value matches the exact value displayed in the report."
        ),
    }
    if source_id:
        row["source_id"] = source_id
    return row


def accepted_check(index: int, verdict: str = "confirmed", *,
                   basis: str = "evidence") -> dict:
    label = f"Reported metric {index}"
    receipt = public_receipt(label, index, source_id=(
        "status-snapshot" if basis == "evidence" else None))
    if verdict == "not_checkable":
        basis = "report"
        receipt = public_receipt(
            label, index, source_id=None, decisive=[],
            explanation=(
                "No approved source was available to verify this displayed report metric."
            ),
        )
    if verdict == "changed_since_report":
        receipt = public_receipt(
            label, index, decisive=[
                {
                    "label": "Report date", "value": "2026-04-04",
                    "location": "Report summary, as-of date",
                },
                {
                    "label": f"Later recorded metric {index}", "value": index + 1,
                    "location": "Project status snapshot, retained field",
                },
                {
                    "label": "Later snapshot date", "value": "2026-08-23",
                    "location": "Project status snapshot, as-of field",
                },
            ],
            explanation=(
                "The later retained snapshot differs from the value recorded in the dated report."
            ),
        )
        receipt["reconstruction_attempt"] = (
            "The approved history source was checked, but no report-date record was retained."
        )
    return {
        "id": f"C{index}",
        "claim_id": f"L{index}",
        "type": "semantic",
        "basis": basis,
        "verdict": verdict,
        "importance": "material",
        "severity": "high" if verdict == "contradicted" else None,
        "public_receipt": receipt,
    }


def raw_for(checks: list[dict], *, sources: list[dict] | None = None,
            supporting: bool = False) -> dict:
    source_rows = list(sources if sources is not None else [retained_source()])
    claims = [
        {
            "id": check["claim_id"],
            "quote": f"Visible report claim {index}.",
            "public_label": check["public_receipt"]["report_operand"]["label"],
            "importance": "material",
            "classification": "material_claim",
            "outcome": check["verdict"],
            "check_id": check["id"],
            "inventory_ids": [f"INV{index}"],
        }
        for index, check in enumerate(checks, 1)
    ]
    if supporting:
        claims.append({
            "id": "S1", "quote": "Source snapshot: CRM export.",
            "public_label": "CRM export provenance", "importance": "supporting",
            "classification": "supporting_provenance",
            "reason": "This line identifies the report source only.",
            "outcome": None, "check_id": None, "inventory_ids": ["INVS"],
        })
    items = [
        {
            "id": f"INV{index}", "kind": "raw", "displayed": str(index),
            "location": f"line{index}", "importance": "material",
        }
        for index in range(1, len(checks) + 1)
    ]
    if supporting:
        items.append({
            "id": "INVS", "kind": "raw", "displayed": "Source snapshot",
            "location": "lineS", "importance": "supporting",
        })
    return {
        "source": {
            "path": "report.md", "format": "md", "sha256": "b" * 64,
            "period_label": None, "report_date": None,
        },
        "findings": [],
        "inventory": {"complete": True, "reader": "md", "items": items, "reason": None},
        "inventory_missing": [],
        "coverage": {
            "claims_in_ledger": len(checks),
            "claims_reached_by_a_check": len(checks),
            "extractor_checkable_fraction": 1.0,
            "engine_checkable_fraction": 1.0,
            "inventory_material": len(checks),
            "checks_registered": 0, "checks_with_findings": 0,
            "checks_found_nothing": 0, "checks_errored": 0,
        },
        "verification": {
            "document": {"status": "complete", "detail": None},
            "semantic": {"status": "complete", "detail": None},
            "live_source": {
                "status": (
                    "complete" if any(row.get("kind") == "live_tool" for row in source_rows)
                    else "not_run"
                ),
                "detail": None,
            },
        },
        "claims": claims,
        "sources": source_rows,
    }


def make_artifact(checks: list[dict], *, sources: list[dict] | None = None,
                  supporting: bool = False) -> dict:
    raw = raw_for(checks, sources=sources, supporting=supporting)
    return render.artifact_from_findings(
        raw, run_id="unit-render", generated_at="2026-08-25T13:10:00Z",
        layer2=checks,
    )


class PublicLayerTests(unittest.TestCase):
    def test_public_layer_is_an_exact_whitelist(self) -> None:
        check = accepted_check(1)
        expected_receipt = copy.deepcopy(check["public_receipt"])
        check.update({
            "formula": "on-time / total semantic heuristic",
            "comparison": {"label": "row 9", "value": 999},
            "evidence_json": [{"pointer": "/private", "value": 1}],
        })
        first = render._public_layer2([check], sources=[retained_source()])
        check["formula"] = "changed prose that must have no effect"
        second = render._public_layer2([check], sources=[retained_source()])
        self.assertEqual(first, second)
        self.assertEqual(first[0]["public_receipt"], expected_receipt)
        self.assertEqual(set(first[0]), set(render.CHECK_PUBLIC_KEYS))
        self.assertNotIn("formula", json.dumps(first))
        self.assertNotIn("/private", json.dumps(first))

    def test_renderer_has_no_semantic_fallback_apis(self) -> None:
        for name in (
            "evidence_heading", "_verification_public", "location_line",
            "public_explanation", "_public_claim", "_combined_verdict",
            "public_verdict", "customer_verdict", "CONFIRM_CARDS",
            "GROUNDED_OUTCOMES",
        ):
            self.assertFalse(hasattr(render, name), name)

    def test_missing_vague_or_private_receipts_fail_closed(self) -> None:
        source = [retained_source()]
        for mutation in ("missing", "vague", "private", "explanation"):
            check = accepted_check(1)
            if mutation == "missing":
                check.pop("public_receipt")
            elif mutation == "vague":
                check["public_receipt"]["report_operand"]["label"] = "row 2"
            elif mutation == "private":
                check["public_receipt"]["report_operand"]["location"] = "/metrics/value"
            else:
                check["public_receipt"]["explanation"] = "Confirmed."
            with self.subTest(mutation=mutation), self.assertRaises(SystemExit):
                render._public_layer2([check], sources=source)

    def test_not_checkable_requires_its_agent_receipt_and_no_operands(self) -> None:
        check = accepted_check(1, "not_checkable")
        public = render._public_layer2([check], sources=[retained_source()])
        self.assertEqual(public[0]["public_receipt"], check["public_receipt"])
        check["public_receipt"]["decisive_operands"] = [{
            "label": "Unverified value", "value": 1, "location": "Unknown source",
        }]
        with self.assertRaises(SystemExit):
            render._public_layer2([check], sources=[retained_source()])

    def test_evidence_not_checkable_requires_its_retained_source_link(self) -> None:
        check = accepted_check(1, "not_checkable")
        check["basis"] = "evidence"
        with self.assertRaises(SystemExit):
            render._public_layer2([check], sources=[retained_source()])
        check["public_receipt"]["source_id"] = "status-snapshot"
        public = render._public_layer2([check], sources=[retained_source()])
        self.assertEqual(public[0]["public_receipt"], check["public_receipt"])

    def test_changed_receipt_keeps_agent_reconstruction_inside_receipt(self) -> None:
        check = accepted_check(1, "changed_since_report")
        public = render._public_layer2([check], sources=[retained_source()])
        self.assertEqual(
            public[0]["public_receipt"]["reconstruction_attempt"],
            check["public_receipt"]["reconstruction_attempt"],
        )
        check["public_receipt"].pop("reconstruction_attempt")
        with self.assertRaises(SystemExit):
            render._public_layer2([check], sources=[retained_source()])


class LedgerTests(unittest.TestCase):
    def test_root_verdict_uses_one_material_ledger(self) -> None:
        cases = (
            ([accepted_check(1)], "safe_to_share"),
            ([accepted_check(1, "not_checkable")], "share_with_caveats"),
            ([accepted_check(1, "changed_since_report")], "share_with_caveats"),
            ([accepted_check(1, "contradicted")], "fix_first"),
        )
        for checks, expected in cases:
            with self.subTest(expected=expected):
                art = make_artifact(checks)
                self.assertEqual(art["verdict"], expected)

    def test_two_errors_among_nine_score_twenty_two_point_two(self) -> None:
        checks = [
            accepted_check(index, "contradicted" if index in {1, 2} else "confirmed")
            for index in range(1, 10)
        ]
        art = make_artifact(checks)
        self.assertAlmostEqual(art["score"]["value"], 200.0 / 9, places=12)
        self.assertEqual(art["evidence_coverage"]["contradicted"], 2)
        self.assertEqual(art["evidence_coverage"]["confirmed"], 7)

    def test_supporting_provenance_is_outside_material_totals(self) -> None:
        art = make_artifact([accepted_check(1)], supporting=True)
        coverage = art["evidence_coverage"]
        self.assertEqual(coverage["document_claims_total"], 1)
        self.assertEqual(coverage["supporting_claims_reviewed"], 1)
        self.assertEqual(coverage["confirmed"], 1)

    def test_arithmetic_use_marker_cannot_be_a_public_outcome(self) -> None:
        raw = raw_for([accepted_check(1)])
        raw["claims"][0]["outcome"] = "used_for_internal_arithmetic"
        self.assertEqual(render.ledger_verdict(raw), "unable_to_grade")
        with self.assertRaises(SystemExit):
            render.artifact_from_findings(
                raw, run_id="bad", generated_at="2026-08-25T13:10:00Z",
                layer2=[accepted_check(1)],
            )

    def test_machine_finding_statement_never_enters_artifact(self) -> None:
        raw = raw_for([accepted_check(1, "contradicted")])
        raw["findings"] = [{
            "check_id": "machine", "tier": "D", "statement": "machine copy",
            "inventory_ids": ["INV1"],
        }]
        art = render.artifact_from_findings(
            raw, run_id="machine", generated_at="2026-08-25T13:10:00Z",
            layer2=[accepted_check(1, "contradicted")],
        )
        self.assertEqual(art["findings"], [])
        self.assertEqual(art["diagnostics"], [])
        self.assertNotIn("machine copy", json.dumps(art))

    def test_unowned_machine_error_fails_before_serialization(self) -> None:
        raw = raw_for([accepted_check(1)])
        raw["findings"] = [{
            "check_id": "machine", "tier": "D", "statement": "internal",
            "inventory_ids": ["INV1"],
        }]
        self.assertTrue(render.document_errors_unaccounted(raw))


class HtmlTests(unittest.TestCase):
    def test_every_material_outcome_is_one_exact_card_without_truncation(self) -> None:
        checks = [
            accepted_check(1, "confirmed"),
            accepted_check(2, "confirmed"),
            accepted_check(3, "confirmed"),
            accepted_check(4, "contradicted"),
            accepted_check(5, "not_checkable"),
            accepted_check(6, "changed_since_report"),
        ]
        art = make_artifact(checks)
        page = render.html_of(art)
        tags = re.findall(r'<article class="material-card"[^>]*>', page)
        self.assertEqual(len(tags), len(checks))
        for check in checks:
            self.assertEqual(page.count(f'data-card-id="{check["id"]}"'), 1)
            tag = next(tag for tag in tags if f'data-card-id="{check["id"]}"' in tag)
            self.assertEqual(tag.count(f'data-disposition="{check["verdict"]}"'), 1)
        self.assertEqual(page.count("data-disposition="), len(checks))
        self.assertEqual(audit._card_identity_problems(art, page), [])

    def test_missing_duplicate_or_mismatched_card_identity_fails(self) -> None:
        art = make_artifact([accepted_check(1), accepted_check(2)])
        page = render.html_of(art)
        mutations = (
            page.replace(' data-card-id="C1"', "", 1),
            page.replace('data-card-id="C1"', 'data-card-id="C1" data-card-id="C1"', 1),
            page.replace('data-card-id="C2"', 'data-card-id="C1"', 1),
            page.replace(
                'data-card-id="C1" data-disposition="confirmed"',
                'data-card-id="C1" data-disposition="contradicted"',
                1,
            ),
        )
        for mutated in mutations:
            self.assertTrue(audit._card_identity_problems(art, mutated))

    def test_html_shows_exact_receipt_fields_and_no_public_fallback_sentences(self) -> None:
        check = accepted_check(1)
        check["public_receipt"]["calculation"] = {
            "expression": "94 / 100 * 100", "result": "94%",
        }
        check["public_receipt"]["decisive_operands"] = [
            {
                "label": "On-time deliveries", "value": 94,
                "location": "Project status snapshot, delivery totals",
            },
            {
                "label": "Total deliveries", "value": 100,
                "location": "Project status snapshot, delivery totals",
            },
        ]
        art = make_artifact([check])
        page = render.html_of(art)
        for text in (
            "Reported metric 1", "On-time deliveries", "Total deliveries",
            "94 / 100 * 100 = 94%", check["public_receipt"]["explanation"],
            "Project status snapshot", "supplied_file",
        ):
            self.assertIn(text, page)
        for fallback in (
            "Supplied recorded evidence", "Actual live query", "What ran",
            "No semantic review status was recorded", "Claim</",
        ):
            self.assertNotIn(fallback, page)

    def test_source_kind_is_the_exact_retained_enum_token(self) -> None:
        static = make_artifact([accepted_check(1)], sources=[retained_source()])
        static_page = render.html_of(static)
        self.assertIn("supplied_file", static_page)
        self.assertNotIn("live_tool", static_page)
        live_source = retained_source(kind="live_tool")
        live = make_artifact([accepted_check(1)], sources=[live_source])
        live_page = render.html_of(live)
        self.assertIn("live_tool", live_page)
        self.assertNotIn("Supplied recorded evidence", live_page)

    def test_static_source_cannot_be_retyped_live_without_live_metadata(self) -> None:
        source = retained_source()
        source["kind"] = "live_tool"
        with self.assertRaises(SystemExit):
            make_artifact([accepted_check(1)], sources=[source])


class SchemaAndSerializationTests(unittest.TestCase):
    def test_full_artifact_contract_and_new_version_are_emitted(self) -> None:
        art = make_artifact([accepted_check(1)])
        self.assertEqual(art["schema_version"], render.SCHEMA_VERSION)
        for field in render.REQUIRED:
            self.assertIn(field, art)
        render.validate_artifact(art)
        legacy = copy.deepcopy(art)
        legacy["schema_version"] = "grade-artifact/v1"
        with self.assertRaisesRegex(SystemExit, "bad schema_version"):
            render.validate_artifact(legacy)

    def test_verification_statuses_are_exact_and_public_detail_is_rejected(self) -> None:
        raw = raw_for([accepted_check(1)])
        expected = copy.deepcopy(raw["verification"])
        art = render.artifact_from_findings(
            raw, run_id="verification", generated_at="2026-08-25T13:10:00Z",
            layer2=[accepted_check(1)],
        )
        self.assertEqual(art["verification"], expected)
        raw["verification"] = {
            "document": {"status": "complete", "detail": "Agent supplied document status."},
            "semantic": {"status": "complete", "detail": "Agent supplied semantic status."},
            "live_source": {"status": "not_run", "detail": None},
        }
        with self.assertRaises(SystemExit):
            render.artifact_from_findings(
                raw, run_id="verification", generated_at="2026-08-25T13:10:00Z",
                layer2=[accepted_check(1)],
            )

    def test_report_source_metadata_has_no_digest_or_format_fallback(self) -> None:
        raw = raw_for([accepted_check(1)])
        for field in ("sha256", "format"):
            broken = copy.deepcopy(raw)
            broken["source"].pop(field)
            with self.subTest(field=field), self.assertRaises(SystemExit):
                render.artifact_from_findings(
                    broken, run_id="source", generated_at="2026-08-25T13:10:00Z",
                    layer2=[accepted_check(1)],
                )
        raw["source"]["path"] = "/private/tmp/report.md"
        with self.assertRaises(SystemExit):
            render.artifact_from_findings(
                raw, run_id="source", generated_at="2026-08-25T13:10:00Z",
                layer2=[accepted_check(1)],
            )

    def test_public_json_contains_no_internal_grounding_or_alias_fields(self) -> None:
        check = accepted_check(1)
        check.update({
            "report_quote": "Visible report claim.",
            "evidence_json": [{"pointer": "/metric", "value": 1}],
            "date_receipt": {"pointer": "/date", "value": "2026-08-23"},
        })
        raw = raw_for([check])
        raw["claims"][0]["arithmetic_inventory_ids"] = ["INV1"]
        art = render.artifact_from_findings(
            raw, run_id="private", generated_at="2026-08-25T13:10:00Z",
            layer2=[check],
        )
        blob = json.dumps(art)
        for forbidden in (
            "report_quote", "evidence_json", "date_receipt", "/metric",
            "arithmetic_inventory_ids", "found_by", "verification_mode",
        ):
            self.assertNotIn(forbidden, blob)


if __name__ == "__main__":
    unittest.main()
