"""Mutation tests for the exact public artifact and rendered-text contract."""
from __future__ import annotations

import copy
import json
import pathlib
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "verify" / "scripts"
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(SCRIPTS))

import artifact_audit as audit  # noqa: E402
import render  # noqa: E402
from test_verify_render import (  # noqa: E402
    accepted_check,
    make_artifact,
    render_context,
    rounded_arithmetic_check,
)


def valid_artifact_pair() -> tuple[dict, str]:
    checks = [
        accepted_check(1, "confirmed"),
        accepted_check(2, "contradicted"),
        accepted_check(3, "not_checkable"),
        accepted_check(4, "changed_since_report"),
    ]
    artifact = make_artifact(checks, supporting=True)
    return artifact, render.html_of(artifact)


class InvariantTests(unittest.TestCase):
    def test_black_box_audit_accepts_exact_private_render_context(self) -> None:
        check = rounded_arithmetic_check()
        artifact = make_artifact([check], sources=[])
        context = render_context([check])
        page = render.html_of(artifact, render_context=context)
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            artifact_path = folder / "grade-artifact.json"
            page_path = folder / "grade-artifact.html"
            context_path = folder / "receipts.json"
            artifact_path.write_text(json.dumps(artifact))
            page_path.write_text(page)
            context_path.write_text(json.dumps(context))
            argv = sys.argv
            sys.argv = [
                "artifact_audit.py", str(artifact_path), str(page_path),
                str(context_path),
            ]
            try:
                self.assertEqual(audit.main(), 0)
            finally:
                sys.argv = argv

    def test_valid_artifact_and_exact_html_pass(self) -> None:
        artifact, page = valid_artifact_pair()
        self.assertEqual(audit.audit_public_artifact(artifact, page), [])

    def test_ledger_counts_exclude_supporting_provenance(self) -> None:
        artifact, _page = valid_artifact_pair()
        counts = audit.ledger_counts(artifact)
        self.assertEqual(counts, {
            "material": 4,
            "supporting": 1,
            "changed_since_report": 1,
            "confirmed": 1,
            "contradicted": 1,
            "not_checkable": 1,
        })

    def test_machine_findings_and_diagnostics_are_structurally_empty(self) -> None:
        artifact, _page = valid_artifact_pair()
        self.assertEqual(artifact["findings"], [])
        self.assertEqual(artifact["diagnostics"], [])

    def test_stale_report_quote_2_mutation_name_is_removed(self) -> None:
        self.assertFalse(hasattr(audit, "mutate_hide_report_quote_2"))
        self.assertTrue(hasattr(audit, "mutate_remove_report_operand"))


class JsonMutationTests(unittest.TestCase):
    def assert_mutation_fails(self, mutator) -> None:
        artifact, page = valid_artifact_pair()
        mutated = mutator(artifact)
        self.assertTrue(audit.audit_public_artifact(mutated, page), mutator.__name__)

    def test_missing_decisive_operands_fails(self) -> None:
        self.assert_mutation_fails(audit.mutate_remove_operands)

    def test_changed_operand_order_or_value_fails_exact_serialization(self) -> None:
        self.assert_mutation_fails(audit.mutate_swap_operands)

    def test_vague_operand_label_fails(self) -> None:
        self.assert_mutation_fails(audit.mutate_vague_operand_label)

    def test_missing_report_operand_fails(self) -> None:
        self.assert_mutation_fails(audit.mutate_remove_report_operand)

    def test_missing_substantive_explanation_fails(self) -> None:
        self.assert_mutation_fails(audit.mutate_remove_explanation)

    def test_missing_source_link_fails(self) -> None:
        self.assert_mutation_fails(audit.mutate_remove_source_link)

    def test_wrong_arithmetic_result_fails(self) -> None:
        self.assert_mutation_fails(audit.mutate_confirmed_calculation_to_contradiction)

    def test_machine_finding_copy_fails(self) -> None:
        self.assert_mutation_fails(audit.mutate_duplicate_findings)

    def test_evidence_findings_must_equal_material_contradictions(self) -> None:
        self.assert_mutation_fails(audit.mutate_alter_evidence_findings)

    def test_score_mutation_fails(self) -> None:
        self.assert_mutation_fails(audit.mutate_alter_score)

    def test_material_count_mutation_fails(self) -> None:
        self.assert_mutation_fails(audit.mutate_alter_counts)

    def test_evidence_count_mutation_fails(self) -> None:
        self.assert_mutation_fails(audit.mutate_falsify_evidence_counts)

    def test_basis_mutation_fails(self) -> None:
        self.assert_mutation_fails(audit.mutate_demote_evidence)

    def test_private_path_fails(self) -> None:
        self.assert_mutation_fails(audit.mutate_inject_paths)

    def test_json_pointer_fails(self) -> None:
        self.assert_mutation_fails(audit.mutate_inject_json_pointer)

    def test_raw_slide_shape_token_fails(self) -> None:
        self.assert_mutation_fails(audit.mutate_inject_slide_token)

    def test_tenant_identifier_fails(self) -> None:
        self.assert_mutation_fails(audit.mutate_inject_tenant_identifier)

    def test_credential_fails(self) -> None:
        self.assert_mutation_fails(audit.mutate_inject_credential)

    def test_static_file_cannot_become_live_tool(self) -> None:
        self.assert_mutation_fails(audit.mutate_static_evidence_to_live)

    def test_verification_detail_cannot_enter_public_output(self) -> None:
        self.assert_mutation_fails(audit.mutate_inject_verification_detail)

    def test_static_source_cannot_claim_live_complete(self) -> None:
        self.assert_mutation_fails(audit.mutate_static_source_claims_live_complete)

    def test_found_by_and_verification_mode_fields_fail_schema(self) -> None:
        for field in ("found_by", "verification_mode"):
            artifact, page = valid_artifact_pair()
            artifact["claims"][0][field] = "internal"
            problems = audit.audit_public_artifact(artifact, page)
            self.assertTrue(problems)
            self.assertTrue(any(field in problem for problem in problems), problems)


