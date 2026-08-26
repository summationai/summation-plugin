"""Planted weekly-sales Checkpoint 1 proofs against shipped accept and render."""
from __future__ import annotations

import html as html_lib
import pathlib
import re
import tempfile
import unittest

from tests.test_verify_render import (
    guidance_for,
    make_artifact,
    raw_for,
    render,
    retained_source,
    rounded_arithmetic_check,
)
from tests.test_verify_semantic_workflow import reasons, use_corrected_yoy_report_check, validate
from tests.verify_v6_case import build_case

from tests.test_verify_accept import accept as accept_module


CORRECTED_TOTAL = "$350,490.34"
DISPLAYED_TOTAL = "$359,490.34"
PRIOR_TOTAL = "$367,290.32"
YOY_EXACT = "4.574032879496728%"
YOY_SHOWN = "4.6%"
STALE_YOY = "2.1236552055%"


def visible_text(page: str) -> str:
    stripped = re.sub(
        r"<(?:style|script)[^>]*>.*?</(?:style|script)>",
        " ",
        page,
        flags=re.I | re.S,
    )
    return html_lib.unescape(re.sub(r"<[^>]+>", " ", stripped))


def next_block(page: str) -> str:
    match = re.search(r'<div class="next">(.*?)</div>', page, re.S)
    assert match is not None
    return visible_text(match.group(1))


