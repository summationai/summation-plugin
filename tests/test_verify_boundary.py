"""Architecture-boundary tests for agent-authored public receipts."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import pathlib
import re
import tempfile
import unittest

try:
    import jsonschema
except ImportError:  # pragma: no cover - focused command installs it when absent
    jsonschema = None


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "verify" / "scripts"


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


accept = load("accept")
artifact_audit = load("artifact_audit")
html_arith = load("html_arith")
internal = load("internal")
render = load("render")


def source_for(path: pathlib.Path, *, kind: str = "supplied_file") -> dict:
    row = {
        "id": "project-status",
        "kind": kind,
        "label": "Project status snapshot",
        "evidence_file": path.name,
        "result_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
    if kind == "live_tool":
        row["retrieval"] = {
            "retrieved_at": "2026-08-25T13:10:00Z",
            "tool": "sum-api query",
            "arguments": {"query_name": "project status by week"},
        }
    return row


def evidence_check() -> dict:
    return {
        "id": "C1",
        "claim_id": "L1",
        "type": "semantic",
        "basis": "evidence",
        "verdict": "confirmed",
        "importance": "material",
        "report_quote": "On-time delivery was 94%.",
        "evidence_json": [
            {"pointer": "/on_time", "value": 94},
            {"pointer": "/total", "value": 100},
        ],
        "public_receipt": {
            "report_operand": {
                "label": "Reported on-time delivery rate",
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
                "The recorded delivery totals calculate to the same 94% rate "
                "shown in the report."
            ),
            "source_id": "project-status",
        },
    }


def public_artifact(checks: list[dict]) -> dict:
    source = {
        "id": "project-status",
        "kind": "supplied_file",
        "label": "Project status snapshot",
        "evidence_file": "project-status.json",
        "result_sha256": "a" * 64,
    }
    public_checks = render._public_layer2(checks, sources=[source])
    claims = [{
        "id": str(check["claim_id"]),
        "quote": str(check["public_receipt"]["report_operand"]["value"]),
        "importance": "material",
        "classification": "material_claim",
        "outcome": str(check["verdict"]),
        "check_id": str(check["id"]),
        "verification_mode": "external_evidence",
    } for check in checks]
    n = len(checks)
    return {
        "schema_version": "grade-artifact/public-receipt-v1",
        "run_id": "boundary-cards",
        "generated_at": "2026-08-25T13:10:00Z",
        "source": {"path": "report.md", "format": "md"},
        "source_result": None,
        "sources": [source],
        "verdict": "safe_to_share",
        "score": {"kind": "tier_d_per_100_claims", "value": 0},
        "findings": [],
        "evidence_checks": public_checks,
        "evidence_findings": [],
        "evidence_coverage": {
            "document_claims_total": n,
            "document_claims_reached": n,
            "claim_outcomes_proposed": n,
            "material_claims_reviewed": n,
            "supporting_claims_reviewed": 0,
            "confirmed": n,
            "contradicted": 0,
            "not_checkable": 0,
            "evidence_confirmed": n,
            "evidence_contradicted": 0,
            "evidence_not_checkable": 0,
            "report_confirmed": 0,
            "report_contradicted": 0,
            "report_not_checkable": 0,
            "validated_outcomes": n,
            "receipt_failures": 0,
            "evidence_files_supplied": 1,
            "evidence_files_cited": ["Project status snapshot"],
            "provenance_groups": [{
                "source_id": "project-status",
                "kind": "supplied_file",
                "label": "Project status snapshot",
            }],
            "source_independence": "grouped_by_declared_provenance",
        },
        "decision": None,
        "actions": [],
        "decision_limits": [],
        "diagnostics": [],
        "checks": {
            "registered": 0, "with_findings": 0, "found_nothing": 0,
            "errored": 0, "skipped_note": "",
        },
        "verification": {
            "document": {"status": "complete", "detail": None},
            "semantic": {"status": "complete", "detail": None},
            "live_source": {"status": "not_run", "detail": None},
        },
        "limitations": [],
        "offer": {"text": "", "accepted": None},
        "claims": claims,
    }


class SourceContractTests(unittest.TestCase):
    def test_checks_file_requires_top_level_sources_and_checks_arrays(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = pathlib.Path(raw) / "checks.json"
            path.write_text('{"checks": []}\n')
            with self.assertRaisesRegex(ValueError, "no sources array"):
                accept.load_checks(path)
            path.write_text('{"sources": [], "checks": []}\n')
            checks, document = accept.load_checks(path)
            self.assertEqual(checks, [])
            self.assertEqual(document["sources"], [])

    def test_source_digest_and_kind_are_validated(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            report = folder / "report.md"
            report.write_text("On-time delivery was 94%.")
            evidence = folder / "project-status.json"
            evidence.write_text('{"on_time": 94, "total": 100}\n')

            accepted, discarded = accept.validate_sources(
                folder, [source_for(evidence)], report)
            self.assertEqual([row["id"] for row in accepted], ["project-status"])
            self.assertEqual(discarded, [])

            bad = source_for(evidence)
            bad["result_sha256"] = "0" * 64
            accepted, discarded = accept.validate_sources(folder, [bad], report)
            self.assertEqual(accepted, [])
            self.assertIn(
                "source result_sha256 does not match evidence file",
                discarded[0]["problems"],
            )

    def test_supplied_file_cannot_claim_live_retrieval(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            report = folder / "report.md"
            report.write_text("On-time delivery was 94%.")
            evidence = folder / "project-status.json"
            evidence.write_text('{"on_time": 94, "total": 100}\n')
            row = source_for(evidence)
            row["retrieval"] = {
                "retrieved_at": "2026-08-25T13:10:00Z",
                "tool": "invented live call",
                "arguments": {},
            }
            accepted, discarded = accept.validate_sources(folder, [row], report)
            self.assertEqual(accepted, [])
            self.assertIn(
                "supplied_file source must not declare live retrieval metadata",
                discarded[0]["problems"],
            )

    def test_live_tool_requires_complete_safe_retrieval_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            report = folder / "report.md"
            report.write_text("On-time delivery was 94%.")
            evidence = folder / "project-status.json"
            evidence.write_text('{"on_time": 94, "total": 100}\n')
            row = source_for(evidence, kind="live_tool")
            row["retrieval"].pop("tool")
            accepted, discarded = accept.validate_sources(folder, [row], report)
            self.assertEqual(accepted, [])
            self.assertIn("live_tool source retrieval.tool is missing", discarded[0]["problems"])


@unittest.skipUnless(jsonschema is not None, "jsonschema is not installed")
class SchemaContractTests(unittest.TestCase):
    def test_public_receipt_artifact_matches_the_declared_schema(self) -> None:
        schema = json.loads((ROOT / "skills" / "verify" / "schema.v1.json").read_text())
        expected = "grade-artifact/public-receipt-v1"
        self.assertEqual(schema["$id"], expected)
        self.assertEqual(schema["properties"]["schema_version"]["const"], expected)
        self.assertTrue({
            "score", "claims", "evidence_coverage", "limitations", "offer"
        } <= set(schema["required"]))
        jsonschema.Draft202012Validator.check_schema(schema)
        jsonschema.Draft202012Validator(schema).validate(
            public_artifact([evidence_check()])
        )

    def test_renderer_emits_new_contract_and_rejects_legacy_version(self) -> None:
        check = {
            "id": "C-REPORT",
            "claim_id": "L-REPORT",
            "type": "arithmetic",
            "basis": "report",
            "verdict": "confirmed",
            "importance": "material",
            "severity": None,
            "public_receipt": {
                "report_operand": {
                    "label": "Reported active projects",
                    "value": 12,
                    "location": "Project summary, active projects",
                },
                "decisive_operands": [{
                    "label": "Projects in the first group",
                    "value": 10,
                    "location": "Project summary, first group",
                }, {
                    "label": "Projects in the second group",
                    "value": 2,
                    "location": "Project summary, second group",
                }],
                "calculation": {"expression": "10 + 2", "result": 12},
                "explanation": (
                    "The two displayed project groups add to the reported twelve projects."
                ),
            },
        }
        raw = {
            "findings": [],
            "source": {
                "path": "report.md",
                "format": "md",
                "sha256": "a" * 64,
            },
            "coverage": {
                "claims_in_ledger": 1,
                "claims_reached_by_a_check": 1,
                "checks_registered": 0,
                "checks_with_findings": 0,
                "checks_found_nothing": 0,
                "checks_errored": 0,
            },
            "claims": [{
                "id": "L-REPORT",
                "quote": "Active projects: 12",
                "importance": "material",
                "classification": "material_claim",
                "outcome": "confirmed",
                "check_id": "C-REPORT",
            }],
            "verification": {
                "document": {"status": "complete", "detail": None},
                "semantic": {"status": "complete", "detail": None},
                "live_source": {"status": "not_run", "detail": None},
            },
        }
        artifact = render.artifact_from_findings(
            raw,
            run_id="schema-emission",
            generated_at="2026-08-25T13:10:00Z",
            layer2=[check],
        )
        expected = "grade-artifact/public-receipt-v1"
        self.assertEqual(render.SCHEMA_VERSION, expected)
        self.assertEqual(artifact["schema_version"], expected)
        for field in (
            "score", "claims", "evidence_coverage", "limitations", "offer"
        ):
            self.assertIn(field, artifact)

        legacy = json.loads(json.dumps(artifact))
        legacy["schema_version"] = "grade-artifact/v1"
        with self.assertRaisesRegex(SystemExit, "bad schema_version"):
            render.validate_artifact(legacy)


class ReceiptContractTests(unittest.TestCase):
    def validate(self, folder: pathlib.Path, check: dict, source: dict):
        accepted_sources, discarded_sources = accept.validate_sources(
            folder, [source], folder / "report.md")
        self.assertEqual(discarded_sources, [])
        return accept.validate_receipts(
            "On-time delivery was 94%.", folder, [check], {"L1"},
            folder / "report.md", sources=accepted_sources,
        )

    def test_explicit_public_receipt_is_grounded(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            (folder / "report.md").write_text("On-time delivery was 94%.")
            evidence = folder / "project-status.json"
            evidence.write_text('{"on_time": 94, "total": 100}\n')
            validated, discarded = self.validate(
                folder, evidence_check(), source_for(evidence))
            self.assertEqual(discarded, [])
            self.assertEqual(validated[0]["public_receipt"], evidence_check()["public_receipt"])
            self.assertEqual(validated[0]["evidence_mode"], "supplied_file")

    def test_missing_private_and_vague_labels_fail_closed(self) -> None:
        bad_labels = ("", "row 2", "operand 4", "item 1", "value 9", "/Users/eric/private")
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            (folder / "report.md").write_text("On-time delivery was 94%.")
            evidence = folder / "project-status.json"
            evidence.write_text('{"on_time": 94, "total": 100}\n')
            source = source_for(evidence)
            for target in ("report_operand", "decisive_operand"):
                for label in bad_labels:
                    with self.subTest(target=target, label=label):
                        check = evidence_check()
                        if target == "report_operand":
                            check["public_receipt"]["report_operand"]["label"] = label
                            expected = "public_receipt.report_operand.label"
                        else:
                            check["public_receipt"]["decisive_operands"][0]["label"] = label
                            expected = "public_receipt.decisive_operands[0].label"
                        validated, discarded = self.validate(folder, check, source)
                        self.assertEqual(validated, [])
                        self.assertTrue(any(
                            expected in problem
                            for problem in discarded[0]["problems"]
                        ))

    def test_private_location_and_missing_substantive_explanation_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            (folder / "report.md").write_text("On-time delivery was 94%.")
            evidence = folder / "project-status.json"
            evidence.write_text('{"on_time": 94, "total": 100}\n')
            source = source_for(evidence)

            check = evidence_check()
            check["public_receipt"]["report_operand"]["location"] = "/metrics/on_time"
            validated, discarded = self.validate(folder, check, source)
            self.assertEqual(validated, [])
            self.assertIn(
                "public_receipt.report_operand.location is private or internal",
                discarded[0]["problems"],
            )

            check = evidence_check()
            check["public_receipt"]["explanation"] = "Confirmed."
            validated, discarded = self.validate(folder, check, source)
            self.assertEqual(validated, [])
            self.assertIn(
                "public_receipt.explanation is missing or not substantive",
                discarded[0]["problems"],
            )

    def test_missing_or_unknown_source_link_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            (folder / "report.md").write_text("On-time delivery was 94%.")
            evidence = folder / "project-status.json"
            evidence.write_text('{"on_time": 94, "total": 100}\n')
            source = source_for(evidence)
            for source_id in (None, "missing-source"):
                with self.subTest(source_id=source_id):
                    check = evidence_check()
                    if source_id is None:
                        check["public_receipt"].pop("source_id")
                    else:
                        check["public_receipt"]["source_id"] = source_id
                    validated, discarded = self.validate(folder, check, source)
                    self.assertEqual(validated, [])
                    self.assertTrue(any("source_id" in row for row in discarded[0]["problems"]))

    def test_calculation_is_recomputed_and_uses_declared_operands(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            (folder / "report.md").write_text("On-time delivery was 94%.")
            evidence = folder / "project-status.json"
            evidence.write_text('{"on_time": 94, "total": 100}\n')
            source = source_for(evidence)

            wrong_result = evidence_check()
            wrong_result["public_receipt"]["calculation"]["result"] = "95%"
            validated, discarded = self.validate(folder, wrong_result, source)
            self.assertEqual(validated, [])
            self.assertIn(
                "public_receipt.calculation result does not equal the computed expression",
                discarded[0]["problems"],
            )

            undeclared_value = evidence_check()
            undeclared_value["public_receipt"]["calculation"]["expression"] = (
                "94 / 99 * 100"
            )
            validated, discarded = self.validate(folder, undeclared_value, source)
            self.assertEqual(validated, [])
            self.assertIn(
                "public_receipt.calculation expression uses a value absent from decisive_operands",
                discarded[0]["problems"],
            )

    def test_temporal_receipt_requires_exact_later_value_and_date(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            report = folder / "report.md"
            report.write_text("Inventory was 10,481 units.")
            evidence = folder / "inventory-snapshot.json"
            evidence.write_text(
                '{"units": 10613, "as_of": "2026-08-23"}\n')
            source = source_for(evidence)
            source["id"] = "inventory-snapshot"
            source["label"] = "Inventory units snapshot"
            check = {
                "id": "C-TIME", "claim_id": "L-TIME", "type": "temporal",
                "basis": "evidence", "verdict": "changed_since_report",
                "importance": "material",
                "report_quote": "Inventory was 10,481 units.",
                "report_value": 10481, "report_date": "2026-04-04",
                "current_value": 10613, "current_as_of": "2026-08-23",
                "reconstruction_attempt": (
                    "The approved history source was checked, but it did not retain the report-date row."
                ),
                "evidence_json": [{"pointer": "/units", "value": 10613}],
                "public_receipt": {
                    "report_operand": {
                        "label": "Reported inventory units", "value": 10481,
                        "location": "Inventory summary, units line",
                    },
                    "decisive_operands": [{
                        "label": "Later recorded inventory units", "value": 10613,
                        "location": "Inventory units snapshot, current row",
                    }],
                    "explanation": (
                        "The later snapshot records 10,613 units after the report recorded 10,481 units."
                    ),
                    "source_id": "inventory-snapshot",
                },
            }
            accepted_sources, source_discards = accept.validate_sources(
                folder, [source], report)
            self.assertEqual(source_discards, [])
            validated, discarded = accept.validate_receipts(
                report.read_text(), folder, [check], {"L-TIME"}, report,
                sources=accepted_sources,
            )
            self.assertEqual(discarded, [])
            self.assertEqual(validated[0]["current_as_of"], "2026-08-23")

            wrong_date = json.loads(json.dumps(check))
            wrong_date["current_as_of"] = "2026-08-22"
            validated, discarded = accept.validate_receipts(
                report.read_text(), folder, [wrong_date], {"L-TIME"}, report,
                sources=accepted_sources,
            )
            self.assertEqual(validated, [])
            self.assertIn(
                "current_as_of does not match evidence date",
                discarded[0]["problems"],
            )


class MechanicalBoundaryTests(unittest.TestCase):
    def test_discarded_source_metadata_blocks_a_complete_review(self) -> None:
        receipts = {
            "semantic_status": "complete",
            "inventory": {"complete": True},
            "claims": [{
                "id": "L1",
                "importance": "material",
                "classification": "material_claim",
                "outcome": "confirmed",
                "check_id": "C1",
            }],
            "checks": [evidence_check()],
            "discarded_sources": [{
                "id": "project-status",
                "problems": ["source result_sha256 does not match evidence file"],
            }],
        }
        self.assertEqual(
            render.ungraded_reason({}, True, receipts),
            "receipt failures remain",
        )

    def test_arithmetic_use_marks_claim_without_creating_confirmation(self) -> None:
        ledger = [{
            "id": "L1", "quote": "40", "importance": "material",
            "classification": "material_claim", "inventory_ids": ["html-t1-r2-c2"],
            "outcome": "not_reached", "check_id": None,
        }]
        uses = [{
            "matched": True,
            "inventory_ids": ["html-t1-r2-c2", "html-t1-r4-c2"],
            "addends": [{"inventory_id": "html-t1-r2-c2", "displayed": "40"}],
        }]
        checks, updated = accept.attach_arithmetic_uses(ledger, [], uses)
        self.assertEqual(checks, [])
        self.assertEqual(updated[0]["outcome"], "used_for_internal_arithmetic")
        self.assertIsNone(updated[0]["check_id"])

    def test_internal_candidates_contain_facts_not_public_semantics(self) -> None:
        inventory = {"items": [
            {"id": "i1", "displayed": "Ranked from highest to lowest", "location": "page 1"},
            {"id": "i2", "displayed": "Alpha", "location": "page 1"},
            {"id": "i3", "displayed": "100", "location": "page 1"},
            {"id": "i4", "displayed": "Beta", "location": "page 1"},
            {"id": "i5", "displayed": "120", "location": "page 1"},
        ]}
        candidates = internal.check_inventory(inventory)
        self.assertTrue(candidates)
        blob = json.dumps(candidates)
        for forbidden in ("verdict", "explanation", "report_quote", "comparison"):
            self.assertNotIn(f'"{forbidden}"', blob)
        rank = candidates[0]
        self.assertTrue(rank["facts"]["mismatch"])
        self.assertEqual(
            [row["displayed"] for row in rank["facts"]["values"]],
            ["100", "120"],
        )

    def test_blank_html_labels_remain_missing_with_exact_coordinates(self) -> None:
        tables = [[
            ["", "Amount"],
            ["", "40"],
            ["Beta", "60"],
            ["Total", "100"],
        ]]
        _findings, _checked, uses = html_arith.footing_findings(tables)
        first = uses[0]["addends"][0]
        self.assertIsNone(first["label"])
        self.assertEqual(first["coordinate"], "table1/r2/c2")
        self.assertNotIn("row ", json.dumps(uses).lower())

    def test_int9_and_clean_xlsx_percentage_points_stay_explicit(self) -> None:
        report = (
            "Prior gross margin: 40.0%. Current gross margin: 43.0%. "
            "Note: gross margin improved 3% week over week. "
            "Clean note: gross margin improved 3 percentage points week over week."
        )

        def check(check_id: str, verdict: str, quote: str, reported_value: str) -> dict:
            return {
                "id": check_id,
                "claim_id": f"L-{check_id}",
                "type": "units",
                "basis": "report",
                "verdict": verdict,
                "importance": "material",
                "report_quote": quote,
                "public_receipt": {
                    "report_operand": {
                        "label": "Reported gross margin improvement",
                        "value": reported_value,
                        "location": "Gross margin note",
                    },
                    "decisive_operands": [{
                        "label": "Prior gross margin",
                        "value": "40.0%",
                        "location": "Gross margin row, prior period",
                    }, {
                        "label": "Current gross margin",
                        "value": "43.0%",
                        "location": "Gross margin row, current period",
                    }],
                    "calculation": {
                        "expression": "43.0 - 40.0",
                        "result": "3 percentage points",
                    },
                    "explanation": (
                        "The two displayed margins differ by three percentage points."
                    ),
                },
            }

        planted = check(
            "INT9", "contradicted",
            "Note: gross margin improved 3% week over week.", "3%",
        )
        clean = check(
            "C-CLEAN", "confirmed",
            "Clean note: gross margin improved 3 percentage points week over week.",
            "3 percentage points",
        )
        validated, discarded = accept.validate_receipts(
            report, pathlib.Path("."), [planted, clean],
            {"L-INT9", "L-C-CLEAN"}, sources=[],
        )
        self.assertEqual(discarded, [])
        self.assertEqual([row["id"] for row in validated], ["INT9", "C-CLEAN"])
        for row in validated:
            self.assertEqual(
                row["public_receipt"]["calculation"]["result"],
                "3 percentage points",
            )


class RendererBoundaryTests(unittest.TestCase):
    def test_renderer_serializes_only_agent_public_receipt_fields(self) -> None:
        source = {
            "id": "project-status",
            "kind": "supplied_file",
            "label": "Project status snapshot",
            "evidence_file": "project-status.json",
            "result_sha256": "a" * 64,
        }
        check = evidence_check()
        check["evidence_mode"] = "supplied_file"
        check["comparison"] = {
            "formula": "invented on-time/total heuristic",
            "operands": [{"label": "row 9", "value": 999}],
        }
        first = render._public_layer2([check], sources=[source])
        check["comparison"]["formula"] = "completely different prose"
        second = render._public_layer2([check], sources=[source])
        self.assertEqual(first, second)
        self.assertEqual(first[0]["public_receipt"], evidence_check()["public_receipt"])
        self.assertNotIn("comparison", first[0])
        self.assertNotIn("current_source_kind", first[0])

    def test_no_generic_operand_fallback_can_render(self) -> None:
        check = evidence_check()
        check["public_receipt"]["decisive_operands"][0]["label"] = "row 3"
        with self.assertRaisesRegex(SystemExit, "public_receipt is not publishable"):
            render._public_layer2([check], sources=[{
                "id": "project-status",
                "kind": "supplied_file",
                "label": "Project status snapshot",
                "evidence_file": "project-status.json",
                "result_sha256": "a" * 64,
            }])

    def test_material_card_copies_exact_check_id_and_verdict_once(self) -> None:
        check = evidence_check()
        art = public_artifact([check])
        page = render.html_of(art)
        opening = re.search(r'<div class="card ok"[^>]*>', page)
        self.assertIsNotNone(opening)
        tag = opening.group(0)
        self.assertEqual(tag.count('data-card-id="C1"'), 1)
        self.assertEqual(tag.count('data-disposition="confirmed"'), 1)
        self.assertNotIn("claim-L1", tag)
        self.assertIn("On-time deliveries", page)
        self.assertIn("Total deliveries", page)
        self.assertIn("94 / 100 * 100 = 94%", page)
        self.assertEqual(artifact_audit._card_identity_problems(art, page), [])

    def test_material_card_missing_duplicate_and_mismatch_fail(self) -> None:
        first = evidence_check()
        second = evidence_check()
        second["id"] = "C2"
        second["claim_id"] = "L2"
        art = public_artifact([first, second])
        page = render.html_of(art)

        missing = page.replace(' data-card-id="C1"', "", 1)
        self.assertTrue(artifact_audit._card_identity_problems(art, missing))

        duplicate_attribute = page.replace(
            'data-card-id="C1"',
            'data-card-id="C1" data-card-id="C1"',
            1,
        )
        self.assertTrue(
            artifact_audit._card_identity_problems(art, duplicate_attribute))

        duplicate_id = page.replace('data-card-id="C2"', 'data-card-id="C1"', 1)
        self.assertTrue(artifact_audit._card_identity_problems(art, duplicate_id))

        mismatch = page.replace(
            'data-disposition="confirmed"',
            'data-disposition="contradicted"',
            1,
        )
        self.assertTrue(artifact_audit._card_identity_problems(art, mismatch))

    def test_each_rendered_material_disposition_copies_its_exact_check_id(self) -> None:
        confirmed = evidence_check()
        contradicted = json.loads(json.dumps(confirmed))
        contradicted.update({
            "id": "C-ERROR",
            "claim_id": "L-ERROR",
            "verdict": "contradicted",
        })
        changed = json.loads(json.dumps(confirmed))
        changed.update({
            "id": "C-CHANGED",
            "claim_id": "L-CHANGED",
            "type": "temporal",
            "verdict": "changed_since_report",
            "report_value": "94%",
            "report_date": "2026-04-04",
            "current_value": "95%",
            "current_as_of": "2026-08-23",
            "reconstruction_attempt": (
                "The approved history source does not retain the report-date row."
            ),
        })
        changed["public_receipt"]["decisive_operands"][0]["value"] = "95%"
        changed["public_receipt"].pop("calculation")
        changed["public_receipt"]["explanation"] = (
            "The later recorded rate is 95%, compared with the report's 94% rate."
        )

        art = public_artifact([confirmed, contradicted, changed])
        page = render.html_of(art)
        expected = {
            "C1": "confirmed",
            "C-ERROR": "contradicted",
            "C-CHANGED": "changed_since_report",
        }
        openings = re.findall(r'<div class="card [^"]+"[^>]*>', page)
        found = {}
        for opening in openings:
            check_id = re.search(r'data-card-id="([^"]+)"', opening)
            disposition = re.search(r'data-disposition="([^"]+)"', opening)
            self.assertIsNotNone(check_id)
            self.assertIsNotNone(disposition)
            found[check_id.group(1)] = disposition.group(1)
        self.assertEqual(found, expected)
        self.assertEqual(artifact_audit._card_identity_problems(art, page), [])

    def test_source_mode_copy_comes_only_from_retained_source_kind(self) -> None:
        check = evidence_check()
        static_art = public_artifact([check])
        static_page = render.html_of(static_art)
        self.assertIn("Supplied recorded evidence", static_page)
        self.assertNotIn("Actual live query", static_page)

        live_art = json.loads(json.dumps(static_art))
        live_art["sources"][0]["kind"] = "live_tool"
        live_art["sources"][0]["retrieval"] = {
            "retrieved_at": "2026-08-25T13:10:00Z",
            "tool": "sum-api query",
            "arguments": {"query_name": "project status by week"},
        }
        live_art["evidence_coverage"]["provenance_groups"][0]["kind"] = "live_tool"
        live_page = render.html_of(live_art)
        self.assertIn("Actual live query", live_page)
        self.assertNotIn("Supplied recorded evidence", live_page)

    def test_rank_receipt_renders_agent_ordered_values_in_order(self) -> None:
        values = [
            ("Enterprise revenue", "$520"),
            ("SMB revenue", "$305"),
            ("Mid-market revenue", "$410"),
            ("Startup revenue", "$190"),
            ("Education revenue", "$120"),
        ]
        check = {
            "id": "RANK-1", "claim_id": "L-RANK", "type": "selection",
            "basis": "report", "verdict": "contradicted",
            "importance": "material", "severity": "high",
            "public_receipt": {
                "report_operand": {
                    "label": "Reported segment ranking",
                    "value": "Ranked from highest to lowest",
                    "location": "Top five segments heading",
                },
                "decisive_operands": [
                    {"label": label, "value": value,
                     "location": "Top five segments table"}
                    for label, value in values
                ],
                "explanation": (
                    "The displayed values place Mid-market above SMB despite the stated descending order."
                ),
            },
        }
        art = public_artifact([check])
        page = render.html_of(art)
        positions = [page.index(f"{label}</strong>: {value}") for label, value in values]
        self.assertEqual(positions, sorted(positions))


if __name__ == "__main__":
    unittest.main()
