"""Current receipt-contract coverage for Markdown, PDF, XLSX, and PPTX."""
from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "verify" / "scripts"
FIX = pathlib.Path("/Users/ericjaffe/Documents/GitHub/alg-deploy/fixtures-format")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(SCRIPTS))

from test_verify_render import make_artifact, render  # noqa: E402
import accept  # noqa: E402
import artifact_audit  # noqa: E402
import inventory  # noqa: E402


MD_PLANTED = FIX / "markdown-status/stale/weekly-project-status.md"
PDF_CLEAN = FIX / "pdf-top5/clean/top-5-segments-clean.pdf"
PDF_PLANTED = FIX / "pdf-top5/twin/top-5-segments-twin.pdf"
XLSX_CLEAN = FIX / "xlsx-margin/clean/weekly-margin-summary-clean.xlsx"
XLSX_PLANTED = FIX / "xlsx-margin/twin/weekly-margin-summary-twin.xlsx"
PPTX_PLANTED = FIX / "pptx-kpi/twin/operations-kpi-twin.pptx"

M1 = "Data is current through August 11, 2026."
M2 = "Active projects: 10"
M3 = "Projects at risk: 1"
M4 = "The at-risk list is unchanged from the prior week."
P1 = "Ranked from highest to lowest revenue."
X1 = "Note: gross margin improved 3% week over week."
T1 = "96%"
SPEAKER_NOTE = "The headline must match 94 on-time deliveries out of 100 total."


def validate_report_check(
    report: pathlib.Path,
    *,
    claim_quote: str,
    label: str,
    report_value,
    location: str,
    verdict: str,
    decisive: list[dict],
    explanation: str,
    calculation: dict | None = None,
    numeric_comparison: dict | None = None,
) -> dict:
    visible, problem = inventory.visible_text_for(report)
    if problem:
        raise AssertionError(problem)
    claims, discarded_claims = accept.validate_claims(visible, [{
        "id": "L1",
        "quote": claim_quote,
        "public_label": label,
        "importance": "material",
        "classification": "material_claim",
    }])
    if discarded_claims:
        raise AssertionError(discarded_claims)
    receipt = {
        "report_operand": {
            "label": label,
            "value": report_value,
            "location": location,
        },
        "decisive_operands": decisive,
        "explanation": explanation,
    }
    if calculation is not None:
        receipt["calculation"] = calculation
    proposed = [{
        "id": "C1",
        "claim_id": "L1",
        "type": "arithmetic" if calculation else "semantic",
        "basis": "report",
        "verdict": verdict,
        "importance": "material",
        "severity": "high" if verdict == "contradicted" else None,
        "report_quote": visible,
        "public_receipt": receipt,
    }]
    with tempfile.TemporaryDirectory() as raw:
        accepted, discarded = accept.validate_receipts(
            visible,
            pathlib.Path(raw),
            proposed,
            {"L1"},
            report_path=report,
            sources=[],
            claim_labels={"L1": claims[0]["public_label"]},
            numeric_comparisons=(
                {"L1": numeric_comparison}
                if numeric_comparison is not None else None
            ),
        )
    if discarded:
        raise AssertionError(discarded)
    return accepted[0]


@unittest.skipUnless(FIX.is_dir(), "format fixtures are not present")
class RawFormatInventoryTests(unittest.TestCase):
    def test_markdown_inventories_all_planted_claim_lines(self) -> None:
        shown = {row["displayed"] for row in inventory.inventory_for(MD_PLANTED)["items"]}
        for value in (M1, M2, M3, M4):
            self.assertIn(value, shown)

    def test_pdf_inventory_keeps_raw_rank_lines_and_values(self) -> None:
        visible, problem = inventory.visible_text_for(PDF_PLANTED)
        self.assertIsNone(problem)
        for value in (P1, "Enterprise", "$520", "SMB", "$305", "Mid-market", "$410"):
            self.assertIn(value, visible)

    def test_xlsx_inventory_keeps_cells_without_semantic_classification(self) -> None:
        result = inventory.inventory_for(XLSX_PLANTED)
        self.assertTrue(result["complete"])
        shown = {row["displayed"] for row in result["items"]}
        for value in (X1, "40.0%", "43.0%"):
            self.assertIn(value, shown)
        self.assertTrue(all(row["kind"] == "xlsx_cell" for row in result["items"]))

    def test_pptx_inventory_excludes_speaker_notes(self) -> None:
        visible, problem = inventory.visible_text_for(PPTX_PLANTED)
        self.assertIsNone(problem)
        self.assertIn(T1, visible)
        self.assertIn("94 on-time deliveries / 100 total deliveries = 94%", visible)
        self.assertNotIn(SPEAKER_NOTE, visible)


