"""Focused renderer tests for exact public-receipt serialization."""
from __future__ import annotations

import copy
import html as html_lib
import importlib.util
import json
import pathlib
import re
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "verify" / "scripts"


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


render = load("render")
audit = load("artifact_audit")


def retained_source(*, kind: str = "supplied_file") -> dict:
    row = {
        "id": "status-snapshot",
        "kind": kind,
        "label": "Project status snapshot",
        "evidence_file": "status.json",
        "result_sha256": "a" * 64,
    }
    if kind == "live_tool":
        row["retrieval"] = {
            "retrieved_at": "2026-08-25T13:10:00Z",
            "tool": "status_api.get_week",
            "arguments": {"week": "2026-W34"},
        }
    return row


def public_receipt(label: str, report_value, *, source_id: str | None = "status-snapshot",
                   decisive: list[dict] | None = None,
                   explanation: str | None = None) -> dict:
    if decisive is None:
        decisive = [{
            "label": f"Recorded {label.lower()}",
            "value": report_value,
            "location": "Project status snapshot, retained field",
        }]
    row = {
        "report_operand": {
            "label": label,
            "value": report_value,
            "location": "Report summary, displayed value",
        },
        "decisive_operands": decisive,
        "explanation": explanation or (
            "The retained source value matches the exact value displayed in the report."
        ),
    }
    if source_id:
        row["source_id"] = source_id
    return row


def accepted_check(index: int, verdict: str = "confirmed", *,
                   basis: str = "evidence", severity: str | None = None) -> dict:
    label = f"Reported metric {index}"
    receipt = public_receipt(label, index, source_id=(
        "status-snapshot" if basis == "evidence" else None))
    if verdict == "not_checkable":
        basis = "report"
        receipt = public_receipt(
            label, index, source_id=None, decisive=[],
            explanation=(
                "No approved source was available to verify this displayed report metric."
            ),
        )
    if verdict == "changed_since_report":
        receipt = public_receipt(
            label, index, decisive=[
                {
                    "label": "Report date", "value": "2026-04-04",
                    "location": "Report summary, as-of date",
                },
                {
                    "label": f"Later recorded metric {index}", "value": index + 1,
                    "location": "Project status snapshot, retained field",
                },
                {
                    "label": "Later snapshot date", "value": "2026-08-23",
                    "location": "Project status snapshot, as-of field",
                },
            ],
            explanation=(
                "The later retained snapshot differs from the value recorded in the dated report."
            ),
        )
        receipt["reconstruction_attempt"] = (
            "The approved history source was checked, but no report-date record was retained."
        )
    return {
        "id": f"C{index}",
        "claim_id": f"L{index}",
        "type": "semantic",
        "basis": basis,
        "verdict": verdict,
        "importance": "material",
        "severity": (
            severity if severity is not None
            else "high" if verdict == "contradicted" else None
        ),
        "public_receipt": receipt,
    }


def rounded_arithmetic_check() -> dict:
    check = accepted_check(1, "confirmed", basis="report")
    check["type"] = "arithmetic"
    check["public_receipt"] = public_receipt(
        "Year-over-year revenue decrease", "4.6%", source_id=None,
        decisive=[
            {
                "label": "Current revenue", "value": "350490.34",
                "location": "Revenue total",
            },
            {
                "label": "Prior-year revenue", "value": "367290.32",
                "location": "Prior-year total",
            },
        ],
        explanation=(
            "The exact recomputation rounds to the one-decimal percentage shown."
        ),
    )
    check["public_receipt"]["calculation"] = {
        "expression": "(367290.32 - 350490.34) / 367290.32 * 100",
        "result": "4.574032879496728%",
    }
    check["numeric_comparison"] = {
        "mode": "rounded", "rounding": "half_up", "decimal_places": 1,
        "customer_result": "4.6%", "matches": True,
    }
    return check


def render_context(checks: list[dict], whole_source_exclusions: list[dict] | None = None
                   ) -> dict:
    return {
        "status": "complete",
        "contract_version": "verify-role-handoff/coordinator-v6",
        "checks": checks,
        "assessments": [],
        "resolutions": [],
        "whole_source_exclusions": list(whole_source_exclusions or []),
        "source_consideration": [],
        "source_consideration_problems": [],
        "semantic_status": "complete",
        "discarded": [],
        "discarded_claims": [],
        "discarded_sources": [],
        "presentation": guidance_for(checks),
        "presentation_problems": [],
    }