class Checkpoint1PlantedWeeklySalesTests(unittest.TestCase):
    def test_declared_one_decimal_rounding_cannot_contradict_matching_yoy(self) -> None:
        receipt = {
            "label": "Year-over-year revenue decrease",
            "value": YOY_SHOWN,
        }
        calculation = {
            "expression": f"({PRIOR_TOTAL.strip('$').replace(',', '')} - "
                          f"{CORRECTED_TOTAL.strip('$').replace(',', '')}) "
                          "/ 367290.32 * 100",
            "result": YOY_EXACT,
        }
        comparison = {
            "mode": "rounded",
            "rounding": "half_up",
            "decimal_places": 1,
        }
        confirmed, problems = accept_module.validate_numeric_comparison(
            {
                "basis": "report",
                "type": "arithmetic",
                "verdict": "confirmed",
                "numeric_comparison": comparison,
            },
            receipt,
            calculation,
        )
        self.assertEqual(problems, [])
        self.assertTrue(confirmed["matches"])
        self.assertEqual(confirmed["customer_result"], YOY_SHOWN)

        rejected, problems = accept_module.validate_numeric_comparison(
            {
                "basis": "report",
                "type": "arithmetic",
                "verdict": "contradicted",
                "numeric_comparison": comparison,
            },
            receipt,
            calculation,
        )
        self.assertIsNone(rejected)
        self.assertTrue(
            any("values match under the declared numeric comparison" in item
                for item in problems)
        )

    def test_yoy_using_contradicted_displayed_total_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            case = build_case(pathlib.Path(raw))
            downstream = case["checks_doc"]["assessments"][1]
            downstream["depends_on_assessment_ids"] = []
            downstream["operand_bindings"][0]["origin"] = {
                "kind": "report_occurrence",
                "occurrence_id": "INV-KPI",
            }
            downstream["calculation"]["expression"] = (
                "(367290.32 - 359490.34) / 367290.32 * 100")
            downstream["calculation"]["result"] = STALE_YOY
            self.assertIn(
                "assessment 'AS-YOY-report' uses stale report occurrence "
                "'INV-KPI' from contradicted upstream claim 'L-TOTAL'",
                reasons(case),
            )

    def test_corrected_total_yoy_accepts_and_renders_without_false_next(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            case = build_case(pathlib.Path(raw))
            use_corrected_yoy_report_check(case)
            accepted = validate(case)
            self.assertEqual(accepted["repair_reasons"], [])
            yoy = next(row for row in accepted["checks"] if row["id"] == "C-YOY")
            self.assertEqual(yoy["verdict"], "confirmed")
            self.assertEqual(yoy["numeric_comparison"]["customer_result"], YOY_SHOWN)

        total = {
            "id": "C-TOTAL",
            "claim_id": "L-TOTAL",
            "type": "arithmetic",
            "basis": "report",
            "verdict": "contradicted",
            "importance": "material",
            "severity": "high",
            "public_receipt": {
                "report_operand": {
                    "label": "Total weekly revenue",
                    "value": DISPLAYED_TOTAL,
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
                    "result": CORRECTED_TOTAL,
                },
                "explanation": (
                    "The two segment values sum to a different amount than the "
                    "total shown in both report locations."
                ),
            },
            "numeric_comparison": {
                "mode": "absolute_tolerance",
                "tolerance": 0,
                "matches": False,
            },
        }
        yoy_check = rounded_arithmetic_check()
        yoy_check["id"] = "C-YOY"
        yoy_check["claim_id"] = "L-YOY"
        checks = [total, yoy_check]
        next_text = (
            "Both the Revenue KPI tile and the segment table Total row "
            f"repeat {DISPLAYED_TOTAL}, and both must change to "
            f"{CORRECTED_TOTAL}."
        )
        raw = raw_for(checks, sources=[])
        artifact = render.artifact_from_findings(
            raw, run_id="unit-render", generated_at="2026-08-25T13:10:00Z",
            layer2=checks, guidance=guidance_for(checks, text=next_text),
        )
        page = render.html_of(
            artifact,
            render_context=render_context_with_next(checks, next_text),
        )
        nxt = next_block(page)
        self.assertIn(CORRECTED_TOTAL, nxt)
        self.assertNotIn("2.1%", nxt)
        self.assertNotIn(YOY_EXACT, nxt)
        self.assertNotIn(
            f"change the report's {YOY_SHOWN}", nxt.lower() + nxt)

        snippet_path = pathlib.Path(
            "/var/folders/nh/f6pw527j6tj4sz0rn0j9znjm0000gn/T/"
            "grok-goal-0ce08f790a0a/implementer/checkpoint1-html-snippet.txt"
        )
        snippet_path.write_text(page[:4000] + "\n...\n" + nxt + "\n")

    def test_structural_title_owner_period_are_not_material_cards(self) -> None:
        yoy = rounded_arithmetic_check()
        raw = {
            "source": {
                "path": "weekly-sales-snapshot.html",
                "format": "html",
                "sha256": "b" * 64,
                "period_label": "Week ending 2026-04-04",
                "report_date": "2026-04-04",
            },
            "findings": [],
            "inventory": {
                "complete": True,
                "reader": "html",
                "items": [
                    {
                        "id": "INV-TITLE", "kind": "raw",
                        "displayed": "Weekly Sales Snapshot",
                        "location": "title", "importance": "supporting",
                    },
                    {
                        "id": "INV-OWNER", "kind": "raw",
                        "displayed": "OWNER_07",
                        "location": "owner", "importance": "supporting",
                    },
                    {
                        "id": "INV-WEEK", "kind": "raw",
                        "displayed": "Week ending 2026-04-04",
                        "location": "subtitle", "importance": "supporting",
                    },
                    {
                        "id": "INV1", "kind": "raw",
                        "displayed": "4.6%",
                        "location": "narrative", "importance": "material",
                    },
                ],
                "reason": None,
            },
            "inventory_missing": [],
            "coverage": {
                "claims_in_ledger": 1,
                "claims_reached_by_a_check": 1,
                "extractor_checkable_fraction": 1.0,
                "engine_checkable_fraction": 1.0,
                "inventory_material": 1,
                "checks_registered": 0, "checks_with_findings": 0,
                "checks_found_nothing": 0, "checks_errored": 0,
            },
            "verification": {
                "document": {"status": "complete", "detail": None},
                "semantic": {"status": "complete", "detail": None},
                "live_source": {"status": "not_run", "detail": None},
            },
            "claims": [
                {
                    "id": "STRUCT-TITLE",
                    "quote": "Weekly Sales Snapshot",
                    "public_label": "Weekly Sales Snapshot",
                    "importance": "supporting",
                    "classification": "structural_context",
                    "reason": "The host classifies the report title as structure.",
                    "outcome": None, "check_id": None,
                    "inventory_ids": ["INV-TITLE"],
                },
                {
                    "id": "STRUCT-OWNER",
                    "quote": "OWNER_07",
                    "public_label": "Report owner",
                    "importance": "supporting",
                    "classification": "structural_context",
                    "reason": "The host classifies the owner line as structure.",
                    "outcome": None, "check_id": None,
                    "inventory_ids": ["INV-OWNER"],
                },
                {
                    "id": "STRUCT-WEEK",
                    "quote": "Week ending 2026-04-04",
                    "public_label": "Week-ending date",
                    "importance": "supporting",
                    "classification": "structural_context",
                    "reason": "The host classifies the week line as period metadata.",
                    "outcome": None, "check_id": None,
                    "inventory_ids": ["INV-WEEK"],
                },
                {
                    "id": yoy["claim_id"],
                    "quote": "Revenue is down 4.6% against the same week last year.",
                    "public_label": yoy["public_receipt"]["report_operand"]["label"],
                    "importance": "material",
                    "classification": "material_claim",
                    "outcome": yoy["verdict"],
                    "check_id": yoy["id"],
                    "inventory_ids": ["INV1"],
                },
            ],
            "sources": [],
        }
        art = render.artifact_from_findings(
            raw, run_id="checkpoint1-struct",
            generated_at="2026-08-26T14:00:00Z",
            layer2=[yoy],
            guidance=guidance_for([yoy]),
        )
        page = render.html_of(
            art, render_context=render_context_with_next(
                [yoy], "Review the year-over-year receipt before sharing."))
        self.assertNotIn("STRUCT-TITLE", page)
        self.assertNotIn("STRUCT-OWNER", page)
        self.assertNotIn("STRUCT-WEEK", page)
        self.assertNotIn('data-card-id="STRUCT', page)
        self.assertEqual(page.count('data-card-id="'), 1)
        self.assertNotIn("Report owner", page)
        self.assertNotIn("OWNER_07", page)

        with tempfile.TemporaryDirectory() as tmp:
            case = build_case(pathlib.Path(tmp))
            decision = case["claims_meta"]["coordinator"][
                "partition_results"][0]["occurrence_decisions"][0]
            decision.pop("classification")
            text = " ".join(reasons(case))
            self.assertIn("classification is missing or unknown", text)

    def test_exemplar_markers_and_no_dump_tokens(self) -> None:
        total = rounded_arithmetic_check()
        total["id"] = "C-YOY"
        page = render.html_of(
            make_artifact([total], sources=[retained_source()]),
            render_context=render_context_with_next(
                [total], "Review the year-over-year receipt before sharing."),
        )
        visible = visible_text(page)
        self.assertIn("Summation", page)
        self.assertIn("/ Verify", page)
        self.assertTrue(
            "FIX FIRST" in page or "Safe to share" in page,
            page[page.find("chip"):page.find("chip") + 200],
        )
        self.assertIn("Next:", page)
        self.assertNotIn("live_tool", visible)
        self.assertNotIn('<code class="verdict">', page)
        self.assertNotIn("safe_to_share", visible)
        pathlib.Path(
            "/var/folders/nh/f6pw527j6tj4sz0rn0j9znjm0000gn/T/"
            "grok-goal-0ce08f790a0a/implementer/exemplar-markers.txt"
        ).write_text(
            "\n".join([
                "Summation: yes",
                "FIX FIRST or Safe to share: yes",
                "Next: yes",
                "live_tool visible: no",
                "code.verdict dump: no",
            ]) + "\n"
        )


def render_context_with_next(checks: list[dict], text: str) -> dict:
    return {
        "status": "complete",
        "contract_version": "verify-role-handoff/coordinator-v6",
        "checks": checks,
        "assessments": [],
        "resolutions": [],
        "whole_source_exclusions": [],
        "source_consideration": [],
        "source_consideration_problems": [],
        "semantic_status": "complete",
        "discarded": [],
        "discarded_claims": [],
        "discarded_sources": [],
        "presentation": guidance_for(checks, text=text),
        "presentation_problems": [],
    }


if __name__ == "__main__":
    unittest.main()
