"""Focused acceptance tests for the public-receipt architecture boundary."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import pathlib
import sys
import tempfile
import unittest

from tests.verify_v6_case import WORKFLOW_VERSION, build_case


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
        "occurrence_ids": ["INV1"],
        "primary_clause_id": "summary:C1",
        "member_clause_ids": ["summary:C1"],
        "primary_quote": "On-time delivery was 94%.",
        "context_occurrence_ids": [],
        "population_requirements": [],
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


def role_provenance_for(folder: pathlib.Path, *, report_text: str,
                        inventory: dict, report_metadata: dict,
                        coordinator: dict, claims: list, sources: list,
                        assessments: list, source_consideration: list,
                        whole_source_exclusions: list, resolutions: list,
                        checks: list, presentation: dict) -> dict:
    """Materialize exact bounded v6 role bundles for acceptance fixtures."""
    specs = []
    for partition in coordinator["partition_results"]:
        occurrence_ids = {
            row["occurrence_id"]
            for row in partition["occurrence_decisions"]
        }
        for clause in partition["clauses"]:
            occurrence_ids.update(clause.get("context_occurrence_ids") or [])
        partition_inventory = {
            **inventory,
            "items": [
                row for row in inventory["items"]
                if row["id"] in occurrence_ids
            ],
        }
        specs.append((
            f"claim-{partition['partition_id']}",
            "claim_taker", "claim_taking",
            {
                "partition_id": partition["partition_id"],
                "visible_text": report_text,
                "inventory": partition_inventory,
                "report_metadata": report_metadata,
            },
            partition,
        ))
    specs.append((
        "plan", "coordinator", "coordinator_semantic_plan",
        {
            "partition_results": coordinator["partition_results"],
            "inventory": inventory,
            "report_metadata": report_metadata,
            "internal_candidates": [],
            "approved_source_manifest": sources,
        },
        {
            "classification_reviews": coordinator["classification_reviews"],
            "canonical_claims": claims,
            "source_consideration_plan": coordinator[
                "source_consideration_plan"],
            "claim_dependencies": coordinator["claim_dependencies"],
            "verifier_assignments": coordinator["verifier_assignments"],
        },
    ))
    assessment_by_id = {row["id"]: row for row in assessments}
    claim_by_id = {row["id"]: row for row in claims}
    for assignment in coordinator["verifier_assignments"]:
        claim_ids = assignment["claim_ids"]
        verifier_assessments = [
            row for row in assessments if row["claim_id"] in claim_ids
        ]
        plan_rows = [
            row for row in coordinator["source_consideration_plan"]
            if row["claim_id"] in claim_ids
        ]
        considered_ids = {
            row["source_id"] for row in plan_rows
            if row["decision"] == "consider"
        }
        upstream = []
        seen_upstream = set()
        for assessment in verifier_assessments:
            for binding in assessment.get("operand_bindings") or []:
                origin = binding.get("origin") or {}
                if origin.get("kind") != "assessment_result":
                    continue
                upstream_id = origin["assessment_id"]
                upstream_assessment = assessment_by_id[upstream_id]
                if (
                    upstream_assessment["claim_id"] in claim_ids
                    or upstream_id in seen_upstream
                ):
                    continue
                seen_upstream.add(upstream_id)
                upstream.append({
                    "assessment_id": upstream_id,
                    "field": "calculation.result",
                    "value": upstream_assessment["calculation"]["result"],
                })
        specs.append((
            f"verify-{assignment['verifier_id']}",
            "evidence_verifier", "dependency_ordered_verification",
            {
                "canonical_claims": [claim_by_id[item] for item in claim_ids],
                "relevant_report_text": report_text,
                "assigned_sources": [
                    row for row in sources if row["id"] in considered_ids
                ],
                "source_consideration_plan": plan_rows,
                "accepted_upstream_assessment_results": upstream,
            },
            {
                "assessments": verifier_assessments,
                "source_consideration_results": [
                    row for row in source_consideration
                    if row["claim_id"] in claim_ids
                ],
                "proposed_resolutions": [
                    row for row in resolutions if row["claim_id"] in claim_ids
                ],
                "checks": [
                    row for row in checks if row["claim_id"] in claim_ids
                ],
            },
        ))
    specs.append((
        "resolve", "coordinator", "coordinator_global_resolution",
        {
            "canonical_claims": claims,
            "assessments": assessments,
            "source_consideration_results": source_consideration,
            "claim_dependencies": coordinator["claim_dependencies"],
        },
        {
            "sources": sources,
            "source_consideration": source_consideration,
            "whole_source_exclusions": whole_source_exclusions,
            "assessments": assessments,
            "resolutions": resolutions,
            "checks": checks,
            "presentation": presentation,
        },
    ))
    runs = []
    for role_id, role, stage, input_payload, output_payload in specs:
        input_path = folder / "role-inputs" / f"{role_id}.json"
        output_path = folder / "role-outputs" / f"{role_id}.json"
        input_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        input_path.write_text(json.dumps({
            "contract_version": WORKFLOW_VERSION, "role": role, "stage": stage,
            **input_payload,
        }))
        output_path.write_text(json.dumps({
            "contract_version": WORKFLOW_VERSION, "role": role,
            "stage": stage, "status": "complete", **output_payload,
        }))
        input_path.chmod(0o444)
        runs.append({
            "id": role_id, "role": role, "stage": stage,
            "input_bundle": {
                "path": str(input_path.relative_to(folder)),
                "sha256": hashlib.sha256(input_path.read_bytes()).hexdigest(),
            },
            "output_bundle": {
                "path": str(output_path.relative_to(folder)),
                "sha256": hashlib.sha256(output_path.read_bytes()).hexdigest(),
            },
            "allowed_read_paths": [
                str(input_path.relative_to(folder)),
                *(
                    row["evidence_file"]
                    for row in input_payload.get("assigned_sources", [])
                ),
            ],
            "observed_read_paths": [
                str(input_path.relative_to(folder)),
                *(
                    row["evidence_file"]
                    for row in input_payload.get("assigned_sources", [])
                ),
            ],
        })
    return {"route": "native_subagents", "runs": runs}


def evidence_check(*, verdict: str = "confirmed") -> dict:
    return {
        "id": "C1",
        "claim_id": "L1",
        "type": "semantic",
        "basis": "evidence",
        "verdict": verdict,
        "importance": "material",
        "addressed_clause_ids": ["summary:C1"],
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
            "requirement_id": "POP-L1-period",
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


def rounded_comparison(decimal_places: int = 1) -> dict:
    return {
        "mode": "rounded",
        "rounding": "half_up",
        "decimal_places": decimal_places,
    }


def exact_comparison() -> dict:
    return {"mode": "absolute_tolerance", "tolerance": 0}


def not_checkable_check() -> dict:
    return {
        "id": "C1",
        "claim_id": "L1",
        "type": "semantic",
        "basis": "report",
        "verdict": "not_checkable",
        "importance": "material",
        "addressed_clause_ids": ["summary:C1"],
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
    clause_ids = ["revenue:KPI", "revenue:TOTAL"]
    claims = folder / "claims.json"
    claims.write_text(json.dumps({
        "contract_version": WORKFLOW_VERSION,
        "claims": [{
            "id": "L1", "quote": "$359,490.34",
            "primary_quote": "$359,490.34",
            "public_label": "Total weekly revenue", "importance": "material",
            "classification": "material_claim",
            "inventory_ids": ["INV-KPI", "INV-TOTAL"],
            "occurrence_ids": ["INV-KPI", "INV-TOTAL"],
            "primary_clause_id": clause_ids[0],
            "member_clause_ids": clause_ids,
            "context_occurrence_ids": [],
            "population_requirements": [],
        }],
        "coordinator": {
            "partition_results": [{
                "partition_id": "revenue",
                "occurrence_decisions": [
                    {
                        "occurrence_id": "INV-KPI",
                        "classification": "material_claim",
                        "reason": "This occurrence states the displayed weekly total.",
                        "clause_ids": [clause_ids[0]],
                    },
                    {
                        "occurrence_id": "INV-TOTAL",
                        "classification": "material_claim",
                        "reason": "This occurrence repeats the displayed weekly total.",
                        "clause_ids": [clause_ids[1]],
                    },
                ],
                "clauses": [
                    {
                        "id": clause_ids[0], "occurrence_id": "INV-KPI",
                        "span": {"start": 0, "end": 11},
                        "quote": "$359,490.34",
                        "public_label": "Total weekly revenue",
                        "context_occurrence_ids": [],
                    },
                    {
                        "id": clause_ids[1], "occurrence_id": "INV-TOTAL",
                        "span": {"start": 0, "end": 11},
                        "quote": "$359,490.34",
                        "public_label": "Total weekly revenue",
                        "context_occurrence_ids": [],
                    },
                ],
            }],
            "classification_reviews": [
                {
                    "occurrence_id": occurrence_id,
                    "claim_taker_partition_id": "revenue",
                    "proposed_classification": "material_claim",
                    "final_classification": "material_claim",
                    "decision": "accept",
                    "reason": "The coordinator accepts this explicit material classification.",
                    "accepted_clause_ids": [clause_id],
                }
                for occurrence_id, clause_id in zip(
                    ["INV-KPI", "INV-TOTAL"], clause_ids)
            ],
            "verifier_assignments": [{"verifier_id": "V1", "claim_ids": ["L1"]}],
            "claim_dependencies": [],
            "source_consideration_plan": [{
                "source_id": "revenue-source", "claim_id": "L1",
                "decision": "consider",
                "reason": (
                    "The retained source contains the two values selected for this claim."
                ),
            }],
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
        "addressed_clause_ids": clause_ids,
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
    check["assessment_ids"] = ["AS1"]
    retained_source = source_for(evidence, source_id="revenue-source")
    checks = folder / "checks.json"
    checks_doc = {
        "contract_version": WORKFLOW_VERSION,
        "sources": [retained_source],
        "source_consideration": [{
            "source_id": "revenue-source", "claim_id": "L1",
            "coordinator_decision": "consider",
            "coordinator_reason": (
                "The retained source contains the two values selected for this claim."
            ),
            "verifier_decision": "used",
            "verifier_reason": (
                "The exact retained values address the displayed total calculation."
            ),
            "assessment_ids": ["AS1"],
        }],
        "whole_source_exclusions": [],
        "assessments": [{
            "id": "AS1", "claim_id": "L1", "basis": "evidence",
            "effect": "contradicts", "source_id": "revenue-source",
            "depends_on_assessment_ids": [],
            "operand_bindings": [
                {
                    "slot": "decisive_operands/0",
                    "origin": {
                        "kind": "source_receipt", "source_id": "revenue-source",
                        "receipt": {
                            "pointer": "/segment_alpha", "value": 218385.67,
                        },
                    },
                },
                {
                    "slot": "decisive_operands/1",
                    "origin": {
                        "kind": "source_receipt", "source_id": "revenue-source",
                        "receipt": {
                            "pointer": "/segment_beta", "value": 132104.67,
                        },
                    },
                },
            ],
            "calculation": {
                "expression": "218385.67 + 132104.67",
                "result": "$350,490.34",
            },
        }],
        "resolutions": [{
            "claim_id": "L1", "assessment_ids": ["AS1"],
            "state": "contradicted", "final_verdict": "contradicted",
            "reason": "The selected values calculate to a different displayed total.",
            "required_action_kind": "correct_report",
        }],
        "checks": [check],
        "presentation": {
            "summary": "The accepted result requires the displayed total to be corrected.",
            "check_ids": ["C1"],
            "actions": [{
                "id": "A1", "kind": "correct_report", "text": statement,
                "report_quote": report_quote, "check_ids": ["C1"],
                "resolution_ids": ["L1"],
            }],
            "limits": [],
        },
    }
    claims_doc = json.loads(claims.read_text())
    inventory_doc = json.loads(findings.read_text())["inventory"]
    checks_doc["role_provenance"] = role_provenance_for(
        folder, report_text=report_quote, inventory=inventory_doc,
        report_metadata={}, coordinator=claims_doc["coordinator"],
        claims=claims_doc["claims"], sources=checks_doc["sources"],
        assessments=checks_doc["assessments"],
        source_consideration=checks_doc["source_consideration"],
        whole_source_exclusions=checks_doc["whole_source_exclusions"],
        resolutions=checks_doc["resolutions"], checks=checks_doc["checks"],
        presentation=checks_doc["presentation"],
    )
    checks.write_text(json.dumps(checks_doc))
    return {
        "report": report, "claims": claims, "checks": checks,
        "findings": findings, "evidence_dir": folder,
        "preflight_record": folder / "preflight-record.json",
    }


def run_cli_bundle(paths: dict[str, pathlib.Path], out: pathlib.Path, *,
                   preflight: bool,
                   preflight_record: pathlib.Path | None = None) -> int:
    argv = sys.argv
    sys.argv = [
        "accept.py", "--report", str(paths["report"]),
        "--claims", str(paths["claims"]), "--checks", str(paths["checks"]),
        "--findings", str(paths["findings"]),
        "--evidence-dir", str(paths["evidence_dir"]), "--out", str(out),
    ]
    if preflight:
        sys.argv.insert(1, "--preflight-only")
    elif preflight_record is not None:
        sys.argv.extend(["--preflight-record", str(preflight_record)])
    try:
        return accept.main()
    finally:
        sys.argv = argv


def validate_v6_case(case: dict) -> dict:
    """Call the single acceptance path with one complete private bundle."""
    return accept.validate_acceptance_bundle(**{
        key: value for key, value in case.items() if key in {
            "text", "sandbox", "proposed", "checks_doc", "proposed_claims",
            "claims_meta", "inventory", "report_path", "bundle_root",
            "arithmetic_uses",
        }
    })


def validate_bundle_paths(paths: dict[str, pathlib.Path]) -> dict:
    """Load one CLI fixture and invoke the same pure acceptance function."""
    proposed, checks_doc = accept.load_checks(paths["checks"])
    proposed_claims, claims_meta = accept.load_claims_bundle(paths["claims"])
    findings_doc = json.loads(paths["findings"].read_text())
    text = accept.report_text(paths["report"], None)
    return accept.validate_acceptance_bundle(
        text=text, sandbox=paths["evidence_dir"], proposed=proposed,
        checks_doc=checks_doc, proposed_claims=proposed_claims,
        claims_meta=claims_meta, inventory=findings_doc["inventory"],
        report_path=paths["report"], arithmetic_uses=[],
        bundle_root=paths["checks"].parent,
    )


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
            case = build_case(pathlib.Path(raw))
            assessment = case["checks_doc"]["assessments"][2]
            assessment["effect"] = "contradicts"
            del assessment["population_alignment"]
            problems = validate_v6_case(case)["repair_reasons"]
            self.assertIn(
                "assessment 'AS-YOY-q3' has no population alignment for its canonical claim requirements",
                problems,
            )

    def test_dated_evidence_confirmation_requires_grounded_same_population(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            case = build_case(pathlib.Path(raw))
            del case["checks_doc"]["assessments"][2]["population_alignment"]
            problems = validate_v6_case(case)["repair_reasons"]
            self.assertIn(
                "assessment 'AS-YOY-q3' has no population alignment for its canonical claim requirements",
                problems,
            )

    def test_same_population_alignment_resolves_only_exact_agent_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            case = build_case(pathlib.Path(raw))
            result = validate_v6_case(case)
            self.assertEqual(result["repair_reasons"], [])
            self.assertEqual(
                result["assessments_by_id"]["AS-YOY-q3"][
                    "population_alignment"]["links"][0]["source_receipt"],
                {"pointer": "/period", "value": "2026-04-04"},
            )

            case["checks_doc"]["assessments"][2]["population_alignment"][
                "links"][0]["source_receipt"]["pointer"] = "/missing"
            self.assertIn(
                "assessment 'AS-YOY-q3' population_alignment.links[0].source_receipt did not match the retained source",
                validate_v6_case(case)["repair_reasons"],
            )

    def test_unreconciled_population_cannot_be_a_contradiction(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            case = build_case(pathlib.Path(raw))
            assessment = case["checks_doc"]["assessments"][2]
            assessment["effect"] = "contradicts"
            assessment["population_alignment"] = {
                "status": "unreconciled",
                "requirement_ids": ["POP-L-YOY-period"],
                "reason": "The retained source cannot be linked to the report period.",
                "missing_dimensions": ["report_period"],
                "conflict_receipts": [{"pointer": "/revenue_yoy", "value": 4.6}],
                "reconciliation_action": (
                    "Reconcile the source period with the report before changing either value."
                ),
            }
            self.assertIn(
                "assessment 'AS-YOY-q3' with unreconciled population must declare effect unreconciled",
                validate_v6_case(case)["repair_reasons"],
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

    def test_duplicate_source_identity_returns_one_reason_with_every_id(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            evidence = folder / "q3.json"
            evidence.write_text('{"metric": 1}\n')
            rows = [
                source_for(evidence, source_id="q3-a"),
                source_for(evidence, source_id="q3-b"),
                source_for(evidence, source_id="q3-c"),
            ]
            accepted, discarded = accept.validate_sources(folder, rows)
            self.assertEqual(accepted, [])
            duplicate_reasons = [
                problem
                for row in discarded
                for problem in row.get("problems") or []
                if "duplicate retained source identity" in problem
            ]
            self.assertEqual(len(duplicate_reasons), 1)
            for source_id in ("q3-a", "q3-b", "q3-c"):
                self.assertIn(source_id, duplicate_reasons[0])

    def test_source_consideration_covers_every_source_by_citation_or_exclusion(self) -> None:
        sources = [
            {"id": "q3", "kind": "supplied_file", "label": "Q3 warehouse extract",
             "evidence_file": "q3.json", "result_sha256": "1" * 64},
            {"id": "later-units", "kind": "supplied_file",
             "label": "Later units snapshot", "evidence_file": "later.json",
             "result_sha256": "2" * 64},
        ]
        claims = [claim()]
        check = evidence_check()
        check["public_receipt"]["source_id"] = "q3"
        check["assessment_ids"] = ["AS-q3"]
        assessments = [{
            "id": "AS-q3", "claim_id": "L1", "source_id": "q3",
            "effect": "supports",
        }]
        consideration = [
            {
                "source_id": "q3", "claim_id": "L1",
                "coordinator_decision": "consider",
                "coordinator_reason": (
                    "The retained source contains the delivery measure selected for review."
                ),
                "verifier_decision": "used",
                "verifier_reason": (
                    "The exact retained receipt addresses the canonical delivery claim."
                ),
                "assessment_ids": ["AS-q3"],
            },
            {
                "source_id": "later-units", "claim_id": "L1",
                "coordinator_decision": "exclude",
                "coordinator_reason": (
                    "The later snapshot does not cover this report-period delivery claim."
                ),
                "verifier_decision": "exclude",
                "verifier_reason": (
                    "No retained field in this source addresses the canonical claim."
                ),
                "assessment_ids": [],
            },
        ]
        plan = [{
            "source_id": row["source_id"], "claim_id": row["claim_id"],
            "decision": row["coordinator_decision"],
            "reason": row["coordinator_reason"],
        } for row in consideration]
        accepted, problems = accept.validate_source_consideration(
            consideration, sources, claims, [check], assessments=assessments,
            coordinator_plan=plan)
        self.assertEqual(problems, [])
        self.assertEqual(accepted, consideration)

        missing, problems = accept.validate_source_consideration(
            consideration[:1], sources, claims, [check], assessments=assessments,
            coordinator_plan=plan)
        self.assertEqual(missing, consideration[:1])
        self.assertIn(
            "source/claim pair 'later-units'/'L1' is missing",
            problems,
        )

    def test_considered_source_requires_an_assessment_and_role_agreement(self) -> None:
        sources = [
            {"id": "q3", "kind": "supplied_file", "label": "Q3 warehouse extract",
             "evidence_file": "q3.json", "result_sha256": "1" * 64},
            {"id": "later-units", "kind": "supplied_file",
             "label": "Later units snapshot", "evidence_file": "later.json",
             "result_sha256": "2" * 64},
        ]
        check = evidence_check()
        check["public_receipt"]["source_id"] = "q3"
        check["assessment_ids"] = ["AS-q3"]
        consideration = [
                {
                    "source_id": "q3", "claim_id": "L1",
                    "coordinator_decision": "consider",
                    "coordinator_reason": (
                        "The source contains the selected delivery measure for review."
                    ),
                    "verifier_decision": "used",
                    "verifier_reason": (
                        "The exact source assessment addresses the canonical claim."
                    ),
                    "assessment_ids": ["AS-q3"],
                },
                {
                    "source_id": "later-units", "claim_id": "L1",
                    "coordinator_decision": "consider",
                    "coordinator_reason": (
                        "The coordinator assigns this source to the claim for review."
                    ),
                    "verifier_decision": "exclude",
                    "verifier_reason": (
                        "The verifier cannot use this source for the canonical claim."
                    ),
                    "assessment_ids": [],
                },
            ]
        plan = [{
            "source_id": row["source_id"], "claim_id": row["claim_id"],
            "decision": row["coordinator_decision"],
            "reason": row["coordinator_reason"],
        } for row in consideration]
        _accepted, problems = accept.validate_source_consideration(
            consideration, sources, [claim()], [check], assessments=[{
                "id": "AS-q3", "claim_id": "L1", "source_id": "q3",
                "effect": "supports",
            }], coordinator_plan=plan,
        )
        self.assertIn(
            "source/claim pair 'later-units'/'L1' has unresolved coordinator/verifier disagreement",
            problems,
        )
        self.assertIn(
            "considered source/claim pair 'later-units'/'L1' has no assessment",
            problems,
        )

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
                 *, report: str = REPORT, label: str = CLAIM_LABEL,
                 report_date: str | None = None):
        sources = []
        if source is not None:
            sources, source_drops = accept.validate_sources(
                folder, [source], folder / "report.md")
            self.assertEqual(source_drops, [])
        return accept.validate_receipts(
            report, folder, [check], {"L1"}, folder / "report.md",
            sources=sources, claim_labels={"L1": label},
            report_date=report_date,
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
        check["type"] = "arithmetic"
        check.pop("evidence_json")
        check["report_quote"] = report
        check["public_receipt"].pop("source_id")
        check["numeric_comparison"] = exact_comparison()
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
            "numeric_comparison": exact_comparison(),
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
            "confirmed report-basis arithmetic values differ under the declared "
            "numeric comparison",
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
            "numeric_comparison": exact_comparison(),
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

    def test_host_declared_rounding_controls_arithmetic_disposition(self) -> None:
        report = (
            "Revenue decreased 4.6% from the same week last year. "
            "Current revenue was 350490.34 and prior revenue was 367290.32."
        )
        check = {
            "id": "C1", "claim_id": "L1", "type": "arithmetic",
            "basis": "report", "verdict": "confirmed", "importance": "material",
            "report_quote": report, "numeric_comparison": rounded_comparison(1),
            "public_receipt": {
                "report_operand": {
                    "label": "Year-over-year revenue decrease", "value": "4.6%",
                    "location": "Revenue commentary",
                },
                "decisive_operands": [
                    {"label": "Current revenue", "value": "350490.34",
                     "location": "Revenue total"},
                    {"label": "Prior-year revenue", "value": "367290.32",
                     "location": "Prior-year total"},
                ],
                "calculation": {
                    "expression": "(367290.32 - 350490.34) / 367290.32 * 100",
                    "result": "4.574032879496728%",
                },
                "explanation": (
                    "The recomputed decrease rounds to the one-decimal percentage shown."
                ),
            },
        }
        with tempfile.TemporaryDirectory() as raw:
            kept, dropped = self.validate(
                pathlib.Path(raw), check, report=report,
                label="Year-over-year revenue decrease")
            self.assertEqual(dropped, [])
            self.assertEqual(
                kept[0]["numeric_comparison"]["customer_result"], "4.6%")

            contradicted = json.loads(json.dumps(check))
            contradicted["verdict"] = "contradicted"
            kept, dropped = self.validate(
                pathlib.Path(raw), contradicted, report=report,
                label="Year-over-year revenue decrease")
            self.assertEqual(kept, [])
            self.assertIn(
                "contradicted report-basis arithmetic values match under the "
                "declared numeric comparison",
                dropped[0]["problems"],
            )

    def test_report_arithmetic_requires_explicit_comparison_declaration(self) -> None:
        report = "On-time delivery was 94%; 94 deliveries out of 100 total."
        check = evidence_check()
        check["basis"] = "report"
        check["type"] = "arithmetic"
        check.pop("evidence_json")
        check["report_quote"] = report
        check["public_receipt"].pop("source_id")
        with tempfile.TemporaryDirectory() as raw:
            kept, dropped = self.validate(pathlib.Path(raw), check, report=report)
        self.assertEqual(kept, [])
        self.assertIn(
            "numeric_comparison is required for numeric report-basis arithmetic",
            dropped[0]["problems"],
        )

    def test_host_declared_absolute_tolerance_controls_disposition(self) -> None:
        report = "Adjusted total was 100.00 from base 100 plus 0.004."
        check = {
            "id": "C1", "claim_id": "L1", "type": "arithmetic",
            "basis": "report", "verdict": "confirmed", "importance": "material",
            "report_quote": report,
            "numeric_comparison": {
                "mode": "absolute_tolerance", "tolerance": "0.01",
            },
            "public_receipt": {
                "report_operand": {
                    "label": "Adjusted total", "value": "100.00",
                    "location": "Adjusted total line",
                },
                "decisive_operands": [
                    {"label": "Base total", "value": 100,
                     "location": "Adjusted total line"},
                    {"label": "Adjustment", "value": "0.004",
                     "location": "Adjusted total line"},
                ],
                "calculation": {
                    "expression": "100 + 0.004", "result": "100.004",
                },
                "explanation": (
                    "The computed total is within the verifier-declared absolute tolerance."
                ),
            },
        }
        with tempfile.TemporaryDirectory() as raw:
            kept, dropped = self.validate(
                pathlib.Path(raw), check, report=report, label="Adjusted total")
            self.assertEqual(dropped, [])
            self.assertTrue(kept[0]["numeric_comparison"]["matches"])
            self.assertNotIn(
                "customer_result", kept[0]["numeric_comparison"])

            invalid = json.loads(json.dumps(check))
            invalid["numeric_comparison"]["tolerance"] = -0.01
            kept, dropped = self.validate(
                pathlib.Path(raw), invalid, report=report, label="Adjusted total")
            self.assertEqual(kept, [])
            self.assertIn(
                "numeric_comparison.tolerance must be a non-negative public numeric value",
                dropped[0]["problems"],
            )

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
        occurrence_decisions = []
        classification_reviews = []
        for index, inventory_id in enumerate(("INV1", "INV2", "INV3", "INV4"), 1):
            occurrence_decisions.append({
                "occurrence_id": inventory_id,
                "classification": "structural_context",
                "reason": "This visible item organizes the report and is not an analytical assertion.",
                "clause_ids": [],
            })
            classification_reviews.append({
                "occurrence_id": inventory_id,
                "claim_taker_partition_id": "report-shell",
                "proposed_classification": "structural_context",
                "final_classification": "structural_context",
                "decision": "accept",
                "reason": "The coordinator accepts the explicit structural classification.",
                "accepted_clause_ids": [],
            })
        occurrence_decisions.append({
            "occurrence_id": "INV5",
            "classification": "material_claim",
            "reason": "This occurrence states the report's claimed data-currency date.",
            "clause_ids": ["report-shell:C1"],
        })
        material_quote = "Data is current through April 4, 2026."
        clauses = [{
            "id": "report-shell:C1", "occurrence_id": "INV5",
            "span": {"start": 0, "end": len(material_quote)},
            "quote": material_quote,
            "public_label": "Reported data currency date",
            "context_occurrence_ids": ["INV3"],
        }]
        classification_reviews.append({
            "occurrence_id": "INV5",
            "claim_taker_partition_id": "report-shell",
            "proposed_classification": "material_claim",
            "final_classification": "material_claim",
            "decision": "accept",
            "reason": "The coordinator accepts the explicit material classification.",
            "accepted_clause_ids": ["report-shell:C1"],
        })
        claims = [{
            "id": "L1",
            "quote": material_quote,
            "primary_quote": material_quote,
            "public_label": "Reported data currency date",
            "classification": "material_claim",
            "importance": "material",
            "inventory_ids": ["INV5"],
            "occurrence_ids": ["INV5"],
            "primary_clause_id": "report-shell:C1",
            "member_clause_ids": ["report-shell:C1"],
            "context_occurrence_ids": ["INV3"],
            "population_requirements": [],
        }]
        coordinator = {
            "partition_results": [{
                "partition_id": "report-shell",
                "occurrence_decisions": occurrence_decisions,
                "clauses": clauses,
            }],
            "classification_reviews": classification_reviews,
            "verifier_assignments": [{"verifier_id": "V1", "claim_ids": ["L1"]}],
            "claim_dependencies": [],
            "source_consideration_plan": [],
        }
        handoff, problems = accept.validate_coordinator_handoff(
            claims, coordinator, inv)
        self.assertEqual(problems, [])
        self.assertEqual(len(handoff["structural_context"]), 4)
        self.assertEqual(handoff["material_claim_ids"], ["L1"])

        report_text = " ".join(item["displayed"] for item in inv["items"])
        grounded, discarded = accept.validate_claims(report_text, claims)
        self.assertEqual(discarded, [])
        ledger = accept.attach_claim_outcomes(
            grounded, [{"id": "C1", "claim_id": "L1", "verdict": "not_checkable"}])
        discarded_claims = []
        classified_inventory = copy.deepcopy(inv)
        ledger = accept.apply_host_classifications(
            ledger, discarded_claims, classified_inventory,
            structural_context=handoff["structural_context"],
            material_inventory_claim_ids=handoff["material_inventory_claim_ids"],
        )
        self.assertEqual(discarded_claims, [])
        covered = inventory.cover(
            classified_inventory, ledger,
            structural_context=handoff["structural_context"],
            material_inventory_claim_ids=handoff["material_inventory_claim_ids"],
        )
        self.assertEqual(covered["missing"], [])
        self.assertEqual(covered["material"], 1)
        self.assertEqual([row["id"] for row in ledger], ["L1"])
        self.assertTrue(all(item["importance"] == "unclassified" for item in inv["items"]))
        self.assertTrue(all(
            item["classification"] == "structural_context"
            for item in classified_inventory["items"][:4]
        ))

        with tempfile.TemporaryDirectory() as raw:
            root = pathlib.Path(raw)
            report_path = root / "report.md"
            report_path.write_text(report_text + "\n")
            check = {
                "id": "C1", "claim_id": "L1", "type": "semantic",
                "basis": "report", "verdict": "not_checkable",
                "importance": "material", "severity": None,
                "addressed_clause_ids": ["report-shell:C1"],
                "assessment_ids": [], "report_quote": material_quote,
                "public_receipt": {
                    "report_operand": {
                        "label": "Reported data currency date",
                        "value": "April 4, 2026",
                        "location": "Data-currency statement",
                    },
                    "decisive_operands": [],
                    "explanation": (
                        "No approved evidence source was supplied to verify the stated data-currency date."
                    ),
                },
            }
            checks_doc = {
                "contract_version": WORKFLOW_VERSION,
                "sources": [], "source_consideration": [],
                "whole_source_exclusions": [], "assessments": [],
                "resolutions": [{
                    "claim_id": "L1", "assessment_ids": [],
                    "state": "not_assessed", "final_verdict": "not_checkable",
                    "reason": (
                        "No approved evidence source was supplied for this material claim."
                    ),
                    "required_action_kind": "review_before_share",
                }],
                "checks": [check],
                "presentation": {
                    "summary": (
                        "The data-currency claim remains not checkable from the supplied inputs."
                    ),
                    "check_ids": ["C1"],
                    "actions": [{
                        "id": "A1", "kind": "review_before_share",
                        "text": (
                            "Review the unverified data-currency claim before sharing this report."
                        ),
                        "report_quote": material_quote,
                        "check_ids": ["C1"], "resolution_ids": ["L1"],
                    }],
                    "limits": [],
                },
            }
            checks_doc["role_provenance"] = role_provenance_for(
                root, report_text=report_text, inventory=inv,
                report_metadata={}, coordinator=coordinator, claims=claims,
                sources=checks_doc["sources"],
                assessments=checks_doc["assessments"],
                source_consideration=checks_doc["source_consideration"],
                whole_source_exclusions=checks_doc["whole_source_exclusions"],
                resolutions=checks_doc["resolutions"],
                checks=checks_doc["checks"],
                presentation=checks_doc["presentation"],
            )
            case = {
                "text": report_text, "sandbox": root, "proposed": [check],
                "checks_doc": checks_doc, "proposed_claims": claims,
                "claims_meta": {
                    "contract_version": WORKFLOW_VERSION,
                    "coordinator": coordinator,
                },
                "inventory": inv, "report_path": report_path,
                "bundle_root": root, "arithmetic_uses": [],
            }
            accepted = validate_v6_case(case)
            self.assertEqual(accepted["repair_reasons"], [])
            self.assertEqual(accepted["claims_in_ledger"], 1)
            self.assertEqual(accepted["claims_reached_by_a_check"], 1)
            self.assertEqual([row["id"] for row in accepted["claims"]], ["L1"])
            self.assertTrue(all(item["importance"] == "unclassified" for item in inv["items"]))

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
                "primary_quote": "Revenue was $10.",
                "public_label": "Reported revenue", "importance": "material",
                "classification": "material_claim", "inventory_ids": ["INV1"],
                "occurrence_ids": ["INV1"], "primary_clause_id": "p1:C1",
                "member_clause_ids": ["p1:C1"], "context_occurrence_ids": [],
                "population_requirements": [],
            },
            {
                "id": "L2", "quote": "Revenue was $10.",
                "primary_quote": "Revenue was $10.",
                "public_label": "Second reported revenue", "importance": "material",
                "classification": "material_claim", "inventory_ids": ["INV1"],
                "occurrence_ids": ["INV1"], "primary_clause_id": "p2:C1",
                "member_clause_ids": ["p2:C1"], "context_occurrence_ids": [],
                "population_requirements": [],
            },
        ]
        coordinator = {
            "partition_results": [
                {
                    "partition_id": "p1",
                    "occurrence_decisions": [{
                        "occurrence_id": "INV1", "classification": "material_claim",
                        "reason": "This partition declares the visible occurrence material.",
                        "clause_ids": ["p1:C1"],
                    }],
                    "clauses": [{
                        "id": "p1:C1", "occurrence_id": "INV1",
                        "span": {"start": 0, "end": 16},
                        "quote": "Revenue was $10.",
                        "public_label": "Reported revenue",
                        "context_occurrence_ids": [],
                    }],
                },
                {
                    "partition_id": "p2",
                    "occurrence_decisions": [{
                        "occurrence_id": "INV1", "classification": "material_claim",
                        "reason": "A second partition incorrectly consumes the same occurrence.",
                        "clause_ids": ["p2:C1"],
                    }],
                    "clauses": [{
                        "id": "p2:C1", "occurrence_id": "INV1",
                        "span": {"start": 0, "end": 16},
                        "quote": "Revenue was $10.",
                        "public_label": "Second reported revenue",
                        "context_occurrence_ids": [],
                    }],
                },
            ],
            "classification_reviews": [{
                "occurrence_id": "INV1", "claim_taker_partition_id": "p1",
                "proposed_classification": "material_claim",
                "final_classification": "material_claim", "decision": "accept",
                "reason": "The coordinator records one explicit classification review.",
                "accepted_clause_ids": ["p1:C1"],
            }],
            "verifier_assignments": [
                {"verifier_id": "V1", "claim_ids": ["L1"]},
                {"verifier_id": "V2", "claim_ids": ["L2"]},
            ],
            "claim_dependencies": [],
            "source_consideration_plan": [],
        }
        _handoff, problems = accept.validate_coordinator_handoff(
            claims, coordinator, inv)
        self.assertIn(
            "inventory occurrence 'INV1' has more than one claim-taker decision",
            problems,
        )

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
            "resolution_ids": ["L1"],
        }
        resolutions = {"L1": {
            "claim_id": "L1", "assessment_ids": ["AS1"],
            "state": "supported", "final_verdict": "confirmed",
            "reason": "The accepted assessment supports the canonical claim.",
            "required_action_kind": "review_before_share",
        }}
        accepted, problems = accept.validate_presentation(
            {"presentation": {
                "summary": "The accepted receipt supports the report value before sharing.",
                "check_ids": ["C1"],
                "actions": [action], "limits": [],
            }},
            REPORT, {"C1"}, accepted_checks=[evidence_check()],
            resolutions=resolutions, claim_ancestors={"L1": []},
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
            "claim_id": "L-TOTAL",
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
            "resolution_ids": ["L-TOTAL"],
        }
        resolutions = {"L-TOTAL": {
            "claim_id": "L-TOTAL", "assessment_ids": ["AS-TOTAL"],
            "state": "contradicted", "final_verdict": "contradicted",
            "reason": "The accepted arithmetic assessment contradicts the total.",
            "required_action_kind": "correct_report",
        }}
        accepted, problems = accept.validate_presentation(
            {"presentation": {
                "summary": "The accepted contradiction requires a report correction before sharing.",
                "check_ids": ["C-TOTAL"],
                "actions": [action], "limits": [],
            }},
            REPORT, {"C-TOTAL"}, accepted_checks=[check],
            resolutions=resolutions, claim_ancestors={"L-TOTAL": []},
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
            resolutions=resolutions, claim_ancestors={"L-TOTAL": []},
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
            "resolution_ids": ["L-HIGH"],
        }
        resolutions = {
            claim_id: {
                "claim_id": claim_id, "assessment_ids": [f"AS-{claim_id}"],
                "state": "supported", "final_verdict": "confirmed",
                "reason": "The accepted assessment supports this canonical claim.",
                "required_action_kind": "review_before_share",
            }
            for claim_id in ("L-HIGH", "L-LOW")
        }
        accepted, problems = accept.validate_presentation(
            {"presentation": {
                "summary": "The selected confirmation supplies decision-relevant checking context.",
                "check_ids": ["C-LOW"],
                "actions": [action], "limits": [],
            }},
            REPORT, {"C-HIGH", "C-LOW"}, accepted_checks=[high, low],
            resolutions=resolutions,
            claim_ancestors={"L-HIGH": [], "L-LOW": []},
        )
        self.assertEqual(problems, [])
        self.assertEqual(accepted["check_ids"], ["C-LOW"])

        error = evidence_check(verdict="contradicted")
        error["id"] = "C-ERR"
        error["claim_id"] = "L-ERR"
        resolutions["L-ERR"] = {
            "claim_id": "L-ERR", "assessment_ids": ["AS-L-ERR"],
            "state": "contradicted", "final_verdict": "contradicted",
            "reason": "The accepted assessment contradicts this canonical claim.",
            "required_action_kind": "correct_report",
        }
        _accepted, problems = accept.validate_presentation(
            {"presentation": {
                "summary": "The accepted results require review before this report is shared.",
                "check_ids": ["C-ERR"],
                "actions": [action], "limits": [],
            }},
            REPORT, {"C-HIGH", "C-LOW", "C-ERR"},
            accepted_checks=[high, low, error],
            resolutions=resolutions,
            claim_ancestors={"L-HIGH": [], "L-LOW": [], "L-ERR": []},
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
            "resolution_ids": ["L1"],
        }
        resolutions = {"L1": {
            "claim_id": "L1", "assessment_ids": ["AS1"],
            "state": "unreconciled", "final_verdict": "not_checkable",
            "reason": "The approved source cannot be aligned to the report population.",
            "required_action_kind": "reconcile_before_change",
        }}
        _accepted, problems = accept.validate_presentation(
            {"presentation": {
                "summary": "The source conflict must be reconciled before either value changes.",
                "check_ids": ["C1"],
                "actions": [action], "limits": [],
            }},
            REPORT, {"C1"}, accepted_checks=[check],
            resolutions=resolutions, claim_ancestors={"L1": []},
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
            resolutions=resolutions, claim_ancestors={"L1": []},
        )
        self.assertEqual(problems, [])
        self.assertEqual(accepted["actions"][0]["kind"], "reconcile_before_change")

    def test_dependency_unresolved_claim_accepts_host_reconciliation_action(self) -> None:
        check = not_checkable_check()
        action = {
            "id": "A1", "kind": "reconcile_before_change",
            "text": (
                "Reconcile the unresolved upstream result before changing this dependent claim."
            ),
            "report_quote": "On-time delivery was 94%.",
            "check_ids": ["C1"],
            "resolution_ids": ["L-UPSTREAM", "L1"],
        }
        resolutions = {
            "L-UPSTREAM": {
                "claim_id": "L-UPSTREAM", "assessment_ids": [],
                "state": "unreconciled", "final_verdict": "not_checkable",
                "reason": "The upstream claim cannot yet be grounded from approved evidence.",
                "required_action_kind": "reconcile_before_change",
            },
            "L1": {
                "claim_id": "L1", "assessment_ids": [],
                "state": "dependency_unresolved", "final_verdict": "not_checkable",
                "reason": "The dependent claim cannot resolve until its upstream input is grounded.",
                "required_action_kind": "reconcile_before_change",
            },
        }
        accepted, problems = accept.validate_presentation(
            {"presentation": {
                "summary": "The dependent claim remains unresolved until its input is grounded.",
                "check_ids": ["C1"], "actions": [action], "limits": [],
            }},
            REPORT, {"C1"}, accepted_checks=[check], resolutions=resolutions,
            claim_ancestors={"L-UPSTREAM": [], "L1": ["L-UPSTREAM"]},
        )
        self.assertEqual(problems, [])
        self.assertEqual(accepted["actions"], [action])

    def test_concise_verdict_summary_is_required_and_grounded_to_accepted_ids(self) -> None:
        action = {
            "id": "A1", "kind": "review_before_share",
            "text": "Review the accepted receipt before sharing the report.",
            "report_quote": "On-time delivery was 94%.", "check_ids": ["C1"],
            "resolution_ids": ["L1"],
        }
        resolutions = {"L1": {
            "claim_id": "L1", "assessment_ids": ["AS1"],
            "state": "supported", "final_verdict": "confirmed",
            "reason": "The accepted assessment supports the canonical claim.",
            "required_action_kind": "review_before_share",
        }}
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
                    resolutions=resolutions, claim_ancestors={"L1": []},
                )
                self.assertIn(expected, problems)


class CliTests(unittest.TestCase):
    def test_duplicate_source_reasons_match_in_preflight_and_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            paths = write_invalid_preflight_bundle(folder)
            document = json.loads(paths["checks"].read_text())
            duplicate = dict(document["sources"][0], id="revenue-source-copy")
            document["sources"].append(duplicate)
            duplicate_pair = copy.deepcopy(document["source_consideration"][0])
            duplicate_pair["source_id"] = "revenue-source-copy"
            document["source_consideration"].append(duplicate_pair)
            paths["checks"].write_text(json.dumps(document))
            preflight_out = folder / "preflight-duplicate.json"
            acceptance_out = folder / "receipts-duplicate.json"
            self.assertEqual(
                run_cli_bundle(paths, preflight_out, preflight=True), 2)
            self.assertEqual(
                run_cli_bundle(paths, acceptance_out, preflight=False), 2)
            preflight = json.loads(preflight_out.read_text())["repair_reasons"]
            acceptance = json.loads(acceptance_out.read_text())["repair_reasons"]
            pure_acceptance = validate_bundle_paths(paths)["repair_reasons"]
            self.assertEqual(preflight, pure_acceptance)
            self.assertEqual(
                preflight,
                [reason for reason in acceptance
                 if not reason.startswith("final acceptance ")],
            )
            self.assertIn(
                "final acceptance requires --preflight-record", acceptance)
            duplicate_reasons = [
                reason for reason in preflight
                if "duplicate retained source identity" in reason
            ]
            self.assertEqual(len(duplicate_reasons), 1)
            self.assertIn("revenue-source", duplicate_reasons[0])
            self.assertIn("revenue-source-copy", duplicate_reasons[0])

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
                "claim resolution 'L1' must have exactly one customer check",
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
            pure_acceptance = validate_bundle_paths(paths)
            self.assertEqual(
                preflight["repair_reasons"], pure_acceptance["repair_reasons"])
            self.assertEqual(
                preflight["repair_reasons"],
                [reason for reason in acceptance["repair_reasons"]
                 if not reason.startswith("final acceptance ")],
            )

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
            checks.write_text(json.dumps({
                "sources": [], "source_consideration": [], "checks": [bad],
            }))
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
                "private workflow version must be verify-role-handoff/coordinator-v6",
                "coordinator handoff is missing or not an object",
                "evidence-verifier check 'C1' "
                "public_receipt.calculation.result is not a public numeric value",
                "evidence-verifier check 'C1' public_receipt.calculation is not "
                "allowed for not_checkable",
                "assessments is missing or not an array",
                "resolutions is missing or not an array",
                "whole_source_exclusions is missing or not an array",
                "presentation is missing",
                "role_provenance is missing or not an object",
                "inventory occurrence 'INV1' assigned to 'L1': material inventory "
                "item has no completed outcome",
            ])

    def test_cli_retains_public_label_and_exact_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            case = build_case(folder)
            claims = folder / "claims.json"
            claims.write_text(json.dumps(case["claims_doc"]))
            checks = folder / "checks.json"
            checks.write_text(json.dumps(case["checks_doc"]))
            findings = folder / "findings.json"
            findings.write_text(json.dumps({"inventory": case["inventory"]}))
            paths = {
                "report": case["report_path"], "claims": claims,
                "checks": checks, "findings": findings,
                "evidence_dir": folder,
            }
            preflight = folder / "preflight.json"
            self.assertEqual(
                run_cli_bundle(paths, preflight, preflight=True), 0)
            out = folder / "receipts.json"
            code = run_cli_bundle(
                paths, out, preflight=False, preflight_record=preflight)
            self.assertEqual(code, 0)
            doc = json.loads(out.read_text())
            self.assertEqual(doc["discarded_claims"], [])
            self.assertEqual(doc["semantic_status"], "complete")
            self.assertEqual(
                doc["claims"][0]["public_label"], "Total weekly revenue")
            self.assertEqual(
                doc["checks"][0]["public_receipt"],
                case["proposed"][0]["public_receipt"],
            )

    def test_cli_records_missing_coordinator_as_a_fail_closed_repair_reason(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            report = folder / "report.md"
            report.write_text("On-time delivery was 94%.\n")
            claims = folder / "claims.json"
            claims.write_text(json.dumps({"claims": [claim()]}))
            checks = folder / "checks.json"
            checks.write_text(json.dumps({
                "sources": [], "source_consideration": [],
                "checks": [not_checkable_check()],
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