def raw_for(checks: list[dict], *, sources: list[dict] | None = None,
            supporting: bool = False) -> dict:
    source_rows = list(sources if sources is not None else [retained_source()])
    claims = [
        {
            "id": check["claim_id"],
            "quote": f"Visible report claim {index}.",
            "public_label": check["public_receipt"]["report_operand"]["label"],
            "importance": "material",
            "classification": "material_claim",
            "outcome": check["verdict"],
            "check_id": check["id"],
            "inventory_ids": [f"INV{index}"],
        }
        for index, check in enumerate(checks, 1)
    ]
    if supporting:
        claims.append({
            "id": "S1", "quote": "Source snapshot: CRM export.",
            "public_label": "CRM export provenance", "importance": "supporting",
            "classification": "supporting_provenance",
            "reason": "This line identifies the report source only.",
            "outcome": None, "check_id": None, "inventory_ids": ["INVS"],
        })
    items = [
        {
            "id": f"INV{index}", "kind": "raw", "displayed": str(index),
            "location": f"line{index}", "importance": "material",
        }
        for index in range(1, len(checks) + 1)
    ]
    if supporting:
        items.append({
            "id": "INVS", "kind": "raw", "displayed": "Source snapshot",
            "location": "lineS", "importance": "supporting",
        })
    return {
        "source": {
            "path": "report.md", "format": "md", "sha256": "b" * 64,
            "period_label": None, "report_date": None,
        },
        "findings": [],
        "inventory": {"complete": True, "reader": "md", "items": items, "reason": None},
        "inventory_missing": [],
        "coverage": {
            "claims_in_ledger": len(checks),
            "claims_reached_by_a_check": len(checks),
            "extractor_checkable_fraction": 1.0,
            "engine_checkable_fraction": 1.0,
            "inventory_material": len(checks),
            "checks_registered": 0, "checks_with_findings": 0,
            "checks_found_nothing": 0, "checks_errored": 0,
        },
        "verification": {
            "document": {"status": "complete", "detail": None},
            "semantic": {"status": "complete", "detail": None},
            "live_source": {
                "status": (
                    "complete" if any(row.get("kind") == "live_tool" for row in source_rows)
                    else "not_run"
                ),
                "detail": None,
            },
        },
        "claims": claims,
        "sources": source_rows,
    }


def guidance_for(checks: list[dict], *, text: str | None = None,
                 visible_confirmed_ids: list[str] | None = None) -> dict:
    confirmed = [row["id"] for row in checks if row["verdict"] == "confirmed"]
    selected = (
        list(visible_confirmed_ids)
        if visible_confirmed_ids is not None else confirmed[:1]
    )
    return {
        "summary": "The accepted results show what is ready and what needs attention.",
        "check_ids": selected or [checks[0]["id"]],
        "actions": [{
            "id": "A1",
            "kind": (
                "correct_report"
                if checks[0]["verdict"] == "contradicted"
                else "review_before_share"
            ),
            "text": text or "Review the material receipts before sharing the report.",
            "report_quote": "Visible report claim 1.",
            "check_ids": [checks[0]["id"]],
        }],
        "limits": [],
    }


def make_artifact(checks: list[dict], *, sources: list[dict] | None = None,
                  supporting: bool = False) -> dict:
    raw = raw_for(checks, sources=sources, supporting=supporting)
    return render.artifact_from_findings(
        raw, run_id="unit-render", generated_at="2026-08-25T13:10:00Z",
        layer2=checks, guidance=guidance_for(checks),
    )


class PublicLayerTests(unittest.TestCase):
    def test_public_layer_is_an_exact_whitelist(self) -> None:
        check = accepted_check(1)
        expected_receipt = copy.deepcopy(check["public_receipt"])
        check.update({
            "formula": "on-time / total semantic heuristic",
            "comparison": {"label": "row 9", "value": 999},
            "evidence_json": [{"pointer": "/private", "value": 1}],
            "addressed_clause_ids": ["summary:C1"],
            "assessment_ids": ["AS-C1"],
            "depends_on_assessment_ids": ["AS-UPSTREAM"],
            "operand_bindings": [{
                "slot": "decisive_operands/0",
                "origin": {"kind": "assessment_result",
                           "assessment_id": "AS-UPSTREAM",
                           "field": "calculation.result"},
            }],
            "correction_notice": {
                "statement": "Internal exact-copy enforcement only.",
                "report_value": 1, "replacement_value": 2,
                "locations": ["Summary", "Table total"],
            },
            "population_alignment": {
                "status": "same_population", "reason": "Internal grounding only.",
                "links": [],
            },
        })
        first = render._public_layer2([check], sources=[retained_source()])
        check["formula"] = "changed prose that must have no effect"
        second = render._public_layer2([check], sources=[retained_source()])
        self.assertEqual(first, second)
        self.assertEqual(first[0]["public_receipt"], expected_receipt)
        self.assertEqual(set(first[0]), set(render.CHECK_PUBLIC_KEYS))
        self.assertNotIn("formula", json.dumps(first))
        self.assertNotIn("addressed_clause_ids", json.dumps(first))
        self.assertNotIn("assessment_ids", json.dumps(first))
        self.assertNotIn("depends_on_assessment_ids", json.dumps(first))
        self.assertNotIn("operand_bindings", json.dumps(first))
        self.assertNotIn("correction_notice", json.dumps(first))
        self.assertNotIn("population_alignment", json.dumps(first))
        self.assertNotIn("/private", json.dumps(first))

    def test_renderer_has_no_semantic_fallback_apis(self) -> None:
        for name in (
            "evidence_heading", "_verification_public", "location_line",
            "public_explanation", "_public_claim", "_combined_verdict",
            "public_verdict", "customer_verdict", "CONFIRM_CARDS",
            "GROUNDED_OUTCOMES", "ROOT_PRESENTATION", "SECTION_PRESENTATION",
        ):
            self.assertFalse(hasattr(render, name), name)

    def test_missing_vague_or_private_receipts_fail_closed(self) -> None:
        source = [retained_source()]
        for mutation in ("missing", "vague", "private", "explanation"):
            check = accepted_check(1)
            if mutation == "missing":
                check.pop("public_receipt")
            elif mutation == "vague":
                check["public_receipt"]["report_operand"]["label"] = "row 2"
            elif mutation == "private":
                check["public_receipt"]["report_operand"]["location"] = "/metrics/value"
            else:
                check["public_receipt"]["explanation"] = "Confirmed."
            with self.subTest(mutation=mutation), self.assertRaises(SystemExit):
                render._public_layer2([check], sources=source)

    def test_not_checkable_requires_its_agent_receipt_and_no_operands(self) -> None:
        check = accepted_check(1, "not_checkable")
        public = render._public_layer2([check], sources=[retained_source()])
        self.assertEqual(public[0]["public_receipt"], check["public_receipt"])
        check["public_receipt"]["decisive_operands"] = [{
            "label": "Unverified value", "value": 1, "location": "Unknown source",
        }]
        with self.assertRaises(SystemExit):
            render._public_layer2([check], sources=[retained_source()])

    def test_evidence_not_checkable_requires_its_retained_source_link(self) -> None:
        check = accepted_check(1, "not_checkable")
        check["basis"] = "evidence"
        with self.assertRaises(SystemExit):
            render._public_layer2([check], sources=[retained_source()])
        check["public_receipt"]["source_id"] = "status-snapshot"
        public = render._public_layer2([check], sources=[retained_source()])
        self.assertEqual(public[0]["public_receipt"], check["public_receipt"])

    def test_changed_receipt_keeps_agent_reconstruction_inside_receipt(self) -> None:
        check = accepted_check(1, "changed_since_report")
        public = render._public_layer2([check], sources=[retained_source()])
        self.assertEqual(
            public[0]["public_receipt"]["reconstruction_attempt"],
            check["public_receipt"]["reconstruction_attempt"],
        )
        check["public_receipt"].pop("reconstruction_attempt")
        with self.assertRaises(SystemExit):
            render._public_layer2([check], sources=[retained_source()])


