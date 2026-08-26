"""Focused behavior tests for the explicit coordinator handoff."""
from __future__ import annotations

import copy
import importlib.util
import json
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "verify" / "scripts" / "accept.py"
COMPOUND_FIXTURE = ROOT / "tests" / "fixtures" / "verify" / "compound-claim-handoff.json"


def load_accept():
    spec = importlib.util.spec_from_file_location("verify_accept_coordinator", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


accept = load_accept()


def inventory() -> dict:
    return {
        "complete": True,
        "items": [
            {
                "id": "INV-KPI",
                "displayed": "Revenue $359,490.34",
                "quote": "Revenue $359,490.34",
                "location": "block2",
                "importance": "unclassified",
            },
            {
                "id": "INV-TOTAL",
                "displayed": "$359,490.34",
                "quote": "$359,490.34",
                "location": "table1/r4/c2",
                "importance": "unclassified",
            },
        ],
    }


def claims() -> list[dict]:
    return [{
        "id": "L-TOTAL",
        "quote": "Revenue $359,490.34",
        "public_label": "Total weekly revenue",
        "importance": "material",
        "classification": "material_claim",
        "inventory_ids": ["INV-KPI", "INV-TOTAL"],
        "member_refs": [
            {"partition_id": "kpi", "candidate_id": "K1", "clause_id": "TOTAL"},
            {"partition_id": "table", "candidate_id": "T1", "clause_id": "TOTAL"},
        ],
    }]


def coordinator() -> dict:
    return {
        "partition_results": [
            {
                "partition_id": "kpi",
                "candidates": [{
                    "id": "K1",
                    "quote": "Revenue $359,490.34",
                    "public_label": "Total weekly revenue",
                    "importance": "material",
                    "classification": "material_claim",
                    "inventory_ids": ["INV-KPI"],
                    "clauses": [{
                        "id": "TOTAL", "quote": "Revenue $359,490.34",
                        "public_label": "Total weekly revenue",
                    }],
                }],
            },
            {
                "partition_id": "table",
                "candidates": [{
                    "id": "T1",
                    "quote": "$359,490.34",
                    "public_label": "Segment table Total revenue",
                    "importance": "material",
                    "classification": "material_claim",
                    "inventory_ids": ["INV-TOTAL"],
                    "clauses": [{
                        "id": "TOTAL", "quote": "$359,490.34",
                        "public_label": "Segment table Total revenue",
                    }],
                }],
            },
        ],
        "membership": [
            {
                "partition_id": "kpi",
                "candidate_id": "K1",
                "clause_id": "TOTAL",
                "canonical_claim_id": "L-TOTAL",
            },
            {
                "partition_id": "table",
                "candidate_id": "T1",
                "clause_id": "TOTAL",
                "canonical_claim_id": "L-TOTAL",
            },
        ],
        "verifier_assignments": [{
            "verifier_id": "revenue-checker",
            "claim_ids": ["L-TOTAL"],
        }],
    }


class CoordinatorContractTests(unittest.TestCase):
    def test_compound_fixture_splits_independently_verifiable_clauses(self) -> None:
        fixture = json.loads(COMPOUND_FIXTURE.read_text())
        handoff, problems = accept.coordinator_preflight(
            fixture["claims"], fixture["coordinator"],
            fixture["inventory"], fixture["checks"],
        )
        self.assertEqual(problems, [])
        self.assertEqual(handoff["material_claim_ids"], ["L-RATE", "L-DIRECTION"])
        self.assertEqual(
            [row["claim_id"] for row in fixture["checks"]],
            ["L-RATE", "L-DIRECTION"],
        )

    def test_compound_clause_claims_share_one_raw_occurrence_without_duplicate_consumption(self) -> None:
        fixture = json.loads(COMPOUND_FIXTURE.read_text())
        handoff, problems = accept.coordinator_preflight(
            fixture["claims"], fixture["coordinator"],
            fixture["inventory"], fixture["checks"],
        )
        self.assertEqual(problems, [])
        report = fixture["inventory"]["items"][0]["displayed"]
        grounded, discarded = accept.validate_claims(report, fixture["claims"])
        self.assertEqual(discarded, [])
        ledger = accept.attach_claim_outcomes(grounded, fixture["checks"])
        discarded_claims: list[dict] = []
        ledger = accept.apply_host_classifications(
            ledger, discarded_claims, fixture["inventory"],
            material_inventory_claim_ids=handoff["material_inventory_claim_ids"],
        )
        self.assertEqual(discarded_claims, [])
        self.assertEqual([row["id"] for row in ledger], ["L-RATE", "L-DIRECTION"])
        covered = accept.cover(
            fixture["inventory"], ledger,
            material_inventory_claim_ids=handoff["material_inventory_claim_ids"],
        )
        self.assertEqual(covered["missing"], [])
        self.assertEqual(covered["material"], 1)
        self.assertEqual(covered["completed"], 1)

    def test_one_receipt_must_address_every_clause_of_its_canonical_claim(self) -> None:
        fixture = json.loads(COMPOUND_FIXTURE.read_text())
        combined = copy.deepcopy(fixture)
        combined["claims"] = [{
            **combined["claims"][0],
            "id": "L-COMBINED",
            "quote": combined["inventory"]["items"][0]["displayed"],
            "public_label": "Combined revenue narrative",
            "member_refs": [
                {
                    "partition_id": "narrative", "candidate_id": "N1",
                    "clause_id": "CL-RATE",
                },
                {
                    "partition_id": "narrative", "candidate_id": "N1",
                    "clause_id": "CL-DIRECTION",
                },
            ],
        }]
        for clause in combined["coordinator"]["partition_results"][0]["candidates"][0]["clauses"]:
            clause["public_label"] = "Combined revenue narrative"
        for row in combined["coordinator"]["membership"]:
            row["canonical_claim_id"] = "L-COMBINED"
        combined["coordinator"]["verifier_assignments"][0]["claim_ids"] = ["L-COMBINED"]
        check = combined["checks"][0]
        check["claim_id"] = "L-COMBINED"
        _handoff, problems = accept.coordinator_preflight(
            combined["claims"], combined["coordinator"],
            combined["inventory"], [check],
        )
        self.assertEqual(problems, [
            "evidence-verifier check 'C-RATE' does not address every clause "
            "of canonical claim 'L-COMBINED'",
        ])

    def test_material_candidate_without_explicit_clauses_fails_preflight(self) -> None:
        row = coordinator()
        del row["partition_results"][0]["candidates"][0]["clauses"]
        _handoff, problems = accept.validate_coordinator_handoff(
            claims(), row, inventory())
        self.assertIn(
            "worker candidate 'kpi'/'K1' clauses is missing or not a non-empty array",
            problems,
        )

    def test_repeated_assertions_merge_into_one_canonical_claim(self) -> None:
        handoff, problems = accept.validate_coordinator_handoff(
            claims(), coordinator(), inventory())
        self.assertEqual(problems, [])
        self.assertEqual(handoff["material_claim_ids"], ["L-TOTAL"])
        self.assertEqual(handoff["verifier_assignments"], [{
            "verifier_id": "revenue-checker",
            "claim_ids": ["L-TOTAL"],
        }])
        self.assertEqual(handoff["membership"], coordinator()["membership"])
        self.assertEqual(handoff["structural_context"], [])

    def test_candidate_membership_is_complete_and_unique(self) -> None:
        cases = {}

        omitted = coordinator()
        omitted["membership"].pop()
        cases["omitted"] = omitted

        duplicate = coordinator()
        duplicate["membership"].append(copy.deepcopy(duplicate["membership"][0]))
        cases["duplicate"] = duplicate

        unknown_canonical = coordinator()
        unknown_canonical["membership"][0]["canonical_claim_id"] = "L-UNKNOWN"
        cases["unknown canonical"] = unknown_canonical

        split = coordinator()
        split["membership"].append({
            "partition_id": "kpi",
            "candidate_id": "K1",
            "canonical_claim_id": "L-SECOND",
        })
        cases["split"] = split

        for label, row in cases.items():
            with self.subTest(label=label):
                _handoff, problems = accept.validate_coordinator_handoff(
                    claims(), row, inventory())
                self.assertTrue(problems)

    def test_verifier_assignments_cover_each_material_claim_once(self) -> None:
        row = coordinator()
        row["verifier_assignments"].append({
            "verifier_id": "second-checker",
            "claim_ids": ["L-TOTAL"],
        })
        _handoff, problems = accept.validate_coordinator_handoff(
            claims(), row, inventory())
        self.assertIn(
            "canonical material claim 'L-TOTAL' is assigned to more than one verifier",
            problems,
        )

    def test_claim_taker_public_label_is_wired_through_canonical_claim(self) -> None:
        row = claims()
        row[0]["public_label"] = "Coordinator-invented revenue label"
        _handoff, problems = accept.validate_coordinator_handoff(
            row, coordinator(), inventory())
        self.assertIn(
            "canonical claim 'L-TOTAL' public_label is not carried from a member candidate",
            problems,
        )

    def test_worker_candidate_label_and_supporting_reason_fail_closed(self) -> None:
        row = coordinator()
        row["partition_results"][0]["candidates"][0]["clauses"][0][
            "public_label"] = "row 2"
        _handoff, problems = accept.validate_coordinator_handoff(
            claims(), row, inventory())
        self.assertIn(
            "worker candidate 'kpi'/'K1' clauses[0].public_label is vague",
            problems,
        )

    def test_canonical_supporting_provenance_requires_a_substantive_reason(self) -> None:
        inv = inventory()
        inv["items"] = [inv["items"][0]]
        row = {
            "partition_results": [{
                "partition_id": "source-note",
                "candidates": [{
                    "id": "S1",
                    "quote": "Revenue $359,490.34",
                    "public_label": "Revenue source note",
                    "importance": "supporting",
                    "classification": "supporting_provenance",
                    "reason": (
                        "This occurrence identifies provenance for the displayed "
                        "revenue value."
                    ),
                    "inventory_ids": ["INV-KPI"],
                }],
            }],
            "membership": [{
                "partition_id": "source-note",
                "candidate_id": "S1",
                "canonical_claim_id": "S-SOURCE",
            }],
            "verifier_assignments": [],
        }
        canonical = [{
            "id": "S-SOURCE",
            "quote": "Revenue $359,490.34",
            "public_label": "Revenue source note",
            "importance": "supporting",
            "classification": "supporting_provenance",
            "inventory_ids": ["INV-KPI"],
            "member_refs": [{
                "partition_id": "source-note", "candidate_id": "S1",
            }],
        }]
        _handoff, problems = accept.validate_coordinator_handoff(
            canonical, row, inv)
        self.assertIn(
            "canonical claim 'S-SOURCE' supporting_provenance reason is missing "
            "or not substantive",
            problems,
        )
        canonical[0]["reason"] = (
            "This canonical record retains the report's visible provenance context."
        )
        _handoff, problems = accept.validate_coordinator_handoff(
            canonical, row, inv)
        self.assertEqual(problems, [])

    def test_preflight_returns_exact_numeric_calculation_repair_reason(self) -> None:
        checks = [{
            "id": "C-TOTAL",
            "claim_id": "L-TOTAL",
            "addressed_clause_refs": copy.deepcopy(claims()[0]["member_refs"]),
            "public_receipt": {
                "calculation": {
                    "expression": "218385.67 + 132104.67",
                    "result": "1 project",
                },
            },
        }]
        _handoff, problems = accept.coordinator_preflight(
            claims(), coordinator(), inventory(), checks)
        self.assertEqual(problems, [
            "evidence-verifier check 'C-TOTAL' "
            "public_receipt.calculation.result is not a public numeric value",
        ])
        checks[0]["public_receipt"]["calculation"]["result"] = "$350,490.34"
        _handoff, problems = accept.coordinator_preflight(
            claims(), coordinator(), inventory(), checks)
        self.assertEqual(problems, [])

    def test_repeated_contradicted_occurrences_require_one_exact_correction_statement(self) -> None:
        statement = (
            "Both the Revenue KPI tile and the segment table Total row repeat "
            "$359,490.34, and both must change to $350,490.34."
        )
        check = {
            "id": "C-TOTAL",
            "claim_id": "L-TOTAL",
            "type": "arithmetic",
            "basis": "report",
            "verdict": "contradicted",
            "importance": "material",
            "addressed_clause_refs": copy.deepcopy(claims()[0]["member_refs"]),
            "public_receipt": {
                "report_operand": {
                    "label": "Total weekly revenue",
                    "value": "$359,490.34",
                    "location": "Revenue KPI tile and segment table Total row",
                },
                "decisive_operands": [
                    {"label": "Segment Alpha revenue", "value": "$218,385.67",
                     "location": "Segment table, Alpha row"},
                    {"label": "Segment Beta revenue", "value": "$132,104.67",
                     "location": "Segment table, Beta row"},
                ],
                "calculation": {
                    "expression": "218385.67 + 132104.67",
                    "result": "$350,490.34",
                },
                "explanation": "The two segment rows add to $350,490.34.",
            },
        }
        _handoff, problems = accept.coordinator_preflight(
            claims(), coordinator(), inventory(), [check])
        self.assertEqual(problems, [
            "evidence-verifier check 'C-TOTAL' correction_notice is missing or not an object",
        ])
        check["correction_notice"] = {
            "statement": statement,
            "report_value": "$359,490.34",
            "replacement_value": "$350,490.34",
            "locations": ["Revenue KPI tile", "segment table Total row"],
        }
        _handoff, problems = accept.coordinator_preflight(
            claims(), coordinator(), inventory(), [check])
        self.assertEqual(problems, [
            "evidence-verifier check 'C-TOTAL' correction_notice.statement is not "
            "copied into public_receipt.explanation",
        ])
        check["public_receipt"]["explanation"] = (
            statement + " The two segment rows provide the exact replacement."
        )
        _handoff, problems = accept.coordinator_preflight(
            claims(), coordinator(), inventory(), [check],
            presentation_doc={"presentation": {"actions": [{
                "id": "A1",
                "text": "Correct the displayed total before sharing the report.",
                "report_quote": "$359,490.34",
                "check_ids": ["C-TOTAL"],
            }]}},
        )
        self.assertEqual(problems, [
            "presentation.actions does not include the exact correction statement "
            "for check 'C-TOTAL'",
        ])
        _handoff, problems = accept.coordinator_preflight(
            claims(), coordinator(), inventory(), [check],
            presentation_doc={"presentation": {"actions": [{
                "id": "A1",
                "text": statement + " Recheck the report before sharing it.",
                "report_quote": "$359,490.34",
                "check_ids": ["C-TOTAL"],
            }]}},
        )
        self.assertEqual(problems, [])

    def test_explicit_structural_title_cannot_become_a_canonical_card(self) -> None:
        inv = inventory()
        inv["items"].append({
            "id": "INV-TITLE", "displayed": "Weekly Sales Snapshot",
            "quote": "Weekly Sales Snapshot", "location": "block1",
            "importance": "unclassified",
        })
        row = coordinator()
        row["partition_results"].append({
            "partition_id": "title",
            "candidates": [{
                "id": "H1", "quote": "Weekly Sales Snapshot",
                "importance": "supporting", "classification": "structural_context",
                "reason": "This text is the document title and contains no analytical assertion.",
                "inventory_ids": ["INV-TITLE"],
            }],
        })
        row["membership"].append({
            "partition_id": "title", "candidate_id": "H1",
            "canonical_claim_id": "L-TITLE",
        })
        row["verifier_assignments"][0]["claim_ids"].append("L-TITLE")
        proposed = claims() + [{
            "id": "L-TITLE", "quote": "Weekly Sales Snapshot",
            "public_label": "Weekly Sales Snapshot", "importance": "material",
            "classification": "material_claim", "inventory_ids": ["INV-TITLE"],
            "member_refs": [{"partition_id": "title", "candidate_id": "H1"}],
        }]
        _handoff, problems = accept.validate_coordinator_handoff(proposed, row, inv)
        self.assertIn(
            "structural worker candidate 'title'/'H1' must not name a canonical claim",
            problems,
        )
        self.assertIn(
            "canonical claim 'L-TITLE' classification does not match its members",
            problems,
        )

    def test_title_restatement_fails_claim_reconciliation(self) -> None:
        """A title cannot be restated as a material confirmation."""
        inv = inventory()
        inv["items"].append({
            "id": "INV-TITLE", "displayed": "Weekly Sales Snapshot",
            "quote": "Weekly Sales Snapshot", "location": "block1",
            "importance": "unclassified",
        })
        row = coordinator()
        row["partition_results"].append({
            "partition_id": "title",
            "candidates": [{
                "id": "H1", "quote": "Weekly Sales Snapshot",
                "importance": "supporting", "classification": "structural_context",
                "reason": "This exact occurrence is the report title and makes no assertion.",
                "inventory_ids": ["INV-TITLE"],
            }],
        })
        row["membership"].append({
            "partition_id": "title", "candidate_id": "H1",
            "canonical_claim_id": "L-TITLE",
        })
        proposed = claims() + [{
            "id": "L-TITLE", "quote": "Weekly Sales Snapshot",
            "public_label": "Weekly Sales Snapshot", "importance": "material",
            "classification": "material_claim", "inventory_ids": ["INV-TITLE"],
            "member_refs": [{"partition_id": "title", "candidate_id": "H1"}],
        }]
        _handoff, problems = accept.validate_coordinator_handoff(proposed, row, inv)
        self.assertTrue(any("structural worker candidate" in value for value in problems))
        self.assertTrue(any("classification does not match" in value for value in problems))


if __name__ == "__main__":
    unittest.main()
