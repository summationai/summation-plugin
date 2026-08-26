"""Trust boundaries for the public-receipt artifact contract."""
from __future__ import annotations

import copy
import json
import pathlib
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "verify" / "scripts"
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(SCRIPTS))

from test_verify_render import (  # noqa: E402
    accepted_check,
    guidance_for,
    make_artifact,
    raw_for,
    render,
    retained_source,
)
import artifact_audit  # noqa: E402
import inventory  # noqa: E402


BARE_HTML = """<!doctype html>
<html><body>
<p>Revenue is $100.</p>
<p>On hand: 42 units.</p>
</body></html>
"""


def accepted_ledger(checks: list[dict]) -> dict:
    cited = [
        check["claim_id"] for check in checks
        if (check.get("public_receipt") or {}).get("source_id") == "status-snapshot"
    ]
    return {
        "checks": checks,
        "semantic_status": "complete",
        "discarded": [],
        "discarded_claims": [],
        "discarded_sources": [],
        "source_consideration": ([{
            "source_id": "status-snapshot", "claim_ids": cited,
        }] if cited else []),
        "source_consideration_problems": [],
        "presentation": guidance_for(checks),
        "presentation_problems": [],
    }


class InventoryAndRefusalTests(unittest.TestCase):
    def test_raw_html_blocks_keep_values_and_distinct_inventory_ids(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            report = pathlib.Path(raw) / "report.html"
            report.write_text(BARE_HTML)
            rows = inventory.inventory_for(report)["items"]
        by_text = {row["displayed"]: row for row in rows}
        self.assertIn("Revenue is $100.", by_text)
        self.assertIn("On hand: 42 units.", by_text)
        self.assertNotEqual(
            by_text["Revenue is $100."]["id"],
            by_text["On hand: 42 units."]["id"],
        )

    def test_html_full_inventories_kpi_and_table_occurrences_separately(self) -> None:
        report = ROOT / "tests" / "fixtures" / "verify" / "weekly-sales-snapshot.html"
        first = inventory.inventory_for(report)["items"]
        second = inventory.inventory_for(report)["items"]

        self.assertEqual(first, second)
        self.assertEqual(len({row["id"] for row in first}), len(first))
        outside = [row for row in first if row["kind"] == "html_text"]
        table = [row for row in first if row["kind"] == "table_cell"]
        self.assertTrue({"$359,490.34", "Revenue", "10,481", "Units"} <= {
            row["displayed"] for row in outside
        })
        self.assertTrue({"$359,490.34", "$367,290.32", "Total"} <= {
            row["displayed"] for row in table
        })
        tile_total = next(
            row for row in outside if row["displayed"] == "$359,490.34")
        table_total = next(
            row for row in table if row["displayed"] == "$359,490.34")
        self.assertNotEqual(tile_total["id"], table_total["id"])
        self.assertTrue(all(row["importance"] == "unclassified" for row in first))

    def test_unreadable_pdf_inventory_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            report = pathlib.Path(raw) / "broken.pdf"
            report.write_bytes(b"not a pdf")
            result = inventory.inventory_for(report)
        self.assertFalse(result["complete"])
        self.assertEqual(result["items"], [])
        self.assertTrue(result["reason"])

    def test_missing_receipts_or_inventory_prevents_grading(self) -> None:
        check = accepted_check(1)
        raw = raw_for([check])
        self.assertEqual(
            render.ungraded_reason(raw, False, None),
            "accepted receipts are required",
        )
        raw["inventory_missing"] = ["INV1"]
        self.assertEqual(
            render.ungraded_reason(raw, True, accepted_ledger([check])),
            "material inventory is not fully accounted for",
        )

    def test_duplicate_inventory_ownership_prevents_grading(self) -> None:
        checks = [accepted_check(1), accepted_check(2)]
        raw = raw_for(checks)
        raw["claims"][1]["inventory_ids"] = ["INV1"]
        self.assertEqual(
            render.ungraded_reason(raw, True, accepted_ledger(checks)),
            "material inventory ids do not reconcile with claims",
        )


class PublicBoundaryTests(unittest.TestCase):
    def test_machine_candidate_copy_cannot_enter_public_json_or_html(self) -> None:
        check = accepted_check(1, "contradicted")
        raw = raw_for([check])
        raw["findings"] = [{
            "check_id": "machine-candidate",
            "tier": "D",
            "statement": "Internal machine-selected semantic explanation.",
            "label": "Internal machine label",
            "inventory_ids": ["INV1"],
        }]
        artifact = render.artifact_from_findings(
            raw,
            run_id="trust-machine-copy",
            generated_at="2026-08-25T13:10:00Z",
            layer2=[check],
            guidance=guidance_for([check]),
        )
        page = render.html_of(artifact)
        blob = json.dumps(artifact) + page
        self.assertNotIn("Internal machine-selected", blob)
        self.assertNotIn("Internal machine label", blob)
        self.assertEqual(artifact_audit.audit_public_artifact(artifact, page), [])

    def test_private_receipt_text_fails_closed(self) -> None:
        for private_text in (
            "/private/tmp/source.json",
            "Use /metrics/on_time",
            "slide2/shape3",
            "tenant_id=customer-123",
            "api_key=secret",
        ):
            check = accepted_check(1)
            check["public_receipt"]["report_operand"]["location"] = private_text
            with self.subTest(private_text=private_text), self.assertRaises(SystemExit):
                render._public_layer2([check], sources=[retained_source()])

    def test_credential_bearing_live_arguments_fail_closed(self) -> None:
        source = retained_source(kind="live_tool")
        source["retrieval"]["arguments"] = {"api_key": "secret"}
        with self.assertRaises(SystemExit):
            render._public_sources([source])

    def test_renderer_does_not_invent_host_promises_or_source_sentences(self) -> None:
        artifact = make_artifact([accepted_check(1)])
        page = render.html_of(artifact)
        for phrase in (
            "put this on a schedule",
            "run a live-query workflow",
            "upload this",
            "Supplied recorded evidence",
            "Actual live query",
        ):
            self.assertNotIn(phrase, page)

    def test_extra_public_alias_field_fails_schema(self) -> None:
        artifact = make_artifact([accepted_check(1)])
        mutated = copy.deepcopy(artifact)
        mutated["evidence_checks"][0]["legacy_public_alias"] = "confirmed"
        with self.assertRaises(Exception):
            render.validate_artifact(mutated)


if __name__ == "__main__":
    unittest.main()
