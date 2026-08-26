"""Accepted coordinator-v6 bundle used by focused semantic-workflow tests."""
from __future__ import annotations

import copy
import hashlib
import json
import pathlib


WORKFLOW_VERSION = "verify-role-handoff/coordinator-v6"


def _digest(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _role_file(root: pathlib.Path, relative: str, payload: dict) -> dict:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.chmod(0o644)
    path.write_text(json.dumps(payload, sort_keys=True) + "\n")
    if relative.startswith("role-inputs/"):
        path.chmod(0o444)
    return {"path": relative, "sha256": _digest(path)}


def build_case(root: pathlib.Path) -> dict:
    """Write private inputs and return one mechanically accepted v6 bundle."""
    report_text = " ".join([
        "Week ending 2026-04-04.",
        "$359,490.34",
        "$359,490.34",
        "$218,385.67",
        "$132,104.67",
        "$367,290.32",
        "Revenue is down 4.6% against the same week last year.",
        "Source: weekly report.",
    ])
    report = root / "report.md"
    report.write_text(report_text + "\n")
    evidence = root / "q3.json"
    evidence.write_text(
        '{"period":"2026-04-04","revenue_yoy":4.6}\n')

    displayed = [
        ("INV-PERIOD", "Week ending 2026-04-04.", "header period"),
        ("INV-KPI", "$359,490.34", "Revenue KPI tile"),
        ("INV-TOTAL", "$359,490.34", "segment table Total row"),
        ("INV-ALPHA", "$218,385.67", "segment table, Alpha current revenue"),
        ("INV-BETA", "$132,104.67", "segment table, Beta current revenue"),
        ("INV-PRIOR", "$367,290.32", "segment table, prior total revenue"),
        (
            "INV-YOY",
            "Revenue is down 4.6% against the same week last year.",
            "weekly revenue narrative",
        ),
        ("INV-SOURCE", "Source: weekly report.", "source line"),
    ]
    inventory = {
        "reader": "html",
        "complete": True,
        "items": [
            {
                "id": item_id,
                "kind": "html_text",
                "displayed": text,
                "quote": text,
                "location": location,
                "importance": "unclassified",
            }
            for item_id, text, location in displayed
        ],
    }

    material = {
        "INV-KPI": ("P-main:CL-KPI", "Total weekly revenue"),
        "INV-TOTAL": ("P-main:CL-TOTAL", "Total weekly revenue"),
        "INV-YOY": ("P-main:CL-YOY", "Year-over-year weekly revenue change"),
    }
    decisions = []
    clauses = []
    for item_id, text, _location in displayed:
        if item_id in material:
            clause_id, public_label = material[item_id]
            decisions.append({
                "occurrence_id": item_id,
                "classification": "material_claim",
                "reason": (
                    "This visible occurrence states a quantitative assertion whose "
                    "truth changes the report conclusion."
                ),
                "clause_ids": [clause_id],
            })
            clauses.append({
                "id": clause_id,
                "occurrence_id": item_id,
                "span": {"start": 0, "end": len(text)},
                "quote": text,
                "public_label": public_label,
                "context_occurrence_ids": [],
            })
        else:
            decisions.append({
                "occurrence_id": item_id,
                "classification": "structural_context",
                "reason": (
                    "This visible occurrence supplies context used to interpret or "
                    "calculate the material assertions."
                ),
                "clause_ids": [],
            })

    reviews = []
    for decision in decisions:
        reviews.append({
            "occurrence_id": decision["occurrence_id"],
            "claim_taker_partition_id": "P-main",
            "proposed_classification": decision["classification"],
            "final_classification": decision["classification"],
            "decision": "accept",
            "reason": (
                "The coordinator independently accepts this explicit classification "
                "for the canonical semantic plan."
            ),
            "accepted_clause_ids": list(decision["clause_ids"]),
        })

    claims = [
        {
            "id": "L-TOTAL",
            "quote": "$359,490.34",
            "primary_quote": "$359,490.34",
            "public_label": "Total weekly revenue",
            "importance": "material",
            "classification": "material_claim",
            "primary_clause_id": "P-main:CL-KPI",
            "member_clause_ids": ["P-main:CL-KPI", "P-main:CL-TOTAL"],
            "occurrence_ids": ["INV-KPI", "INV-TOTAL"],
            "inventory_ids": ["INV-KPI", "INV-TOTAL"],
            "context_occurrence_ids": ["INV-ALPHA", "INV-BETA"],
            "population_requirements": [],
        },
        {
            "id": "L-YOY",
            "quote": "Revenue is down 4.6% against the same week last year.",
            "primary_quote": "Revenue is down 4.6% against the same week last year.",
            "public_label": "Year-over-year weekly revenue change",
            "importance": "material",
            "classification": "material_claim",
            "primary_clause_id": "P-main:CL-YOY",
            "member_clause_ids": ["P-main:CL-YOY"],
            "occurrence_ids": ["INV-YOY"],
            "inventory_ids": ["INV-YOY"],
            "context_occurrence_ids": ["INV-PERIOD", "INV-PRIOR"],
            "population_requirements": [{
                "id": "POP-L-YOY-period",
                "dimension": "report_period",
                "report_quote": "Week ending 2026-04-04.",
            }],
        },
    ]

    coordinator = {
        "partition_results": [{
            "partition_id": "P-main",
            "occurrence_decisions": decisions,
            "clauses": clauses,
        }],
        "classification_reviews": reviews,
        "verifier_assignments": [
            {"verifier_id": "V-total", "claim_ids": ["L-TOTAL"]},
            {"verifier_id": "V-yoy", "claim_ids": ["L-YOY"]},
        ],
        "claim_dependencies": [{
            "id": "DEP-TOTAL-YOY",
            "upstream_claim_id": "L-TOTAL",
            "downstream_claim_id": "L-YOY",
            "role": "decisive_operand",
            "reason": (
                "The year-over-year calculation consumes the accepted current total."
            ),
        }],
        "source_consideration_plan": [{
            "source_id": "q3-analytics",
            "claim_id": "L-TOTAL",
            "decision": "exclude",
            "reason": (
                "The approved source does not contain the report's displayed segment totals."
            ),
        }, {
            "source_id": "q3-analytics",
            "claim_id": "L-YOY",
            "decision": "consider",
            "reason": (
                "The approved source contains a year-over-year revenue value for review."
            ),
        }],
    }

    source = {
        "id": "q3-analytics",
        "kind": "supplied_file",
        "label": "Warehouse analytics extract",
        "evidence_file": evidence.name,
        "result_sha256": _digest(evidence),
    }
    assessments = [
        {
            "id": "AS-TOTAL-report",
            "claim_id": "L-TOTAL",
            "basis": "report",
            "effect": "contradicts",
            "depends_on_assessment_ids": [],
            "operand_bindings": [
                {
                    "slot": "decisive_operands/0",
                    "origin": {
                        "kind": "report_occurrence", "occurrence_id": "INV-ALPHA",
                    },
                },
                {
                    "slot": "decisive_operands/1",
                    "origin": {
                        "kind": "report_occurrence", "occurrence_id": "INV-BETA",
                    },
                },
            ],
            "calculation": {
                "expression": "218385.67 + 132104.67",
                "result": "$350,490.34",
            },
            "numeric_comparison": {
                "mode": "rounded", "rounding": "half_up", "decimal_places": 2,
            },
        },
        {
            "id": "AS-YOY-report",
            "claim_id": "L-YOY",
            "basis": "report",
            "effect": "supports",
            "depends_on_assessment_ids": ["AS-TOTAL-report"],
            "operand_bindings": [
                {
                    "slot": "decisive_operands/0",
                    "origin": {
                        "kind": "assessment_result",
                        "assessment_id": "AS-TOTAL-report",
                        "field": "calculation.result",
                    },
                },
                {
                    "slot": "decisive_operands/1",
                    "origin": {
                        "kind": "report_occurrence", "occurrence_id": "INV-PRIOR",
                    },
                },
            ],
            "calculation": {
                "expression": "(367290.32 - 350490.34) / 367290.32 * 100",
                "result": "4.574032879496728%",
            },
            "numeric_comparison": {
                "mode": "rounded", "rounding": "half_up", "decimal_places": 1,
            },
        },
        {
            "id": "AS-YOY-q3",
            "claim_id": "L-YOY",
            "basis": "evidence",
            "effect": "supports",
            "source_id": "q3-analytics",
            "depends_on_assessment_ids": [],
            "operand_bindings": [{
                "slot": "decisive_operands/0",
                "origin": {
                    "kind": "source_receipt",
                    "source_id": "q3-analytics",
                    "receipt": {"pointer": "/revenue_yoy", "value": 4.6},
                },
            }],
            "population_alignment": {
                "status": "same_population",
                "reason": (
                    "The coordinator links the report week to the exact source period."
                ),
                "links": [{
                    "requirement_id": "POP-L-YOY-period",
                    "dimension": "report_period",
                    "report_quote": "Week ending 2026-04-04.",
                    "source_receipt": {
                        "pointer": "/period", "value": "2026-04-04",
                    },
                }],
            },
        },
    ]

    source_consideration = [
        {
            "source_id": "q3-analytics",
            "claim_id": "L-TOTAL",
            "coordinator_decision": "exclude",
            "coordinator_reason": (
                "The approved source does not contain the report's displayed segment totals."
            ),
            "verifier_decision": "exclude",
            "verifier_reason": (
                "No retained source value addresses the displayed total arithmetic."
            ),
            "assessment_ids": [],
        },
        {
            "source_id": "q3-analytics",
            "claim_id": "L-YOY",
            "coordinator_decision": "consider",
            "coordinator_reason": (
                "The approved source contains a year-over-year revenue value for review."
            ),
            "verifier_decision": "used",
            "verifier_reason": (
                "The exact retained value and period receipt address this canonical claim."
            ),
            "assessment_ids": ["AS-YOY-q3"],
        },
    ]
    resolutions = [
        {
            "claim_id": "L-TOTAL",
            "assessment_ids": ["AS-TOTAL-report"],
            "state": "contradicted",
            "final_verdict": "contradicted",
            "reason": (
                "The two displayed segment values sum to a different current total."
            ),
            "required_action_kind": "correct_report",
        },
        {
            "claim_id": "L-YOY",
            "assessment_ids": ["AS-YOY-report", "AS-YOY-q3"],
            "state": "supported",
            "final_verdict": "confirmed",
            "reason": (
                "Both accepted assessments support the displayed year-over-year rate."
            ),
            "required_action_kind": "review_before_share",
        },
    ]
    correction = (
        "Both the Revenue KPI tile and the segment table Total row repeat "
        "$359,490.34, and both must change to $350,490.34."
    )
    checks = [
        {
            "id": "C-TOTAL",
            "claim_id": "L-TOTAL",
            "type": "arithmetic",
            "basis": "report",
            "verdict": "contradicted",
            "importance": "material",
            "severity": "high",
            "addressed_clause_ids": ["P-main:CL-KPI", "P-main:CL-TOTAL"],
            "assessment_ids": ["AS-TOTAL-report"],
            "report_quote": "$359,490.34",
            "correction_notice": {
                "statement": correction,
                "report_value": "$359,490.34",
                "replacement_value": "$350,490.34",
                "locations": ["Revenue KPI tile", "segment table Total row"],
            },
            "public_receipt": {
                "report_operand": {
                    "label": "Total weekly revenue",
                    "value": "$359,490.34",
                    "location": "Revenue KPI tile and segment table Total row",
                },
                "decisive_operands": [
                    {
                        "label": "Segment Alpha revenue",
                        "value": "$218,385.67",
                        "location": "segment table, Segment Alpha row",
                    },
                    {
                        "label": "Segment Beta revenue",
                        "value": "$132,104.67",
                        "location": "segment table, Segment Beta row",
                    },
                ],
                "calculation": {
                    "expression": "218385.67 + 132104.67",
                    "result": "$350,490.34",
                },
                "explanation": (
                    correction
                    + " The two displayed segment values provide the exact replacement."
                ),
            },
        },
        {
            "id": "C-YOY",
            "claim_id": "L-YOY",
            "type": "semantic",
            "basis": "evidence",
            "verdict": "confirmed",
            "importance": "material",
            "severity": None,
            "addressed_clause_ids": ["P-main:CL-YOY"],
            "assessment_ids": ["AS-YOY-report", "AS-YOY-q3"],
            "report_quote": "Revenue is down 4.6% against the same week last year.",
            "evidence_json": [
                {"pointer": "/period", "value": "2026-04-04"},
                {"pointer": "/revenue_yoy", "value": 4.6},
            ],
            "public_receipt": {
                "report_operand": {
                    "label": "Year-over-year weekly revenue change",
                    "value": "4.6%",
                    "location": "weekly revenue narrative",
                },
                "decisive_operands": [{
                    "label": "Warehouse year-over-year revenue change",
                    "value": 4.6,
                    "location": "Warehouse analytics extract, weekly revenue field",
                }],
                "explanation": (
                    "The retained weekly revenue value supports the displayed report rate."
                ),
                "source_id": "q3-analytics",
            },
        },
    ]
    presentation = {
        "summary": (
            "The accepted checks identify one total correction and one supported rate."
        ),
        "check_ids": ["C-TOTAL", "C-YOY"],
        "actions": [
            {
                "id": "A1",
                "kind": "correct_report",
                "text": correction,
                "report_quote": "$359,490.34",
                "check_ids": ["C-TOTAL"],
                "resolution_ids": ["L-TOTAL"],
            },
            {
                "id": "A2",
                "kind": "review_before_share",
                "text": (
                    "Review the supported year-over-year receipt before sharing this report."
                ),
                "report_quote": (
                    "Revenue is down 4.6% against the same week last year."
                ),
                "check_ids": ["C-YOY"],
                "resolution_ids": ["L-TOTAL", "L-YOY"],
            },
        ],
        "limits": [],
    }
    partition_result = coordinator["partition_results"][0]
    report_metadata = {"report_period": "Week ending 2026-04-04"}
    role_specs = [
        (
            "RR-claim", "claim_taker", "claim_taking",
            {
                "partition_id": "P-main",
                "visible_text": report_text,
                "inventory": inventory,
                "report_metadata": report_metadata,
            },
            partition_result,
        ),
        (
            "RR-plan", "coordinator", "coordinator_semantic_plan",
            {
                "partition_results": [partition_result],
                "inventory": inventory,
                "report_metadata": report_metadata,
                "internal_candidates": [],
                "approved_source_manifest": [source],
            },
            {
                "classification_reviews": coordinator["classification_reviews"],
                "canonical_claims": claims,
                "source_consideration_plan": coordinator[
                    "source_consideration_plan"],
                "claim_dependencies": coordinator["claim_dependencies"],
                "verifier_assignments": coordinator["verifier_assignments"],
            },
        ),
        (
            "RR-total", "evidence_verifier", "dependency_ordered_verification",
            {
                "canonical_claims": [claims[0]],
                "relevant_report_text": report_text,
                "assigned_sources": [],
                "source_consideration_plan": [
                    coordinator["source_consideration_plan"][0]],
                "accepted_upstream_assessment_results": [],
            },
            {
                "assessments": [assessments[0]],
                "source_consideration_results": [source_consideration[0]],
                "proposed_resolutions": [resolutions[0]],
                "checks": [checks[0]],
            },
        ),
        (
            "RR-yoy", "evidence_verifier", "dependency_ordered_verification",
            {
                "canonical_claims": [claims[1]],
                "relevant_report_text": report_text,
                "assigned_sources": [source],
                "source_consideration_plan": [
                    coordinator["source_consideration_plan"][1]],
                "accepted_upstream_assessment_results": [{
                    "assessment_id": "AS-TOTAL-report",
                    "field": "calculation.result",
                    "value": "$350,490.34",
                }],
            },
            {
                "assessments": assessments[1:],
                "source_consideration_results": [source_consideration[1]],
                "proposed_resolutions": [resolutions[1]],
                "checks": [checks[1]],
            },
        ),
        (
            "RR-resolution", "coordinator", "coordinator_global_resolution",
            {
                "canonical_claims": claims,
                "assessments": assessments,
                "source_consideration_results": source_consideration,
                "claim_dependencies": coordinator["claim_dependencies"],
            },
            {
                "sources": [source],
                "source_consideration": source_consideration,
                "whole_source_exclusions": [],
                "assessments": assessments,
                "resolutions": resolutions,
                "checks": checks,
                "presentation": presentation,
            },
        ),
    ]
    role_runs = []
    for role_id, role, stage, input_payload, output_payload in role_specs:
        input_row = _role_file(
            root, f"role-inputs/{role_id}.json",
            {
                "contract_version": WORKFLOW_VERSION,
                "role": role,
                "stage": stage,
                **input_payload,
            },
        )
        output_row = _role_file(
            root, f"role-outputs/{role_id}.json",
            {
                "contract_version": WORKFLOW_VERSION,
                "role": role,
                "stage": stage,
                "status": "complete",
                **output_payload,
            },
        )
        allowed_reads = [input_row["path"]]
        if stage == "dependency_ordered_verification":
            allowed_reads.extend(
                str(source_row["evidence_file"])
                for source_row in input_payload["assigned_sources"]
            )
        role_runs.append({
            "id": role_id,
            "role": role,
            "stage": stage,
            "input_bundle": input_row,
            "output_bundle": output_row,
            "allowed_read_paths": list(allowed_reads),
            "observed_read_paths": list(allowed_reads),
        })
    claims_doc = {
        "contract_version": WORKFLOW_VERSION,
        "report_period": "Week ending 2026-04-04",
        "claims": claims,
        "coordinator": coordinator,
    }
    checks_doc = {
        "contract_version": WORKFLOW_VERSION,
        "sources": [source],
        "source_consideration": source_consideration,
        "whole_source_exclusions": [],
        "assessments": assessments,
        "resolutions": resolutions,
        "checks": checks,
        "presentation": presentation,
        "role_provenance": {
            "route": "native_subagents",
            "runs": role_runs,
        },
    }
    return {
        "text": report_text,
        "sandbox": root,
        "proposed": checks,
        "checks_doc": checks_doc,
        "proposed_claims": claims,
        "claims_meta": {
            "contract_version": WORKFLOW_VERSION,
            "report_period": "Week ending 2026-04-04",
            "coordinator": coordinator,
        },
        "inventory": inventory,
        "report_path": report,
        "bundle_root": root,
        "arithmetic_uses": [],
        "claims_doc": claims_doc,
    }


def clone(case: dict) -> dict:
    """Deep-copy mutable bundle state while retaining pathlib values."""
    return copy.deepcopy(case)