class LedgerTests(unittest.TestCase):
    def test_explicit_clause_membership_allows_two_claims_from_one_raw_occurrence(self) -> None:
        checks = [accepted_check(1, "contradicted"), accepted_check(2, "confirmed")]
        raw = raw_for(checks)
        raw["inventory"]["items"] = [{
            "id": "INV-SHARED", "kind": "html_text",
            "displayed": "Clause one. Clause two.", "location": "text1",
            "importance": "material", "classification": "material_claim",
        }]
        for claim in raw["claims"]:
            claim["inventory_ids"] = ["INV-SHARED"]
        for index, check in enumerate(checks, 1):
            check["assessment_ids"] = [f"AS{index}"]
        assessments = [
            {
                "id": f"AS{index}", "claim_id": f"L{index}",
                "basis": "evidence",
                "effect": (
                    "contradicts" if check["verdict"] == "contradicted"
                    else "supports"
                ),
                "source_id": "status-snapshot",
                "depends_on_assessment_ids": [], "operand_bindings": [],
            }
            for index, check in enumerate(checks, 1)
        ]
        resolutions = [
            {
                "claim_id": f"L{index}", "assessment_ids": [f"AS{index}"],
                "state": (
                    "contradicted" if check["verdict"] == "contradicted"
                    else "supported"
                ),
                "final_verdict": check["verdict"],
                "reason": "The accepted assessment resolves this canonical claim.",
                "required_action_kind": (
                    "correct_report" if check["verdict"] == "contradicted"
                    else "review_before_share"
                ),
            }
            for index, check in enumerate(checks, 1)
        ]
        receipts = {
            "status": "complete",
            "contract_version": "verify-role-handoff/coordinator-v6",
            "claims": raw["claims"],
            "checks": checks,
            "validated": checks,
            "sources": raw["sources"],
            "source_consideration": [
                {
                    "source_id": "status-snapshot", "claim_id": f"L{index}",
                    "coordinator_decision": "consider",
                    "coordinator_reason": (
                        "The retained source is relevant to this canonical claim."
                    ),
                    "verifier_decision": "used",
                    "verifier_reason": (
                        "The accepted assessment uses an exact receipt from this source."
                    ),
                    "assessment_ids": [f"AS{index}"],
                }
                for index in (1, 2)
            ],
            "source_consideration_problems": [],
            "assessments": assessments,
            "resolutions": resolutions,
            "whole_source_exclusions": [],
            "inventory": raw["inventory"],
            "inventory_missing": [],
            "claims_in_ledger": 2,
            "claims_reached_by_a_check": 2,
            "extractor_checkable_fraction": 1.0,
            "engine_checkable_fraction": 1.0,
            "semantic_status": "complete",
            "presentation": guidance_for(checks),
            "presentation_problems": [],
            "coordinator": {
                "material_inventory_claim_ids": {
                    "INV-SHARED": ["L1", "L2"],
                },
            },
        }
        render.attach_receipts_ledger(raw, receipts)
        self.assertIsNone(render.ungraded_reason(raw, True, receipts))

    def test_root_verdict_uses_one_material_ledger(self) -> None:
        cases = (
            ([accepted_check(1)], "safe_to_share"),
            ([accepted_check(1, "not_checkable")], "share_with_caveats"),
            ([accepted_check(1, "changed_since_report")], "share_with_caveats"),
            ([accepted_check(1, "contradicted")], "fix_first"),
        )
        for checks, expected in cases:
            with self.subTest(expected=expected):
                art = make_artifact(checks)
                self.assertEqual(art["verdict"], expected)

    def test_two_errors_among_nine_score_twenty_two_point_two(self) -> None:
        checks = [
            accepted_check(index, "contradicted" if index in {1, 2} else "confirmed")
            for index in range(1, 10)
        ]
        art = make_artifact(checks)
        self.assertAlmostEqual(art["score"]["value"], 200.0 / 9, places=12)
        self.assertEqual(art["evidence_coverage"]["contradicted"], 2)
        self.assertEqual(art["evidence_coverage"]["confirmed"], 7)

    def test_supporting_provenance_is_outside_material_totals(self) -> None:
        art = make_artifact([accepted_check(1)], supporting=True)
        coverage = art["evidence_coverage"]
        self.assertEqual(coverage["document_claims_total"], 1)
        self.assertEqual(coverage["supporting_claims_reviewed"], 1)
        self.assertEqual(coverage["confirmed"], 1)

    def test_arithmetic_use_marker_cannot_be_a_public_outcome(self) -> None:
        raw = raw_for([accepted_check(1)])
        raw["claims"][0]["outcome"] = "used_for_internal_arithmetic"
        self.assertEqual(render.ledger_verdict(raw), "unable_to_grade")
        with self.assertRaises(SystemExit):
            render.artifact_from_findings(
                raw, run_id="bad", generated_at="2026-08-25T13:10:00Z",
                layer2=[accepted_check(1)],
            )

    def test_machine_finding_statement_never_enters_artifact(self) -> None:
        raw = raw_for([accepted_check(1, "contradicted")])
        raw["findings"] = [{
            "check_id": "machine", "tier": "D", "statement": "machine copy",
            "inventory_ids": ["INV1"],
        }]
        art = render.artifact_from_findings(
            raw, run_id="machine", generated_at="2026-08-25T13:10:00Z",
            layer2=[accepted_check(1, "contradicted")],
            guidance=guidance_for([accepted_check(1, "contradicted")]),
        )
        self.assertEqual(art["findings"], [])
        self.assertEqual(art["diagnostics"], [])
        self.assertNotIn("machine copy", json.dumps(art))

    def test_unowned_machine_error_fails_before_serialization(self) -> None:
        raw = raw_for([accepted_check(1)])
        raw["findings"] = [{
            "check_id": "machine", "tier": "D", "statement": "internal",
            "inventory_ids": ["INV1"],
        }]
        self.assertTrue(render.document_errors_unaccounted(raw))


