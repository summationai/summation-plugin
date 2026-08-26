"""Focused behavior tests for the explicit coordinator handoff."""
from __future__ import annotations

import copy
import importlib.util
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "verify" / "scripts" / "accept.py"


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
            {"partition_id": "kpi", "candidate_id": "K1"},
            {"partition_id": "table", "candidate_id": "T1"},
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
                }],
            },
        ],
        "membership": [
            {
                "partition_id": "kpi",
                "candidate_id": "K1",
                "canonical_claim_id": "L-TOTAL",
            },
            {
                "partition_id": "table",
                "candidate_id": "T1",
                "canonical_claim_id": "L-TOTAL",
            },
        ],
        "verifier_assignments": [{
            "verifier_id": "revenue-checker",
            "claim_ids": ["L-TOTAL"],
        }],
    }


class CoordinatorContractTests(unittest.TestCase):
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
        row["partition_results"][0]["candidates"][0]["public_label"] = "row 2"
        _handoff, problems = accept.validate_coordinator_handoff(
            claims(), row, inventory())
        self.assertIn(
            "worker candidate 'kpi'/'K1' public_label is vague",
            problems,
        )

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
