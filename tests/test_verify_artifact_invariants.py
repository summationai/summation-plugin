"""Format-agnostic public artifact invariants and mutation tests.

These tests encode the release gate. They do not hard-code INT9 or one fixture.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "verify" / "scripts"
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(SCRIPTS))

from test_verify_render import _minimal_art, accept, render  # noqa: E402
import artifact_audit as audit  # noqa: E402

FIX = pathlib.Path("/Users/ericjaffe/Documents/GitHub/alg-deploy/fixtures-format")
ARTIFACT_MANIFEST = os.environ.get("ALG_VERIFY_ARTIFACT_MANIFEST", "")


def valid_artifact_pair() -> tuple[dict, str]:
    def receipt(report_label, report_value, report_location, decisive_label,
                decisive_value, decisive_location, explanation, source_id):
        return {
            "report_operand": {
                "label": report_label,
                "value": report_value,
                "location": report_location,
            },
            "decisive_operands": [{
                "label": decisive_label,
                "value": decisive_value,
                "location": decisive_location,
            }],
            "explanation": explanation,
            "source_id": source_id,
        }

    confirmed = {
        "id": "C1", "claim_id": "L1", "type": "semantic",
        "basis": "evidence", "verdict": "confirmed",
        "importance": "material", "severity": None,
        "public_receipt": receipt(
            "Reported active projects", 12, "Status summary, active projects",
            "Recorded active projects", 12,
            "Project status snapshot, active projects",
            "The recorded project count matches the twelve projects shown in the report.",
            "project-status",
        ),
    }
    contradicted = {
        "id": "C2", "claim_id": "L2", "type": "semantic",
        "basis": "evidence", "verdict": "contradicted",
        "importance": "material", "severity": "high",
        "public_receipt": receipt(
            "Reported projects at risk", 1, "Status summary, risk count",
            "Recorded projects at risk", 3,
            "Project status snapshot, risk count",
            "The recorded risk count is three projects while the report shows one project.",
            "project-status",
        ),
    }
    csr = {
        "id": "C3", "claim_id": "L3", "type": "temporal",
        "basis": "evidence", "verdict": "changed_since_report",
        "importance": "material", "severity": None,
        "report_value": 10481, "current_value": 10613,
        "current_as_of": "2026-08-23", "report_date": "2026-04-04",
        "reconstruction_attempt": (
            "The approved history source was checked, but it did not retain the report-date row."
        ),
        "public_receipt": receipt(
            "Reported inventory units", 10481, "Inventory summary, units line",
            "Later recorded inventory units", 10613,
            "Inventory units snapshot, current row",
            "The later recorded snapshot shows 10,613 units after the report recorded 10,481 units.",
            "live-units",
        ),
    }
    art = _minimal_art([confirmed, contradicted, csr])
    art["sources"] = [
        {
            "id": "project-status", "kind": "supplied_file",
            "label": "Project status snapshot",
            "evidence_file": "status.json", "result_sha256": "a" * 64,
        },
        {
            "id": "live-units", "kind": "supplied_file",
            "label": "Inventory units snapshot",
            "evidence_file": "live-units.json", "result_sha256": "b" * 64,
        },
    ]
    art["source"]["report_date"] = "2026-04-04"
    art["source"]["period_label"] = "week ending April 4, 2026"
    art["verdict"] = "fix_first"
    art["claims"] = [
        {
            "id": "L1", "quote": "Active projects: 12", "importance": "material",
            "outcome": "confirmed", "check_id": confirmed["id"],
            "classification": "material_claim",
            "verification_mode": "external_evidence",
        },
        {
            "id": "L2", "quote": "Projects at risk: 1", "importance": "material",
            "outcome": "contradicted", "check_id": contradicted["id"],
            "classification": "material_claim",
            "verification_mode": "external_evidence",
        },
        {
            "id": "L3", "quote": "10,481", "importance": "material",
            "outcome": "changed_since_report", "check_id": csr["id"],
            "classification": "material_claim",
            "verification_mode": "external_evidence",
        },
        {
            "id": "L4", "quote": "Source snapshot: status.json",
            "importance": "supporting", "classification": "supporting_provenance",
            "outcome": "not_checkable",
        },
    ]
    art["score"] = {"kind": "tier_d_per_100_claims", "value": 100.0 / 3}
    art["evidence_coverage"].update({
        "document_claims_total": 3,
        "document_claims_reached": 3,
        "material_claims_reviewed": 3,
        "supporting_claims_reviewed": 1,
        "confirmed": 1,
        "contradicted": 1,
        "not_checkable": 0,
        "evidence_confirmed": 1,
        "evidence_contradicted": 1,
        "validated_outcomes": 3,
        "evidence_files_supplied": 2,
        "evidence_files_cited": ["Inventory units snapshot", "Project status snapshot"],
        "provenance_groups": [
            {
                "source_id": "project-status", "kind": "supplied_file",
                "label": "Project status snapshot",
            },
            {
                "source_id": "live-units", "kind": "supplied_file",
                "label": "Inventory units snapshot",
            },
        ],
        "source_independence": "grouped_by_declared_provenance",
    })
    page = render.html_of(art)
    return art, page


class InvariantTests(unittest.TestCase):
    def test_valid_artifact_passes(self) -> None:
        art, page = valid_artifact_pair()
        self.assertEqual(audit.audit_public_artifact(art, page), [])

    def test_score_counts_error_and_contradicted_once(self) -> None:
        raw = {
            "claims": [
                {"id": "L1", "importance": "material", "outcome": "error"},
                {"id": "L2", "importance": "material", "outcome": "contradicted"},
                *[
                    {"id": f"L{i}", "importance": "material", "outcome": "confirmed"}
                    for i in range(3, 10)
                ],
            ],
            "coverage": {},
            "headline": {},
            "findings": [],
        }
        score = render._public_score(raw, [], {})
        self.assertAlmostEqual(score["value"], 200.0 / 9, places=5)

    def test_supporting_is_excluded_from_material_totals(self) -> None:
        art, page = valid_artifact_pair()
        counts = audit.ledger_counts(art)
        self.assertEqual(counts["material"], 3)
        self.assertEqual(counts["not-checkable"], 0)
        self.assertNotIn("Read these no as unverified", page)

    def test_supporting_importance_is_excluded_even_without_classification(self) -> None:
        raw = {
            "claims": [
                {"id": "L1", "importance": "material", "outcome": "confirmed"},
                {"id": "L2", "importance": "supporting", "outcome": "not_checkable"},
            ]
        }
        self.assertEqual([row["id"] for row in render._material_claims(raw)], ["L1"])

    def test_report_only_repeated_claim_is_not_a_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            report = folder / "report.md"
            report.write_text("Active projects: 12")
            check = {
                "id": "C1", "claim_id": "L1", "type": "semantic",
                "basis": "report", "verdict": "confirmed",
                "importance": "material", "report_quote": "Active projects: 12",
                "public_receipt": {
                    "report_operand": {
                        "label": "Reported active projects", "value": 12,
                        "location": "Project summary",
                    },
                    "decisive_operands": [{
                        "label": "Repeated active projects", "value": 12,
                        "location": "Project summary",
                    }],
                    "explanation": (
                        "The same report claim is repeated without an independent calculation."
                    ),
                },
            }
            validated, discarded = accept.validate_receipts(
                report.read_text(), folder, [check], {"L1"}, report, sources=[])
            self.assertEqual(validated, [])
            self.assertTrue(any(
                "repeats the report operand" in problem
                for problem in discarded[0]["problems"]
            ))

    def test_report_only_result_without_operands_is_not_a_receipt(self) -> None:
        receipt = {
            "report_operand": {
                "label": "Reported active projects", "value": 12,
                "location": "Project summary",
            },
            "decisive_operands": [],
            "explanation": "The report calculation uses no declared decisive operands.",
        }
        self.assertFalse(render._publishable_receipt(
            receipt, basis="report", source_ids=set()))

    def test_evidence_outcome_without_source_is_not_a_receipt(self) -> None:
        receipt = {
            "report_operand": {
                "label": "Reported active projects", "value": 12,
                "location": "Project summary",
            },
            "decisive_operands": [{
                "label": "Recorded active projects", "value": 12,
                "location": "Project status snapshot",
            }],
            "explanation": "The recorded project count matches the report project count.",
        }
        self.assertFalse(render._publishable_receipt(
            receipt, basis="evidence", source_ids={"project-status"}))


class MutationTests(unittest.TestCase):
    def _assert_fails(self, mutator, page=None) -> None:
        art, original_page = valid_artifact_pair()
        mutated = mutator(art)
        problems = audit.audit_public_artifact(mutated, page if page is not None else original_page)
        self.assertTrue(problems, mutator.__name__)

    def test_remove_operands_fails(self) -> None:
        self._assert_fails(audit.mutate_remove_operands)

    def test_swap_operands_fails(self) -> None:
        self._assert_fails(audit.mutate_swap_operands)

    def test_vague_operand_label_fails(self) -> None:
        self._assert_fails(audit.mutate_vague_operand_label)

    def test_missing_public_explanation_fails(self) -> None:
        self._assert_fails(audit.mutate_remove_explanation)

    def test_missing_source_link_fails(self) -> None:
        self._assert_fails(audit.mutate_remove_source_link)

    def test_confirmed_calculation_cannot_prove_a_contradiction(self) -> None:
        self._assert_fails(audit.mutate_confirmed_calculation_to_contradiction)

    def test_equalize_csr_fails(self) -> None:
        self._assert_fails(audit.mutate_equalize_csr)

    def test_remove_csr_report_value_fails(self) -> None:
        self._assert_fails(audit.mutate_remove_csr_report_value)

    def test_hide_report_quote_2_fails_when_it_was_the_receipt(self) -> None:
        self._assert_fails(audit.mutate_hide_report_quote_2)

    def test_duplicate_findings_fails(self) -> None:
        self._assert_fails(audit.mutate_duplicate_findings)

    def test_alter_score_fails(self) -> None:
        self._assert_fails(audit.mutate_alter_score)

    def test_alter_counts_fails(self) -> None:
        self._assert_fails(audit.mutate_alter_counts)

    def test_falsify_evidence_counts_fails(self) -> None:
        art, page = valid_artifact_pair()
        mutated = audit.mutate_falsify_evidence_counts(art)
        problems = audit.audit_public_artifact(mutated, page)
        self.assertTrue(any("evidence" in item.lower() or "supplied" in item.lower() or "tile" in item.lower() or "score" in item.lower() or "coverage" in item.lower() or "does not match" in item for item in problems), problems)

    def test_demote_evidence_fails(self) -> None:
        self._assert_fails(audit.mutate_demote_evidence)

    def test_inject_paths_fails(self) -> None:
        self._assert_fails(audit.mutate_inject_paths)

    def test_inject_json_pointer_fails(self) -> None:
        self._assert_fails(audit.mutate_inject_json_pointer)

    def test_inject_slide_token_fails(self) -> None:
        self._assert_fails(audit.mutate_inject_slide_token)

    def test_inject_tenant_identifier_fails(self) -> None:
        self._assert_fails(audit.mutate_inject_tenant_identifier)

    def test_inject_credential_fails(self) -> None:
        self._assert_fails(audit.mutate_inject_credential)

    def test_static_evidence_cannot_be_relabeled_live(self) -> None:
        self._assert_fails(audit.mutate_static_evidence_to_live)


@unittest.skipUnless(FIX.is_dir(), "format fixtures are not present")
class FormatInvariantTests(unittest.TestCase):
    def test_format_grades_pass_and_mutations_fail(self) -> None:
        from test_verify_formats import (
            grade, PDF_PLANTED, PPTX_PLANTED, XLSX_PLANTED, XLSX_CLEAN,
            P1, T1, X1, XLSX_MATERIAL, provenance_claim, PDF_SOURCE,
            confirmed_report, contradicted_report,
        )
        cases = [
            (XLSX_PLANTED, list(XLSX_MATERIAL) + [X1], X1, "43.0%"),
            (PDF_PLANTED, [
                "Top 5 customer segments - Q2 2026", P1, "Enterprise", "$520",
                "SMB", "$305", "Mid-market", "$410", "Startup", "$190",
                "Education", "$120",
                "The ranking is presented as final for the quarter.",
            ], P1, "Mid-market"),
            (PPTX_PLANTED, [
                "Q2 operations review", T1, "On-time deliveries in Q2",
                "Appendix: delivery calculation",
                "94 on-time deliveries / 100 total deliveries = 94%",
            ], T1, "94 on-time deliveries / 100 total deliveries = 94%"),
        ]
        mutators = [
            audit.mutate_remove_operands,
            audit.mutate_swap_operands,
            audit.mutate_alter_score,
            audit.mutate_alter_counts,
            audit.mutate_inject_paths,
            audit.mutate_demote_evidence,
        ]
        for report, quotes, needle, second in cases:
            with self.subTest(report=report.name), tempfile.TemporaryDirectory() as raw:
                folder = pathlib.Path(raw)
                claims = [{"id": f"L{i}", "quote": q} for i, q in enumerate(quotes, 1)]
                if report == PDF_PLANTED:
                    claims.append(provenance_claim(f"L{len(quotes) + 1}", PDF_SOURCE))
                checks = []
                for i, q in enumerate(quotes, 1):
                    if q == needle:
                        checks.append(contradicted_report(f"C{i}", f"L{i}", needle, second))
                    else:
                        checks.append(confirmed_report(f"C{i}", f"L{i}", q))
                art, page = grade(
                    folder, report, claims=claims, checks=checks,
                    evidence_dir=None, run_id=f"inv-{report.stem}")
                problems = audit.audit_public_artifact(art, page)
                self.assertEqual(problems, [])
                for mutator in mutators:
                    mutated = mutator(art)
                    failed = audit.audit_public_artifact(mutated, page)
                    self.assertTrue(failed, f"{report.name} {mutator.__name__}")


@unittest.skipUnless(ARTIFACT_MANIFEST, "regenerated artifact manifest is not set")
class RegeneratedArtifactAuditTests(unittest.TestCase):
    def test_all_present_artifacts_satisfy_invariants(self) -> None:
        manifest = pathlib.Path(ARTIFACT_MANIFEST)
        self.assertTrue(manifest.is_file())
        paths = [
            pathlib.Path(line.strip()) for line in manifest.read_text().splitlines()
            if line.strip()
        ]
        self.assertEqual(len(paths), 18)
        for folder in paths:
            with self.subTest(path=str(folder)):
                art = json.loads((folder / "grade-artifact.json").read_text())
                page = (folder / "grade-artifact.html").read_text()
                problems = audit.audit_public_artifact(art, page)
                self.assertEqual(problems, [])