class HtmlTests(unittest.TestCase):
    def test_every_material_outcome_is_one_exact_card_without_truncation(self) -> None:
        checks = [
            accepted_check(1, "confirmed"),
            accepted_check(2, "confirmed"),
            accepted_check(3, "confirmed"),
            accepted_check(4, "contradicted"),
            accepted_check(5, "not_checkable"),
            accepted_check(6, "changed_since_report"),
        ]
        art = make_artifact(checks)
        page = render.html_of(art)
        tags = re.findall(r'<article class="material-card"[^>]*>', page)
        self.assertEqual(len(tags), len(checks))
        for check in checks:
            self.assertEqual(page.count(f'data-card-id="{check["id"]}"'), 1)
            tag = next(tag for tag in tags if f'data-card-id="{check["id"]}"' in tag)
            self.assertEqual(tag.count(f'data-disposition="{check["verdict"]}"'), 1)
        self.assertEqual(sum(tag.count("data-disposition=") for tag in tags), len(checks))
        self.assertEqual(audit._card_identity_problems(art, page), [])

    def test_missing_duplicate_or_mismatched_card_identity_fails(self) -> None:
        art = make_artifact([accepted_check(1), accepted_check(2)])
        page = render.html_of(art)
        mutations = (
            page.replace(' data-card-id="C1"', "", 1),
            page.replace('data-card-id="C1"', 'data-card-id="C1" data-card-id="C1"', 1),
            page.replace('data-card-id="C2"', 'data-card-id="C1"', 1),
            page.replace(
                'data-card-id="C1" data-disposition="confirmed"',
                'data-card-id="C1" data-disposition="contradicted"',
                1,
            ),
        )
        for mutated in mutations:
            self.assertTrue(audit._card_identity_problems(art, mutated))

    def test_customer_law_audit_rejects_visible_protocol_tokens_and_flat_page(self) -> None:
        art = make_artifact([
            accepted_check(1, "confirmed", severity="high"),
            accepted_check(2, "contradicted"),
        ])
        page = render.html_of(art)
        self.assertEqual(audit._customer_html_problems(art, page), [])
        for mutation in (
            page.replace("Summation", "safe_to_share Summation", 1),
            page.replace("Verification: report.md", "grade-artifact", 1),
            page.replace("FIX FIRST", "Verification result", 1),
            page.replace(
                "Fix 1 error before you share this report.",
                "Fix before sharing", 1,
            ),
            page.replace('class="tag"', 'class="missing-tag"', 1),
            page.replace('class="next"', 'class="not-next"', 1),
        ):
            self.assertTrue(audit._customer_html_problems(art, mutation))

    def test_customer_hierarchy_uses_fixed_plain_english_labels(self) -> None:
        checks = [
            accepted_check(1, "confirmed", severity="high"),
            accepted_check(2, "confirmed"),
            accepted_check(3, "contradicted"),
            accepted_check(4, "not_checkable"),
            accepted_check(5, "changed_since_report"),
        ]
        raw = raw_for(checks)
        raw["source"]["period_label"] = "Week ending April 4, 2026"
        raw["source"]["report_date"] = "2026-04-04"
        art = render.artifact_from_findings(
            raw, run_id="customer-laws", generated_at="2026-08-25T13:10:00Z",
            layer2=checks, guidance=guidance_for(checks),
        )
        page = render.html_of(art)
        visible = html_lib.unescape(re.sub(
            r"<(?:style|script)[^>]*>.*?</(?:style|script)>|<[^>]+>",
            " ", page, flags=re.I | re.S,
        ))
        self.assertIn("<title>Verification: report.md</title>", page)
        for text in (
            "Summation <span>/ Verify</span>", "FIX FIRST",
            "Fix 1 error before you share this report.",
            "Verification results", "Contradicted", "Confirmed",
            "Changed since the report", "Not checkable",
            "Report examined:", "report.md", "Week ending April 4, 2026",
            "Generated August 25, 2026", "Next:", "Technical detail",
            "Technical scope",
        ):
            self.assertIn(text, page)
        self.assertEqual(page.count('class="next"'), 1)
        for token in (
            "safe_to_share", "share_with_caveats", "fix_first",
            "unable_to_grade", "live_tool", "supplied_file",
            "not_checkable", "changed_since_report", "not_run",
            "Layer 1", "Layer 2",
        ):
            self.assertNotIn(token, visible)

    def test_next_action_is_exact_host_copy_not_a_python_template(self) -> None:
        check = accepted_check(1, severity="high")
        action = "Correct the displayed weekly total, then ask Verify to check it again."
        art = render.artifact_from_findings(
            raw_for([check]), run_id="host-action",
            generated_at="2026-08-25T13:10:00Z", layer2=[check],
            guidance=guidance_for([check], text=action),
        )
        page = render.html_of(art)
        self.assertEqual(art["actions"][0]["text"], action)
        self.assertIn(f"<b>Next:</b> {action}", page)
        for canned in (
            "Keep this verification receipt with the report",
            "Resolve the caveated outcomes below",
            "Correct the contradicted outcomes below",
            "Complete the missing verification work",
        ):
            self.assertNotIn(canned, page)

    def test_confirmation_prominence_comes_only_from_host_selected_ids(self) -> None:
        prominent = accepted_check(1, "confirmed", severity="low")
        technical = accepted_check(2, "confirmed", severity="high")
        contradiction = accepted_check(3, "contradicted")
        checks = [prominent, technical, contradiction]
        raw = raw_for(checks)
        artifact = render.artifact_from_findings(
            raw, run_id="host-placement",
            generated_at="2026-08-25T13:10:00Z", layer2=checks,
            guidance=guidance_for(checks, visible_confirmed_ids=["C1"]),
        )
        page = render.html_of(artifact)
        details_at = page.index('<details class="technical-detail"')
        self.assertLess(page.index('data-card-id="C1"'), details_at)
        self.assertGreater(page.index('data-card-id="C2"'), details_at)
        self.assertLess(page.index('data-card-id="C3"'), details_at)
        self.assertIn('data-prominence="prominent"', page)
        self.assertIn('data-prominence="technical"', page)
        for check in (prominent, technical, contradiction):
            start = page.index(f'data-card-id="{check["id"]}"')
            end = page.index("</article>", start)
            card = page[start:end]
            self.assertIn(check["public_receipt"]["explanation"], card)
            self.assertIn("Visible report claim", card)

        swapped = render.artifact_from_findings(
            raw, run_id="host-placement-swapped",
            generated_at="2026-08-25T13:10:00Z", layer2=checks,
            guidance=guidance_for(checks, visible_confirmed_ids=["C2"]),
        )
        swapped_page = render.html_of(swapped)
        swapped_details = swapped_page.index('<details class="technical-detail"')
        self.assertGreater(swapped_page.index('data-card-id="C1"'), swapped_details)
        self.assertLess(swapped_page.index('data-card-id="C2"'), swapped_details)

    def test_summary_is_exact_host_copy_and_selects_visible_confirmation(self) -> None:
        checks = [accepted_check(1, "confirmed", severity="high")]
        summary = "The confirmed receipt is decision-relevant for sharing this report."
        guidance = guidance_for(checks, visible_confirmed_ids=["C1"])
        guidance["summary"] = summary
        artifact = render.artifact_from_findings(
            raw_for(checks), run_id="host-placement-reason",
            generated_at="2026-08-25T13:10:00Z", layer2=checks,
            guidance=guidance,
        )
        page = render.html_of(artifact)
        self.assertEqual(artifact["presentation"]["summary"], summary)
        self.assertIn(summary, page)
        self.assertLess(
            page.index('data-card-id="C1"'),
            page.index('<details class="technical-detail"'),
        )

    def test_renderer_rejects_unaccepted_confirmation_selection(self) -> None:
        check = accepted_check(1, "confirmed")
        guidance = guidance_for([check], visible_confirmed_ids=["UNKNOWN"])
        with self.assertRaisesRegex(SystemExit, "presentation check ids are invalid"):
            render.artifact_from_findings(
                raw_for([check]), run_id="bad-placement",
                generated_at="2026-08-25T13:10:00Z", layer2=[check],
                guidance=guidance,
            )

    def test_html_shows_only_agent_authored_card_meaning_and_complete_receipt(self) -> None:
        check = accepted_check(1, severity="high")
        check["public_receipt"]["calculation"] = {
            "expression": "94 / 100 * 100", "result": "94%",
        }
        check["public_receipt"]["decisive_operands"] = [
            {
                "label": "On-time deliveries", "value": 94,
                "location": "Project status snapshot, delivery totals",
            },
            {
                "label": "Total deliveries", "value": 100,
                "location": "Project status snapshot, delivery totals",
            },
        ]
        art = make_artifact([check])
        page = render.html_of(art)
        for text in (
            "Visible report claim 1.", "Reported metric 1",
            "Report summary, displayed value", "On-time deliveries", "Total deliveries",
            "94 / 100 * 100 = 94%", check["public_receipt"]["explanation"],
            "Project status snapshot", "status.json", "Supplied file",
        ):
            self.assertIn(text, page)
        self.assertIn('<table class="receipt-math num">', page)
        self.assertIn("Calculated result", page)
        self.assertIn("Report shows", page)
        self.assertLess(page.index("On-time deliveries"), page.index("Calculated result"))
        self.assertLess(page.index("Calculated result"), page.index("Report shows"))
        self.assertIn("94 / 100 * 100", page)

        for fallback in (
            "The figure matches the source", "The claim matches your evidence",
            "Checked by a program", "receipts.json", "findings.json",
        ):
            self.assertNotIn(fallback, page)

        mutated = copy.deepcopy(art)
        mutated["claims"][0]["quote"] = "Agent changed the exact claim quote."
        receipt = mutated["evidence_checks"][0]["public_receipt"]
        receipt["report_operand"]["label"] = "Agent-authored replacement title"
        mutated["claims"][0]["public_label"] = "Agent-authored replacement title"
        receipt["report_operand"]["location"] = "Agent-authored public location"
        receipt["explanation"] = (
            "The agent authored this replacement explanation from the accepted evidence."
        )
        changed = render.html_of(mutated)
        for text in (
            "Agent changed the exact claim quote.",
            "Agent-authored replacement title",
            "Agent-authored public location",
            receipt["explanation"],
        ):
            self.assertIn(text, changed)

    def test_declared_rounding_is_private_but_exact_and_customer_result_render(self) -> None:
        check = rounded_arithmetic_check()
        artifact = make_artifact([check], sources=[])
        self.assertNotIn("numeric_comparison", json.dumps(artifact))
        page = render.html_of(
            artifact, render_context=render_context([check]))
        self.assertIn("Calculated result", page)
        self.assertNotIn("4.574032879496728%", page)
        self.assertIn("Customer-rounded result", page)
        self.assertIn("4.6%", page)
        self.assertLess(page.index("Calculated result"), page.index(
            "Customer-rounded result"))
        self.assertLess(page.index("Customer-rounded result"), page.index(
            "Report shows"))
        visible = re.sub(r"<[^>]+>", " ", page)
        for private in (
            "numeric_comparison", "half_up", "decimal_places",
            "absolute_tolerance",
        ):
            self.assertNotIn(private, visible)
        self.assertEqual(
            audit.audit_public_artifact(
                artifact, page, render_context=render_context([check])),
            [],
        )

    def test_not_checkable_is_compact_in_main_flow_with_full_receipt_in_detail(self) -> None:
        check = accepted_check(1, "not_checkable")
        artifact = make_artifact([check])
        page = render.html_of(artifact)
        details_at = page.index('<details class="technical-detail"')
        compact_at = page.index('class="not-checkable-item"')
        card_at = page.index('data-card-id="C1"')
        self.assertLess(compact_at, details_at)
        self.assertGreater(card_at, details_at)
        compact_end = page.index("</li>", compact_at)
        compact = page[compact_at:compact_end]
        self.assertIn("Visible report claim 1.", compact)
        self.assertIn(check["public_receipt"]["explanation"], compact)
        self.assertEqual(page.count('data-card-id="C1"'), 1)

    def test_each_evidence_card_has_one_local_source_row_and_exclusion_is_scope_only(self) -> None:
        used = retained_source(kind="live_tool")
        unused = {
            "id": "unused-source", "kind": "supplied_file",
            "label": "Unused retained snapshot", "evidence_file": "unused.json",
            "result_sha256": "c" * 64,
        }
        check = accepted_check(1, severity="high")
        art = make_artifact([check], sources=[used, unused])
        exclusion = (
            "This retained snapshot covers a different metric and was excluded from this claim."
        )
        context = render_context([check], [
            {"source_id": "unused-source", "exclusion_reason": exclusion},
        ])
        page = render.html_of(art, render_context=context)
        self.assertEqual(page.count('class="card-source"'), 1)
        for text in (
            "Project status snapshot", "status.json", "Live source",
            "2026-08-25T13:10:00Z",
        ):
            self.assertIn(text, page)
        self.assertIn('class="source-exclusions"', page)
        for text in ("Unused retained snapshot", "unused.json", exclusion):
            self.assertIn(text, page)
        card_start = page.index('data-card-id="C1"')
        card_end = page.index("</article>", card_start)
        card = page[card_start:card_end]
        for text in ("Unused retained snapshot", "unused.json", exclusion):
            self.assertNotIn(text, card)
        self.assertNotIn('class="sources"', page)
        self.assertNotIn("source_consideration", page)

    def test_sources_are_card_local_without_trailing_duplicates(self) -> None:
        checks = [accepted_check(index, severity="high") for index in range(1, 6)]
        page = render.html_of(make_artifact(checks, sources=[retained_source()]))
        self.assertEqual(page.count('class="card-source"'), 5)
        for check in checks:
            start = page.index(f'data-card-id="{check["id"]}"')
            end = page.index("</article>", start)
            self.assertEqual(page[start:end].count('class="card-source"'), 1)
        self.assertNotIn('class="sources"', page)
        self.assertNotIn("Unused retained sources", page)

    def test_structural_context_never_renders_a_material_card(self) -> None:
        check = accepted_check(1, severity="high")
        raw = raw_for([check], supporting=True)
        raw["claims"].append({
            "id": "STRUCT1", "quote": "Weekly status report",
            "public_label": "Weekly status report", "importance": "supporting",
            "classification": "structural_context",
            "reason": "This accepted occurrence is the report title and has no assertion.",
            "outcome": None, "check_id": None, "inventory_ids": ["INV-STRUCT"],
        })
        art = render.artifact_from_findings(
            raw, run_id="strip-structural", generated_at="2026-08-25T13:10:00Z",
            layer2=[check], guidance=guidance_for([check]),
        )
        page = render.html_of(art)
        self.assertNotIn("STRUCT1", json.dumps(art))
        self.assertNotIn("Weekly status report", page)
        self.assertEqual(page.count('data-card-id="'), 1)

    def test_run_status_is_mechanical_scope_not_a_claim_outcome(self) -> None:
        static = render.html_of(make_artifact(
            [accepted_check(1, severity="high")], sources=[retained_source()]))
        live = render.html_of(make_artifact(
            [accepted_check(1, severity="high")],
            sources=[retained_source(kind="live_tool")],
        ))
        self.assertIn("Live source</b>Did not run", static)
        self.assertIn("Live source</b>Ran", live)
        visible = re.sub(r"<[^>]+>", " ", static + live)
        self.assertNotIn('data-disposition="not_run"', static + live)
        self.assertNotIn("not_run", visible)
        for status in ("complete", "partial", "failed", "skipped"):
            self.assertNotRegex(visible, rf"Run status\s*{status}")

    def test_customer_copy_maps_enum_tokens_without_changing_protocol_fields(self) -> None:
        checks = [
            accepted_check(1, "confirmed", severity="high"),
            accepted_check(2, "contradicted"),
            accepted_check(3, "not_checkable"),
            accepted_check(4, "changed_since_report"),
        ]
        art = make_artifact(checks, sources=[retained_source(kind="live_tool")])
        page = render.html_of(art)
        visible = html_lib.unescape(re.sub(
            r"<(?:style|script)[^>]*>.*?</(?:style|script)>|<[^>]+>",
            " ", page, flags=re.I | re.S,
        ))
        for text in (
            "Fix 1 error before you share this report.",
            "Confirmed", "Contradicted", "Not checkable",
            "Changed since the report", "Live source",
        ):
            self.assertIn(text, visible)
        for token in (
            "fix_first", "not_checkable", "changed_since_report",
            "live_tool", "not_run",
        ):
            self.assertNotIn(token, visible)
        self.assertEqual(art["verdict"], "fix_first")
        self.assertEqual(
            [row["verdict"] for row in art["evidence_checks"]],
            ["confirmed", "contradicted", "not_checkable", "changed_since_report"],
        )
        self.assertIn('data-verdict="fix_first"', page)
        for check in checks:
            self.assertIn(f'data-disposition="{check["verdict"]}"', page)

    def test_source_kind_uses_fixed_customer_label_not_protocol_token(self) -> None:
        static = make_artifact([accepted_check(1)], sources=[retained_source()])
        static_page = render.html_of(static)
        self.assertIn("Supplied file", static_page)
        live_source = retained_source(kind="live_tool")
        live = make_artifact([accepted_check(1)], sources=[live_source])
        live_page = render.html_of(live)
        self.assertIn("Live source", live_page)
        visible = re.sub(r"<[^>]+>", " ", static_page + live_page)
        self.assertNotIn("supplied_file", visible)
        self.assertNotIn("live_tool", visible)

    def test_fixed_label_maps_are_total_and_exact(self) -> None:
        self.assertEqual(render.ROOT_STATIC_HEADLINES, {
            "safe_to_share": "Safe to share",
            "share_with_caveats": "Share with caveats",
            "unable_to_grade": "Unable to grade",
        })
        self.assertEqual(render.DISPOSITION_LABELS, {
            "confirmed": "Confirmed",
            "contradicted": "Contradicted",
            "not_checkable": "Not checkable",
            "changed_since_report": "Changed since the report",
        })
        self.assertEqual(render.SOURCE_KIND_LABELS, {
            "supplied_file": "Supplied file", "live_tool": "Live source",
        })
        self.assertEqual(render.ROOT_CHIP_LABELS, {
            "safe_to_share": "SAFE TO SHARE",
            "share_with_caveats": "SHARE WITH CAVEATS",
            "fix_first": "FIX FIRST",
            "unable_to_grade": "UNABLE TO GRADE",
        })
        for verdict, label in render.ROOT_CHIP_LABELS.items():
            artifact = make_artifact([
                accepted_check(1, "contradicted")
                if verdict == "fix_first" else accepted_check(1)
            ])
            artifact["verdict"] = verdict
            page = render.html_of(artifact)
            self.assertIn(f">{label}</span>", page)
            self.assertNotIn(">Verification result</span>", page)
        with self.assertRaises(SystemExit):
            render._fixed_label(render.DISPOSITION_LABELS, "unknown", "disposition")

    def test_fix_first_headline_uses_only_the_mechanical_error_count(self) -> None:
        checks = [
            accepted_check(1, "contradicted"),
            accepted_check(2, "contradicted"),
            accepted_check(3, "confirmed", severity="high"),
        ]
        page = render.html_of(make_artifact(checks))
        self.assertIn("<h1>Fix 2 errors before you share this report.</h1>", page)
        self.assertNotIn("<h1>Fix before sharing</h1>", page)

    def test_static_source_cannot_be_retyped_live_without_live_metadata(self) -> None:
        source = retained_source()
        source["kind"] = "live_tool"
        with self.assertRaises(SystemExit):
            make_artifact([accepted_check(1)], sources=[source])


