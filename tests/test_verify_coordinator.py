"""Focused coordinator-v6 handoff and preflight contract tests."""
from __future__ import annotations

import copy
import importlib.util
import json
import pathlib
import tempfile
import unittest

from tests.verify_v6_case import build_case


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
            "quote": combined["claims"][0]["quote"],
            "primary_quote": combined["claims"][0]["quote"],
            "public_label": "Combined revenue narrative",
            "primary_clause_id": "narrative:CL-RATE",
            "member_clause_ids": [
                "narrative:CL-RATE", "narrative:CL-DIRECTION",
            ],
        }]
        for clause in combined["coordinator"]["partition_results"][0]["clauses"]:
            clause["public_label"] = "Combined revenue narrative"
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
        with tempfile.TemporaryDirectory() as raw:
            case = build_case(pathlib.Path(raw))
            partition = case["claims_meta"]["coordinator"]["partition_results"][0]
            partition["occurrence_decisions"][1]["clause_ids"] = []
            partition["clauses"] = [
                row for row in partition["clauses"]
                if row["occurrence_id"] != "INV-KPI"
            ]
            _handoff, problems = accept.validate_coordinator_handoff(
                case["proposed_claims"], case["claims_meta"]["coordinator"],
                case["inventory"],
            )
            self.assertIn(
                "claim-taker decision for occurrence 'INV-KPI' clause_ids is missing or not a non-empty array",
                problems,
            )

    def test_repeated_assertions_merge_into_one_canonical_claim(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            case = build_case(pathlib.Path(raw))
            handoff, problems = accept.validate_coordinator_handoff(
                case["proposed_claims"], case["claims_meta"]["coordinator"],
                case["inventory"],
            )
            self.assertEqual(problems, [])
            self.assertEqual(
                handoff["material_claim_clause_ids"]["L-TOTAL"],
                ["P-main:CL-KPI", "P-main:CL-TOTAL"],
            )
            self.assertEqual(
                handoff["material_claim_inventory_ids"]["L-TOTAL"],
                ["INV-KPI", "INV-TOTAL"],
            )
            self.assertEqual(sum(
                "L-TOTAL" in row["claim_ids"]
                for row in handoff["verifier_assignments"]
            ), 1)

    def test_candidate_membership_is_complete_and_unique(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = pathlib.Path(raw)

            omitted = build_case(root)
            omitted["proposed_claims"][0]["member_clause_ids"].pop()

            duplicate = build_case(root)
            duplicate["proposed_claims"][0]["member_clause_ids"].append(
                "P-main:CL-KPI")

            unknown = build_case(root)
            unknown["proposed_claims"][0]["member_clause_ids"][0] = (
                "P-main:CL-UNKNOWN")

            split = build_case(root)
            alias = copy.deepcopy(split["proposed_claims"][0])
            alias["id"] = "L-SECOND"
            alias["primary_clause_id"] = "P-main:CL-TOTAL"
            alias["member_clause_ids"] = ["P-main:CL-TOTAL"]
            alias["occurrence_ids"] = ["INV-TOTAL"]
            alias["inventory_ids"] = ["INV-TOTAL"]
            split["proposed_claims"].append(alias)

            for label, case in {
                "omitted": omitted,
                "duplicate": duplicate,
                "unknown clause": unknown,
                "split": split,
            }.items():
                with self.subTest(label=label):
                    _handoff, problems = accept.validate_coordinator_handoff(
                        case["proposed_claims"],
                        case["claims_meta"]["coordinator"],
                        case["inventory"],
                    )
                    self.assertTrue(problems)

    def test_verifier_assignments_cover_each_material_claim_once(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            case = build_case(pathlib.Path(raw))
            case["claims_meta"]["coordinator"]["verifier_assignments"].append({
                "verifier_id": "second-checker",
                "claim_ids": ["L-TOTAL"],
            })
            _handoff, problems = accept.validate_coordinator_handoff(
                case["proposed_claims"], case["claims_meta"]["coordinator"],
                case["inventory"],
            )
            self.assertIn(
                "canonical material claim 'L-TOTAL' is assigned to more than one verifier",
                problems,
            )

    def test_claim_taker_public_label_is_wired_through_canonical_claim(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            case = build_case(pathlib.Path(raw))
            case["proposed_claims"][0]["public_label"] = (
                "Coordinator-authored replacement label")
            _handoff, problems = accept.validate_coordinator_handoff(
                case["proposed_claims"], case["claims_meta"]["coordinator"],
                case["inventory"],
            )
            self.assertIn(
                "canonical claim 'L-TOTAL' public_label is not carried from its primary clause",
                problems,
            )

    def test_missing_clause_label_and_decision_reason_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            case = build_case(pathlib.Path(raw))
            clause = case["claims_meta"]["coordinator"]["partition_results"][0][
                "clauses"][0]
            clause["public_label"] = ""
            case["proposed_claims"][0]["public_label"] = ""
            decision = case["claims_meta"]["coordinator"]["partition_results"][0][
                "occurrence_decisions"][0]
            decision["reason"] = ""
            _handoff, problems = accept.validate_coordinator_handoff(
                case["proposed_claims"], case["claims_meta"]["coordinator"],
                case["inventory"],
            )
            self.assertIn(
                "material clause 'P-main:CL-KPI' public_label is missing",
                problems,
            )
            self.assertIn(
                "claim-taker decision for occurrence 'INV-PERIOD' reason is missing or not substantive",
                problems,
            )

    def test_canonical_supporting_provenance_requires_a_substantive_reason(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            case = build_case(pathlib.Path(raw))
            coordinator = case["claims_meta"]["coordinator"]
            decision = next(
                row for row in coordinator["partition_results"][0][
                    "occurrence_decisions"]
                if row["occurrence_id"] == "INV-SOURCE"
            )
            decision["classification"] = "supporting_provenance"
            decision["analytical_role"] = "supporting_provenance"
            review = next(
                row for row in coordinator["classification_reviews"]
                if row["occurrence_id"] == "INV-SOURCE"
            )
            review["proposed_classification"] = "supporting_provenance"
            review["final_classification"] = "supporting_provenance"
            review["analytical_role"] = "supporting_provenance"
            case["proposed_claims"].append({
                "id": "S-SOURCE",
                "quote": "Source: weekly report.",
                "public_label": "Weekly report source",
                "importance": "supporting",
                "classification": "supporting_provenance",
                "occurrence_ids": ["INV-SOURCE"],
                "inventory_ids": ["INV-SOURCE"],
            })
            _handoff, problems = accept.validate_coordinator_handoff(
                case["proposed_claims"], coordinator, case["inventory"])
            self.assertIn(
                "canonical claim 'S-SOURCE' supporting_provenance reason is missing or not substantive",
                problems,
            )
            case["proposed_claims"][-1]["reason"] = (
                "This canonical record retains the host-declared provenance context."
            )
            _handoff, problems = accept.validate_coordinator_handoff(
                case["proposed_claims"], coordinator, case["inventory"])
            self.assertEqual(problems, [])

    def test_preflight_returns_exact_numeric_calculation_repair_reason(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            case = build_case(pathlib.Path(raw))
            case["proposed"][0]["public_receipt"]["calculation"]["result"] = (
                "1 project")
            _handoff, problems = accept.coordinator_preflight(
                case["proposed_claims"], case["claims_meta"]["coordinator"],
                case["inventory"], case["proposed"],
            )
            self.assertIn(
                "evidence-verifier check 'C-TOTAL' public_receipt.calculation.result is not a public numeric value",
                problems,
            )
            case["proposed"][0]["public_receipt"]["calculation"]["result"] = (
                "$350,490.34")
            _handoff, problems = accept.coordinator_preflight(
                case["proposed_claims"], case["claims_meta"]["coordinator"],
                case["inventory"], case["proposed"],
            )
            self.assertEqual(problems, [])

    def test_repeated_contradicted_occurrences_require_one_exact_correction_statement(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            case = build_case(pathlib.Path(raw))
            check = case["proposed"][0]
            statement = check["correction_notice"]["statement"]
            del check["correction_notice"]
            _handoff, problems = accept.coordinator_preflight(
                case["proposed_claims"], case["claims_meta"]["coordinator"],
                case["inventory"], case["proposed"],
            )
            self.assertIn(
                "evidence-verifier check 'C-TOTAL' correction_notice is missing or not an object",
                problems,
            )

            case = build_case(pathlib.Path(raw))
            check = case["proposed"][0]
            check["public_receipt"]["explanation"] = (
                "The displayed operands recompute the total exactly.")
            _handoff, problems = accept.coordinator_preflight(
                case["proposed_claims"], case["claims_meta"]["coordinator"],
                case["inventory"], case["proposed"],
            )
            self.assertIn(
                "evidence-verifier check 'C-TOTAL' correction_notice.statement is not copied into public_receipt.explanation",
                problems,
            )

            case = build_case(pathlib.Path(raw))
            case["checks_doc"]["presentation"]["actions"][0]["text"] = (
                "Correct the displayed total before sharing the report.")
            _handoff, problems = accept.coordinator_preflight(
                case["proposed_claims"], case["claims_meta"]["coordinator"],
                case["inventory"], case["proposed"],
                presentation_doc=case["checks_doc"],
            )
            self.assertIn(
                "presentation.actions does not include the exact correction statement for check 'C-TOTAL'",
                problems,
            )

            case["checks_doc"]["presentation"]["actions"][0]["text"] = statement
            _handoff, problems = accept.coordinator_preflight(
                case["proposed_claims"], case["claims_meta"]["coordinator"],
                case["inventory"], case["proposed"],
                presentation_doc=case["checks_doc"],
            )
            self.assertEqual(problems, [])

    def test_explicit_structural_title_cannot_become_a_canonical_card(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            case = build_case(pathlib.Path(raw))
            case["inventory"]["items"].append({
                "id": "INV-TITLE", "displayed": "Weekly Sales Snapshot",
                "quote": "Weekly Sales Snapshot", "location": "block1",
                "importance": "unclassified",
            })
            coordinator = case["claims_meta"]["coordinator"]
            coordinator["partition_results"].append({
                "partition_id": "title",
                "occurrence_decisions": [{
                    "occurrence_id": "INV-TITLE",
                    "classification": "structural_context",
                    "analytical_role": "structural_context",
                    "reason": "The host classifies this occurrence as structural context.",
                    "clause_ids": [],
                }],
                "clauses": [],
            })
            coordinator["classification_reviews"].append({
                "occurrence_id": "INV-TITLE",
                "claim_taker_partition_id": "title",
                "proposed_classification": "structural_context",
                "final_classification": "structural_context",
                "analytical_role": "structural_context",
                "decision": "accept",
                "reason": "The coordinator accepts the explicit structural classification.",
                "accepted_clause_ids": [],
            })
            case["proposed_claims"].append({
                "id": "L-TITLE", "quote": "Weekly Sales Snapshot",
                "primary_quote": "Weekly Sales Snapshot",
                "public_label": "Weekly Sales Snapshot", "importance": "material",
                "classification": "material_claim",
                "primary_clause_id": "title:CL1",
                "member_clause_ids": ["title:CL1"],
                "occurrence_ids": ["INV-TITLE"],
                "inventory_ids": ["INV-TITLE"],
                "context_occurrence_ids": [],
                "population_requirements": [],
            })
            coordinator["verifier_assignments"].append({
                "verifier_id": "title-verifier", "claim_ids": ["L-TITLE"],
            })
            _handoff, problems = accept.validate_coordinator_handoff(
                case["proposed_claims"], coordinator, case["inventory"])
            self.assertIn(
                "canonical claim 'L-TITLE' references unknown material clause 'title:CL1'",
                problems,
            )

    def test_title_restatement_fails_claim_reconciliation(self) -> None:
        """A host-raised classification challenge blocks canonical acceptance."""
        with tempfile.TemporaryDirectory() as raw:
            case = build_case(pathlib.Path(raw))
            shown = "Weekly Sales Snapshot"
            case["inventory"]["items"].append({
                "id": "INV-TITLE", "displayed": shown, "quote": shown,
                "location": "block1", "importance": "unclassified",
            })
            coordinator = case["claims_meta"]["coordinator"]
            coordinator["partition_results"].append({
                "partition_id": "title",
                "occurrence_decisions": [{
                    "occurrence_id": "INV-TITLE",
                    "classification": "material_claim",
                    "analytical_role": "load_bearing_analytical_assertion",
                    "reason": "The claim-taker proposes this occurrence for semantic review.",
                    "clause_ids": ["title:CL1"],
                }],
                "clauses": [{
                    "id": "title:CL1", "occurrence_id": "INV-TITLE",
                    "span": {"start": 0, "end": len(shown)}, "quote": shown,
                    "public_label": "Weekly Sales Snapshot",
                    "context_occurrence_ids": [],
                }],
            })
            coordinator["classification_reviews"].append({
                "occurrence_id": "INV-TITLE",
                "claim_taker_partition_id": "title",
                "proposed_classification": "material_claim",
                "final_classification": "material_claim",
                "analytical_role": "load_bearing_analytical_assertion",
                "decision": "challenge",
                "reason": "The coordinator requires the claim-taker to reconsider this classification.",
                "accepted_clause_ids": ["title:CL1"],
            })
            case["proposed_claims"].append({
                "id": "L-TITLE", "quote": shown, "primary_quote": shown,
                "public_label": "Weekly Sales Snapshot", "importance": "material",
                "classification": "material_claim",
                "primary_clause_id": "title:CL1",
                "member_clause_ids": ["title:CL1"],
                "occurrence_ids": ["INV-TITLE"],
                "inventory_ids": ["INV-TITLE"],
                "context_occurrence_ids": [],
                "population_requirements": [],
            })
            coordinator["verifier_assignments"].append({
                "verifier_id": "title-verifier", "claim_ids": ["L-TITLE"],
            })
            _handoff, problems = accept.validate_coordinator_handoff(
                case["proposed_claims"], coordinator, case["inventory"])
            self.assertIn(
                "coordinator classification review for occurrence 'INV-TITLE' is an unresolved challenge",
                problems,
            )


if __name__ == "__main__":
    unittest.main()