@unittest.skipUnless(FIX.is_dir(), "format fixtures are not present")
class ExplicitFormatReceiptTests(unittest.TestCase):
    def assert_canonical_page(self, check: dict) -> str:
        artifact = make_artifact([check], sources=[])
        page = render.html_of(artifact)
        self.assertEqual(artifact_audit.audit_public_artifact(artifact, page), [])
        return page

    def test_markdown_not_checkable_uses_explicit_report_receipt(self) -> None:
        check = validate_report_check(
            MD_PLANTED,
            claim_quote=M1,
            label="Reported data currency date",
            report_value="August 11, 2026",
            location="Weekly project status, data-currency line",
            verdict="not_checkable",
            decisive=[],
            explanation=(
                "No approved retained source was available to verify the displayed currency date."
            ),
        )
        page = self.assert_canonical_page(check)
        self.assertIn("Reported data currency date", page)
        self.assertIn("August 11, 2026", page)

    def test_pdf_clean_rank_receipt_shows_ordered_values(self) -> None:
        ordered = [
            ("Enterprise revenue", "$520"),
            ("Mid-market revenue", "$410"),
            ("SMB revenue", "$305"),
            ("Startup revenue", "$190"),
            ("Education revenue", "$120"),
        ]
        check = validate_report_check(
            PDF_CLEAN,
            claim_quote=P1,
            label="Reported customer-segment rank direction",
            report_value="highest to lowest",
            location="Q2 customer segment ranking statement",
            verdict="confirmed",
            decisive=[
                {
                    "label": label,
                    "value": value,
                    "location": "Q2 customer segment ordered list",
                }
                for label, value in ordered
            ],
            explanation=(
                "The displayed segment values descend from Enterprise through Education in the stated order."
            ),
        )
        page = self.assert_canonical_page(check)
        positions = [page.index(value) for _label, value in ordered]
        self.assertEqual(positions, sorted(positions))

    def test_pdf_planted_rank_receipt_exposes_the_order_mismatch(self) -> None:
        ordered = [
            ("Enterprise revenue", "$520"),
            ("SMB revenue", "$305"),
            ("Mid-market revenue", "$410"),
        ]
        check = validate_report_check(
            PDF_PLANTED,
            claim_quote=P1,
            label="Reported customer-segment rank direction",
            report_value="highest to lowest",
            location="Q2 customer segment ranking statement",
            verdict="contradicted",
            decisive=[
                {
                    "label": label,
                    "value": value,
                    "location": "Q2 customer segment ordered list",
                }
                for label, value in ordered
            ],
            explanation=(
                "The displayed order places the $305 SMB value before the larger $410 Mid-market value."
            ),
        )
        page = self.assert_canonical_page(check)
        self.assertLess(page.index("$305"), page.index("$410"))
        self.assertIn('data-disposition="contradicted"', page)

    def test_xlsx_clean_receipt_says_percentage_points(self) -> None:
        check = validate_report_check(
            XLSX_CLEAN,
            claim_quote="Note: gross margin improved 3 percentage points week over week.",
            label="Reported week-over-week gross margin improvement",
            report_value="3 percentage points",
            location="Weekly Margin sheet, gross margin note",
            verdict="confirmed",
            decisive=[
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
            calculation={"expression": "43 - 40", "result": "3 percentage points"},
            numeric_comparison={
                "mode": "absolute_tolerance", "tolerance": 0,
            },
            explanation=(
                "The displayed margins rise from 40.0% to 43.0%, which equals three percentage points."
            ),
        )
        page = self.assert_canonical_page(check)
        self.assertIn("43 - 40 = 3 percentage points", page)

    def test_pptx_percent_receipt_shows_exact_division(self) -> None:
        check = validate_report_check(
            PPTX_PLANTED,
            claim_quote=T1,
            label="Reported on-time delivery rate",
            report_value="96%",
            location="Q2 operations review, on-time delivery headline",
            verdict="contradicted",
            decisive=[
                {
                    "label": "On-time deliveries",
                    "value": 94,
                    "location": "Q2 operations appendix, delivery calculation",
                },
                {
                    "label": "Total deliveries",
                    "value": 100,
                    "location": "Q2 operations appendix, delivery calculation",
                },
            ],
            calculation={"expression": "94 / 100 * 100", "result": "94%"},
            numeric_comparison={
                "mode": "absolute_tolerance", "tolerance": 0,
            },
            explanation=(
                "The displayed 94 on-time deliveries out of 100 total calculate to 94%, not 96%."
            ),
        )
        page = self.assert_canonical_page(check)
        self.assertIn("94 / 100 * 100 = 94%", page)
        self.assertIn("On-time deliveries", page)
        self.assertIn("Total deliveries", page)
        self.assertNotIn(SPEAKER_NOTE, page)


if __name__ == "__main__":
    unittest.main()