class SchemaAndSerializationTests(unittest.TestCase):
    def test_full_artifact_contract_and_new_version_are_emitted(self) -> None:
        art = make_artifact([accepted_check(1)])
        self.assertEqual(art["schema_version"], render.SCHEMA_VERSION)
        for field in render.REQUIRED:
            self.assertIn(field, art)
        render.validate_artifact(art)
        legacy = copy.deepcopy(art)
        legacy["schema_version"] = "grade-artifact/v1"
        with self.assertRaisesRegex(SystemExit, "bad schema_version"):
            render.validate_artifact(legacy)

    def test_supplied_file_mechanically_emits_live_source_not_run(self) -> None:
        raw = raw_for([accepted_check(1)])
        raw["verification"]["live_source"]["status"] = "failed"
        art = render.artifact_from_findings(
            raw, run_id="supplied", generated_at="2026-08-25T13:10:00Z",
            layer2=[accepted_check(1)], guidance=guidance_for([accepted_check(1)]),
        )
        self.assertEqual(
            art["verification"]["live_source"],
            {"status": "not_run", "detail": None},
        )

    def test_live_tool_mechanically_emits_live_source_complete(self) -> None:
        source = retained_source(kind="live_tool")
        raw = raw_for([accepted_check(1)], sources=[source])
        raw["verification"]["live_source"]["status"] = "not_run"
        art = render.artifact_from_findings(
            raw, run_id="live", generated_at="2026-08-25T13:10:00Z",
            layer2=[accepted_check(1)], guidance=guidance_for([accepted_check(1)]),
        )
        self.assertEqual(
            art["verification"]["live_source"],
            {"status": "complete", "detail": None},
        )

    def test_static_source_cannot_make_live_source_complete(self) -> None:
        raw = raw_for([accepted_check(1)], sources=[retained_source()])
        raw["verification"]["live_source"]["status"] = "complete"
        art = render.artifact_from_findings(
            raw, run_id="static", generated_at="2026-08-25T13:10:00Z",
            layer2=[accepted_check(1)], guidance=guidance_for([accepted_check(1)]),
        )
        self.assertEqual(art["verification"]["live_source"]["status"], "not_run")

    def test_verification_detail_cannot_enter_public_output(self) -> None:
        raw = raw_for([accepted_check(1)])
        raw["verification"]["live_source"]["detail"] = (
            "A customer-facing sentence about source execution."
        )
        with self.assertRaises(SystemExit):
            render.artifact_from_findings(
                raw, run_id="verification", generated_at="2026-08-25T13:10:00Z",
                layer2=[accepted_check(1)],
            )

    def test_report_source_metadata_has_no_digest_or_format_fallback(self) -> None:
        raw = raw_for([accepted_check(1)])
        for field in ("sha256", "format"):
            broken = copy.deepcopy(raw)
            broken["source"].pop(field)
            with self.subTest(field=field), self.assertRaises(SystemExit):
                render.artifact_from_findings(
                    broken, run_id="source", generated_at="2026-08-25T13:10:00Z",
                    layer2=[accepted_check(1)],
                )
        raw["source"]["path"] = "/private/tmp/report.md"
        with self.assertRaises(SystemExit):
            render.artifact_from_findings(
                raw, run_id="source", generated_at="2026-08-25T13:10:00Z",
                layer2=[accepted_check(1)],
            )

    def test_public_json_contains_no_internal_grounding_or_alias_fields(self) -> None:
        check = accepted_check(1)
        check.update({
            "report_quote": "Visible report claim.",
            "evidence_json": [{"pointer": "/metric", "value": 1}],
            "date_receipt": {"pointer": "/date", "value": "2026-08-23"},
            "numeric_comparison": {
                "mode": "rounded", "rounding": "half_up",
                "decimal_places": 1, "customer_result": "1.0", "matches": True,
            },
            "population_alignment": {
                "status": "same_population", "reason": "Internal only.",
            },
        })
        raw = raw_for([check])
        raw["claims"][0]["arithmetic_inventory_ids"] = ["INV1"]
        art = render.artifact_from_findings(
            raw, run_id="private", generated_at="2026-08-25T13:10:00Z",
            layer2=[check], guidance=guidance_for([check]),
        )
        blob = json.dumps(art)
        for forbidden in (
            "evidence_json", "date_receipt", "population_alignment", "/metric",
            "numeric_comparison", "source_consideration",
            "arithmetic_inventory_ids", "found_by", "verification_mode",
        ):
            self.assertNotIn(forbidden, blob)
        self.assertNotIn(
            check["report_quote"],
            json.dumps(art["evidence_checks"]),
        )
        self.assertEqual(
            art["actions"][0]["report_quote"], "Visible report claim 1.")


if __name__ == "__main__":
    unittest.main()