class RenderedTextMutationTests(unittest.TestCase):
    def test_missing_duplicate_and_mismatched_cards_fail(self) -> None:
        artifact, page = valid_artifact_pair()
        mutations = (
            page.replace(' data-card-id="C1"', "", 1),
            page.replace(
                'data-card-id="C1"',
                'data-card-id="C1" data-card-id="C1"',
                1,
            ),
            page.replace('data-card-id="C2"', 'data-card-id="C1"', 1),
            page.replace(
                'data-disposition="confirmed"',
                'data-disposition="contradicted"',
                1,
            ),
        )
        for mutated in mutations:
            with self.subTest(fragment=mutated[:80]):
                self.assertTrue(audit.audit_public_artifact(artifact, mutated))

    def test_injected_fallback_copy_fails_exact_serialization(self) -> None:
        artifact, page = valid_artifact_pair()
        mutated = page.replace(
            '<section class="technical-scope">',
            '<p>Supplied recorded evidence</p><section class="technical-scope">',
            1,
        )
        problems = audit.audit_public_artifact(artifact, mutated)
        self.assertIn(
            "HTML is not the exact generic serialization of the artifact",
            problems,
        )

    def test_removed_agent_operand_text_fails_exact_serialization(self) -> None:
        artifact, page = valid_artifact_pair()
        mutated = page.replace("Reported metric 1", "", 1)
        self.assertTrue(audit.audit_public_artifact(artifact, mutated))

    def test_each_material_card_has_one_exact_identity_pair(self) -> None:
        artifact, page = valid_artifact_pair()
        self.assertEqual(audit._card_identity_problems(artifact, page), [])
        for check in artifact["evidence_checks"]:
            self.assertEqual(page.count(f'data-card-id="{check["id"]}"'), 1)


class ContractCutoverTests(unittest.TestCase):
    def test_legacy_schema_version_is_rejected(self) -> None:
        artifact, _page = valid_artifact_pair()
        artifact["schema_version"] = "grade-artifact/v1"
        with self.assertRaisesRegex(SystemExit, "bad schema_version"):
            render.validate_artifact(artifact)

    def test_not_checkable_without_public_receipt_is_rejected(self) -> None:
        artifact = make_artifact([accepted_check(1, "not_checkable")])
        artifact["evidence_checks"][0].pop("public_receipt")
        with self.assertRaises(Exception):
            render.validate_artifact(artifact)

    def test_changed_receipt_requires_reconstruction_inside_public_receipt(self) -> None:
        artifact = make_artifact([accepted_check(1, "changed_since_report")])
        artifact["evidence_checks"][0]["public_receipt"].pop("reconstruction_attempt")
        page = render.html_of(make_artifact([accepted_check(1, "changed_since_report")]))
        self.assertTrue(audit.audit_public_artifact(artifact, page))

    def test_public_json_has_no_grounding_or_alias_fields(self) -> None:
        artifact, _page = valid_artifact_pair()
        blob = str(artifact)
        for forbidden in (
            "report_quote_2", "evidence_json", "date_receipt",
            "population_alignment",
            "found_by", "verification_mode", "used_for_internal_arithmetic",
        ):
            self.assertNotIn(forbidden, blob)
        self.assertNotIn(
            "report_quote", str(artifact["evidence_checks"]),
        )
        self.assertTrue(all("report_quote" in row for row in artifact["actions"]))


if __name__ == "__main__":
    unittest.main()
