"""Public evidence, arithmetic, coverage, and temporal receipt behavior."""
from __future__ import annotations

import pathlib
import sys
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "verify" / "scripts"
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(SCRIPTS))

from test_verify_render import (  # noqa: E402
    accepted_check,
    make_artifact,
    render,
    retained_source,
)
import artifact_audit  # noqa: E402


def int9_check() -> dict:
    check = accepted_check(9, "contradicted", basis="report")
    check["type"] = "arithmetic"
    check["public_receipt"] = {
        "report_operand": {
            "label": "Reported gross margin improvement",
            "value": "3%",
            "location": "Weekly Margin sheet, gross margin note",
        },
        "decisive_operands": [
            {
                "label": "Prior-week gross margin",
                "value": "40.0%",
                "location": "Weekly Margin sheet, prior-week margin",
            },
            {
                "label": "Current-week gross margin",
                "value": "43.0%",
                "location": "Weekly Margin sheet, current-week margin",
            },
        ],
        "calculation": {
            "expression": "43 - 40",
            "result": "3 percentage points",
        },
        "explanation": (
            "Gross margin rose from 40.0% to 43.0%, which is a three-percentage-point increase."
        ),
    }
    return check


class ArithmeticReceiptTests(unittest.TestCase):
    def test_int9_uses_percentage_points_and_scores_one_of_nine(self) -> None:
        checks = [accepted_check(index) for index in range(1, 9)] + [int9_check()]
        artifact = make_artifact(checks)
        page = render.html_of(artifact)
        self.assertEqual(artifact["verdict"], "fix_first")
        self.assertAlmostEqual(artifact["score"]["value"], 100.0 / 9, places=12)
        self.assertEqual(artifact["evidence_coverage"]["contradicted"], 1)
        for text in (
            "Reported gross margin improvement",
            "40.0%",
            "43.0%",
            "43 - 40 = 3 percentage points",
            "three-percentage-point increase",
        ):
            self.assertIn(text, page)
        self.assertNotIn("3 percent increase", page.lower())
        self.assertEqual(artifact_audit.audit_public_artifact(artifact, page), [])

    def test_bad_int9_calculation_is_rejected_by_artifact_audit(self) -> None:
        artifact = make_artifact([int9_check()])
        artifact["evidence_checks"][0]["public_receipt"]["calculation"]["result"] = (
            "11 percentage points"
        )
        page = render.html_of(artifact)
        problems = artifact_audit.audit_public_artifact(artifact, page)
        self.assertTrue(any("calculation result" in problem for problem in problems))


class EvidenceAndCoverageTests(unittest.TestCase):
    def test_confirmed_card_exposes_agent_operands_not_a_verdict_stamp(self) -> None:
        check = accepted_check(1)
        check["public_receipt"] = {
            "report_operand": {
                "label": "Reported active projects",
                "value": 12,
                "location": "Weekly status summary, active-project count",
            },
            "decisive_operands": [{
                "label": "Recorded active projects",
                "value": 12,
                "location": "Project status snapshot, active-project field",
            }],
            "explanation": (
                "The retained project snapshot records the same 12 active projects shown in the report."
            ),
            "source_id": "status-snapshot",
        }
        artifact = make_artifact([check])
        page = render.html_of(artifact)
        for text in (
            "Reported active projects",
            "Recorded active projects",
            "Project status snapshot, active-project field",
            check["public_receipt"]["explanation"],
        ):
            self.assertIn(text, page)
        self.assertNotIn("The report claim", page)

    def test_supporting_provenance_stays_outside_material_totals_and_score(self) -> None:
        artifact = make_artifact([accepted_check(1)], supporting=True)
        coverage = artifact["evidence_coverage"]
        self.assertEqual(coverage["document_claims_total"], 1)
        self.assertEqual(coverage["supporting_claims_reviewed"], 1)
        self.assertEqual(coverage["confirmed"], 1)
        self.assertEqual(artifact["score"]["value"], 0.0)

    def test_temporal_card_preserves_dates_values_and_source_enum_only(self) -> None:
        check = accepted_check(1, "changed_since_report")
        artifact = make_artifact([check], sources=[retained_source()])
        page = render.html_of(artifact)
        for text in (
            "2026-04-04",
            "2026-08-23",
            "Later recorded metric 1",
            "supplied_file",
            check["public_receipt"]["reconstruction_attempt"],
        ):
            self.assertIn(text, page)
        self.assertEqual(
            artifact["verification"]["live_source"],
            {"status": "not_run", "detail": None},
        )
        self.assertNotIn("Supplied recorded evidence", page)
        self.assertNotIn("Actual live query", page)

    def test_not_checkable_still_renders_its_agent_authored_receipt(self) -> None:
        check = accepted_check(1, "not_checkable")
        artifact = make_artifact([check])
        page = render.html_of(artifact)
        self.assertEqual(
            artifact["evidence_checks"][0]["public_receipt"],
            check["public_receipt"],
        )
        self.assertIn(check["public_receipt"]["explanation"], page)
        self.assertEqual(check["public_receipt"]["decisive_operands"], [])


if __name__ == "__main__":
    unittest.main()
