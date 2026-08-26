"""Full-bundle mutation proofs for coordinator-v6 semantic mechanics."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import pathlib
import sys
import tempfile
import unittest

from tests.verify_v6_case import WORKFLOW_VERSION, build_case, clone


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "verify" / "scripts" / "accept.py"


def load_accept():
    spec = importlib.util.spec_from_file_location("verify_accept_v6", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


accept = load_accept()


def validate(case: dict) -> dict:
    args = {key: value for key, value in case.items() if key in {
        "text", "sandbox", "proposed", "checks_doc", "proposed_claims",
        "claims_meta", "inventory", "report_path", "bundle_root",
        "arithmetic_uses", "validation_stage",
    }}
    return accept.validate_acceptance_bundle(**args)


def reasons(case: dict) -> list[str]:
    return validate(case)["repair_reasons"]


def rewrite_role_bundle(case: dict, role_id: str, field: str, mutate) -> None:
    """Rewrite one materialized fixture bundle and retain exact digest mechanics."""
    run = next(
        row for row in case["checks_doc"]["role_provenance"]["runs"]
        if row["id"] == role_id
    )
    path = case["bundle_root"] / run[field]["path"]
    if field == "input_bundle":
        path.chmod(0o644)
    payload = json.loads(path.read_text())
    mutate(payload)
    path.write_text(json.dumps(payload, sort_keys=True) + "\n")
    if field == "input_bundle":
        path.chmod(0o444)
    run[field]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()


def use_corrected_yoy_report_check(case: dict) -> None:
    """Expose the corrected-total YoY assessment as the public report check."""
    check = case["proposed"][1]
    check.update({"type": "arithmetic", "basis": "report"})
    check.pop("evidence_json", None)
    check["public_receipt"] = {
        "report_operand": {
            "label": "Year-over-year weekly revenue change",
            "value": "4.6%",
            "location": "weekly revenue narrative",
        },
        "decisive_operands": [
            {
                "label": "Corrected current-week revenue",
                "value": "$350,490.34",
                "location": "accepted total-revenue correction",
            },
            {
                "label": "Prior-year revenue",
                "value": "$367,290.32",
                "location": "segment table, prior total revenue",
            },
        ],
        "calculation": {
            "expression": "(367290.32 - 350490.34) / 367290.32 * 100",
            "result": "4.574032879496728%",
        },
        "explanation": (
            "The accepted corrected current total produces a 4.574 percent decline, "
            "which matches the report's 4.6 percent at the host-declared one-decimal "
            "rounding."
        ),
    }
    rewrite_role_bundle(
        case, "RR-yoy", "output_bundle",
        lambda payload: payload["checks"].__setitem__(0, copy.deepcopy(check)),
    )
    rewrite_role_bundle(
        case, "RR-resolution", "output_bundle",
        lambda payload: payload["checks"].__setitem__(1, copy.deepcopy(check)),
    )


def add_repair_context(case: dict, role_id: str, *, repair_pass_id: int) -> None:
    """Materialize one mechanical repair generation for a bounded role input."""
    run = next(
        row for row in case["checks_doc"]["role_provenance"]["runs"]
        if row["id"] == role_id
    )
    prior_output = json.loads(
        (case["bundle_root"] / run["output_bundle"]["path"]).read_text()
    )
    rewrite_role_bundle(
        case, role_id, "input_bundle",
        lambda payload: payload.update({
            "repair_context": {
                "repair_pass_id": repair_pass_id,
                "prior_role_output": prior_output,
                "mechanical_repair_reasons": [
                    "The prior role output failed one exact mechanical preflight rule."
                ],
            },
        }),
    )


def duplicate_repaired_generation(case: dict, role_id: str,
                                  duplicate_id: str) -> None:
    """Add a second materialized generation for the same mechanical role target."""
    original = next(
        row for row in case["checks_doc"]["role_provenance"]["runs"]
        if row["id"] == role_id
    )
    duplicate = copy.deepcopy(original)
    duplicate["id"] = duplicate_id
    for field, folder in (
        ("input_bundle", "role-inputs"),
        ("output_bundle", "role-outputs"),
    ):
        original_path = case["bundle_root"] / original[field]["path"]
        duplicate_path = case["bundle_root"] / folder / f"{duplicate_id}.json"
        duplicate_path.write_bytes(original_path.read_bytes())
        if field == "input_bundle":
            duplicate_path.chmod(0o444)
        duplicate[field] = {
            "path": str(duplicate_path.relative_to(case["bundle_root"])),
            "sha256": hashlib.sha256(duplicate_path.read_bytes()).hexdigest(),
        }
    duplicate["allowed_read_paths"] = [
        duplicate["input_bundle"]["path"],
        *original["allowed_read_paths"][1:],
    ]
    duplicate["observed_read_paths"] = list(duplicate["allowed_read_paths"])
    case["checks_doc"]["role_provenance"]["runs"].append(duplicate)


class CoordinatorV6AcceptedBundleTests(unittest.TestCase):
    def test_complete_v6_bundle_is_accepted_and_validator_is_pure(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            case = build_case(pathlib.Path(raw))
            before = copy.deepcopy(case)
            result = validate(case)
            self.assertEqual(result["repair_reasons"], [])
            self.assertEqual(result["status"], "complete")
            self.assertRegex(result["bundle_sha256"], r"^[0-9a-f]{64}$")
            self.assertEqual(case, before)
            propagated = result["assessments_by_id"]["AS-YOY-report"]
            self.assertEqual(
                propagated["resolved_operands"]["decisive_operands/0"],
                "$350,490.34",
            )
            self.assertEqual(
                propagated["numeric_comparison"]["customer_result"], "4.6%")
            verifier_run = next(
                row for row in result["role_provenance"]["runs"]
                if row["id"] == "RR-yoy"
            )
            self.assertEqual(verifier_run["allowed_read_paths"], [
                "role-inputs/RR-yoy.json", "q3.json",
            ])
            self.assertEqual(
                verifier_run["observed_read_paths"],
                verifier_run["allowed_read_paths"],
            )
            self.assertEqual(
                result["role_provenance"]["repair_passes_used"], 0)

    def test_zero_and_one_global_repair_pass_are_accepted_and_digest_bound(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = pathlib.Path(raw)
            zero_pass = build_case(root)
            zero_result = validate(zero_pass)
            self.assertEqual(zero_result["repair_reasons"], [])
            self.assertEqual(
                zero_result["role_provenance"]["repair_passes_used"], 0)

            one_pass = build_case(root)
            one_pass["checks_doc"]["role_provenance"][
                "repair_passes_used"] = 1
            add_repair_context(one_pass, "RR-total", repair_pass_id=1)
            add_repair_context(one_pass, "RR-yoy", repair_pass_id=1)
            first = validate(one_pass)
            second = validate(one_pass)
            self.assertEqual(first["repair_reasons"], [])
            self.assertEqual(first["role_provenance"]["repair_passes_used"], 1)
            self.assertEqual(first["bundle_sha256"], second["bundle_sha256"])
            self.assertNotEqual(
                zero_result["bundle_sha256"], first["bundle_sha256"])

    def test_two_pass_declaration_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = pathlib.Path(raw)
            two_pass = build_case(root)
            two_pass["checks_doc"]["role_provenance"][
                "repair_passes_used"] = 2
            add_repair_context(two_pass, "RR-total", repair_pass_id=1)
            two_pass_reasons = reasons(two_pass)
            self.assertIn(
                "role_provenance.repair_passes_used must be the integer 0 or 1",
                two_pass_reasons,
            )

    def test_inconsistent_repair_ids_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = pathlib.Path(raw)
            inconsistent = build_case(root)
            inconsistent["checks_doc"]["role_provenance"][
                "repair_passes_used"] = 1
            add_repair_context(inconsistent, "RR-total", repair_pass_id=1)
            add_repair_context(inconsistent, "RR-yoy", repair_pass_id=2)
            inconsistent_reasons = reasons(inconsistent)
            self.assertIn(
                "role run 'RR-yoy' repair_context.repair_pass_id must equal 1",
                inconsistent_reasons,
            )
            self.assertIn(
                "repaired role inputs do not share the one global repair_pass_id 1",
                inconsistent_reasons,
            )

    def test_repaired_generation_without_declared_pass_one_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            case = build_case(pathlib.Path(raw))
            add_repair_context(case, "RR-yoy", repair_pass_id=1)
            self.assertIn(
                "role_provenance declares zero repair passes but repaired role inputs are present",
                reasons(case),
            )

    def test_declared_pass_one_without_a_repaired_generation_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            case = build_case(pathlib.Path(raw))
            case["checks_doc"]["role_provenance"]["repair_passes_used"] = 1
            self.assertIn(
                "role_provenance declares repair pass 1 but has no repaired role input",
                reasons(case),
            )

    def test_second_generation_after_pass_one_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            case = build_case(pathlib.Path(raw))
            case["checks_doc"]["role_provenance"]["repair_passes_used"] = 1
            add_repair_context(case, "RR-yoy", repair_pass_id=1)
            duplicate_repaired_generation(case, "RR-yoy", "RR-yoy-again")
            self.assertIn(
                "repair pass 1 contains a second generation for role target "
                "'dependency_ordered_verification:L-YOY'",
                reasons(case),
            )

    def test_private_check_cutover_rejects_every_legacy_and_unknown_field(self) -> None:
        mutations = {
            "report_quote_2": "A second report quote.",
            "addressed_clause_refs": ["P-main:CL-TOTAL"],
            "population_alignment": {"status": "same_population"},
            "numeric_comparison": {
                "mode": "rounded", "rounding": "half_up", "decimal_places": 2,
            },
            "invented_semantic_alias": {"meaning": "confirmed"},
        }
        with tempfile.TemporaryDirectory() as raw:
            root = pathlib.Path(raw)
            for field, value in mutations.items():
                case = build_case(root)
                case["proposed"][0][field] = value
                with self.subTest(field=field):
                    result = validate(case)
                    self.assertIn(
                        f"evidence-verifier check 'C-TOTAL' private field "
                        f"{field!r} is not allowed in coordinator-v6",
                        result["repair_reasons"],
                    )
                    self.assertEqual(result["status"], "failed")
                    self.assertNotIn(
                        "C-TOTAL", {row["id"] for row in result["checks"]})

    def test_legacy_private_contract_is_rejected_without_a_shim(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            case = build_case(pathlib.Path(raw))
            case["claims_meta"]["contract_version"] = (
                "verify-role-handoff/coordinator-v5")
            case["checks_doc"]["contract_version"] = (
                "verify-role-handoff/coordinator-v5")
            self.assertIn(
                "private workflow version must be verify-role-handoff/coordinator-v6",
                reasons(case),
            )

    def test_missing_classification_review_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            case = build_case(pathlib.Path(raw))
            case["claims_meta"]["coordinator"]["classification_reviews"].pop()
            self.assertIn(
                "inventory occurrence 'INV-SOURCE' has no coordinator classification review",
                reasons(case),
            )

    def test_missing_or_inconsistent_analytical_role_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = pathlib.Path(raw)
            missing = build_case(root)
            decision = missing["claims_meta"]["coordinator"][
                "partition_results"][0]["occurrence_decisions"][0]
            decision.pop("analytical_role")
            self.assertIn(
                "claim-taker decision for occurrence 'INV-PERIOD' "
                "analytical_role is missing or unknown",
                reasons(missing),
            )

            inconsistent = build_case(root)
            review = inconsistent["claims_meta"]["coordinator"][
                "classification_reviews"][1]
            review["analytical_role"] = "structural_context"
            self.assertIn(
                "coordinator classification review for occurrence 'INV-KPI' "
                "analytical_role does not match its final classification",
                reasons(inconsistent),
            )

    def test_unresolved_classification_challenge_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            case = build_case(pathlib.Path(raw))
            review = case["claims_meta"]["coordinator"]["classification_reviews"][0]
            review["decision"] = "challenge"
            self.assertIn(
                "coordinator classification review for occurrence 'INV-PERIOD' is an unresolved challenge",
                reasons(case),
            )

    def test_material_promotion_without_claim_taker_clause_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            case = build_case(pathlib.Path(raw))
            review = case["claims_meta"]["coordinator"]["classification_reviews"][0]
            review.update({
                "final_classification": "material_claim",
                "analytical_role": "load_bearing_analytical_assertion",
                "decision": "accept",
                "accepted_clause_ids": [],
            })
            self.assertIn(
                "coordinator classification review for occurrence 'INV-PERIOD' cannot promote a nonmaterial proposal without a claim-taker clause",
                reasons(case),
            )

    def test_partial_compound_receipt_and_duplicate_clause_outcome_fail(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            case = build_case(pathlib.Path(raw))
            case["proposed"][0]["addressed_clause_ids"].pop()
            self.assertIn(
                "evidence-verifier check 'C-TOTAL' does not address every clause of canonical claim 'L-TOTAL'",
                reasons(case),
            )

            case = build_case(pathlib.Path(raw))
            duplicate = copy.deepcopy(case["proposed_claims"][0])
            duplicate["id"] = "L-TOTAL-ALIAS"
            duplicate["primary_clause_id"] = "P-main:CL-TOTAL"
            duplicate["member_clause_ids"] = ["P-main:CL-TOTAL"]
            duplicate["occurrence_ids"] = ["INV-TOTAL"]
            duplicate["inventory_ids"] = ["INV-TOTAL"]
            case["proposed_claims"].append(duplicate)
            self.assertIn(
                "material clause 'P-main:CL-TOTAL' belongs to more than one canonical claim",
                reasons(case),
            )

    def test_unknown_dependency_cycle_and_cross_claim_operand_fail(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = pathlib.Path(raw)
            case = build_case(root)
            dependency = case["claims_meta"]["coordinator"]["claim_dependencies"][0]
            dependency["upstream_claim_id"] = "L-UNKNOWN"
            self.assertIn(
                "claim dependency 'DEP-TOTAL-YOY' references unknown upstream claim 'L-UNKNOWN'",
                reasons(case),
            )

            case = build_case(root)
            case["claims_meta"]["coordinator"]["claim_dependencies"].append({
                "id": "DEP-YOY-TOTAL",
                "upstream_claim_id": "L-YOY",
                "downstream_claim_id": "L-TOTAL",
                "role": "decisive_operand",
                "reason": (
                    "This declared reverse dependency creates a mechanical cycle."
                ),
            })
            self.assertIn("claim dependency graph contains a cycle", reasons(case))

            case = build_case(root)
            case["claims_meta"]["coordinator"]["claim_dependencies"] = []
            self.assertIn(
                "assessment 'AS-YOY-report' uses cross-claim assessment 'AS-TOTAL-report' without a declared claim dependency",
                reasons(case),
            )

    def test_contradicted_total_propagates_to_yoy_with_host_declared_rounding(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = pathlib.Path(raw)
            corrected = build_case(root)
            use_corrected_yoy_report_check(corrected)
            accepted = validate(corrected)
            self.assertEqual(accepted["repair_reasons"], [])
            yoy = next(row for row in accepted["checks"] if row["id"] == "C-YOY")
            self.assertEqual(yoy["verdict"], "confirmed")
            self.assertEqual(
                yoy["public_receipt"]["calculation"]["result"],
                "4.574032879496728%",
            )
            self.assertEqual(
                yoy["numeric_comparison"]["customer_result"], "4.6%")
            self.assertTrue(yoy["numeric_comparison"]["matches"])

            case = build_case(root)
            downstream = case["checks_doc"]["assessments"][1]
            downstream["depends_on_assessment_ids"] = []
            downstream["operand_bindings"][0]["origin"] = {
                "kind": "report_occurrence", "occurrence_id": "INV-KPI",
            }
            downstream["calculation"]["expression"] = (
                "(367290.32 - 359490.34) / 367290.32 * 100")
            downstream["calculation"]["result"] = "2.1236552055%"
            self.assertIn(
                "assessment 'AS-YOY-report' uses stale report occurrence 'INV-KPI' from contradicted upstream claim 'L-TOTAL'",
                reasons(case),
            )

            case = build_case(root)
            upstream = case["checks_doc"]["assessments"][0]
            upstream["calculation"]["result"] = "$351,490.34"
            self.assertTrue(any(
                "AS-YOY-report" in reason
                and ("computed expression" in reason or "absent" in reason)
                for reason in reasons(case)
            ))

    def test_source_claim_matrix_omission_duplicate_disagreement_and_identity_duplicate_fail(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = pathlib.Path(raw)
            case = build_case(root)
            case["checks_doc"]["source_consideration"].pop()
            self.assertIn(
                "source/claim pair 'q3-analytics'/'L-YOY' is missing",
                reasons(case),
            )

            case = build_case(root)
            case["checks_doc"]["source_consideration"].append(
                copy.deepcopy(case["checks_doc"]["source_consideration"][0]))
            self.assertIn(
                "source/claim pair 'q3-analytics'/'L-TOTAL' is duplicated",
                reasons(case),
            )

            case = build_case(root)
            pair = case["checks_doc"]["source_consideration"][1]
            pair["verifier_decision"] = "exclude"
            pair["assessment_ids"] = []
            self.assertIn(
                "source/claim pair 'q3-analytics'/'L-YOY' has unresolved coordinator/verifier disagreement",
                reasons(case),
            )

            case = build_case(root)
            duplicate = copy.deepcopy(case["checks_doc"]["sources"][0])
            duplicate["id"] = "q3-copy"
            case["checks_doc"]["sources"].append(duplicate)
            self.assertTrue(any(
                "duplicate retained source identity" in reason
                and "q3-analytics" in reason and "q3-copy" in reason
                for reason in reasons(case)
            ))

    def test_coordinator_source_plan_is_complete_and_survives_verifier_merge(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = pathlib.Path(raw)
            case = build_case(root)
            case["claims_meta"]["coordinator"][
                "source_consideration_plan"].pop()
            self.assertIn(
                "coordinator source/claim plan 'q3-analytics'/'L-YOY' is missing",
                reasons(case),
            )

            case = build_case(root)
            case["checks_doc"]["source_consideration"][1][
                "coordinator_reason"] = (
                    "The final merge silently changed the coordinator's source judgment."
                )
            self.assertIn(
                "source/claim pair 'q3-analytics'/'L-YOY' does not preserve the coordinator source plan",
                reasons(case),
            )

    def test_semantic_plan_stage_fails_before_verifier_fanout(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            case = build_case(pathlib.Path(raw))
            case["validation_stage"] = "semantic_plan"
            case["proposed"] = []
            case["checks_doc"] = {
                "contract_version": WORKFLOW_VERSION,
                "sources": copy.deepcopy(case["checks_doc"]["sources"]),
                "checks": [],
            }
            result = validate(case)
            self.assertEqual(result["validation_stage"], "semantic_plan")
            self.assertEqual(result["repair_reasons"], [])

            case["claims_meta"]["coordinator"][
                "source_consideration_plan"].pop()
            repair_reasons = reasons(case)
            self.assertEqual(repair_reasons, [
                "coordinator source/claim plan 'q3-analytics'/'L-YOY' is missing",
            ])
            self.assertFalse(any(
                "assessment" in reason or "presentation" in reason
                for reason in repair_reasons
            ))

    def test_population_requirement_coverage_and_aligned_conflict_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = pathlib.Path(raw)
            case = build_case(root)
            alignment = case["checks_doc"]["assessments"][2]["population_alignment"]
            alignment["links"][0]["requirement_id"] = "POP-UNKNOWN"
            self.assertIn(
                "assessment 'AS-YOY-q3' population alignment does not cover claim requirement 'POP-L-YOY-period'",
                reasons(case),
            )

            case = build_case(root)
            case["checks_doc"]["assessments"][2]["effect"] = "contradicts"
            conflict_reasons = reasons(case)
            self.assertIn(
                "claim resolution 'L-YOY' must be not_checkable with state 'unreconciled' for conflicting aligned assessments",
                conflict_reasons,
            )

    def test_action_dependency_closure_and_unresolved_ancestor_fail(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = pathlib.Path(raw)
            case = build_case(root)
            case["checks_doc"]["presentation"]["actions"][1][
                "resolution_ids"] = ["L-YOY"]
            self.assertIn(
                "presentation.actions[1] resolution_ids omit dependency ancestor 'L-TOTAL'",
                reasons(case),
            )

            case = build_case(root)
            total_resolution = case["checks_doc"]["resolutions"][0]
            total_resolution.update({
                "state": "unreconciled",
                "final_verdict": "not_checkable",
                "required_action_kind": "reconcile_before_change",
            })
            self.assertTrue(any(
                "L-YOY" in reason and "unresolved upstream" in reason
                for reason in reasons(case)
            ))

    def test_changed_or_not_checkable_upstream_blocks_downstream_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = pathlib.Path(raw)
            for upstream_verdict in ("not_checkable", "changed_since_report"):
                case = build_case(root)
                upstream = case["checks_doc"]["resolutions"][0]
                upstream["final_verdict"] = upstream_verdict
                if upstream_verdict == "not_checkable":
                    upstream["state"] = "unreconciled"
                    upstream["required_action_kind"] = "reconcile_before_change"
                else:
                    upstream["state"] = "changed_since_report"
                    upstream["required_action_kind"] = "review_before_share"
                with self.subTest(upstream_verdict=upstream_verdict):
                    self.assertIn(
                        "claim resolution 'L-YOY' has unresolved upstream claim 'L-TOTAL' and must resolve not_checkable",
                        reasons(case),
                    )

    def test_preflight_and_acceptance_are_reason_identical_for_unchanged_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            case = build_case(pathlib.Path(raw))
            case["checks_doc"]["source_consideration"].pop()
            preflight = validate(case)
            acceptance = validate(case)
            self.assertEqual(
                preflight["repair_reasons"], acceptance["repair_reasons"])
            self.assertEqual(
                preflight["bundle_sha256"], acceptance["bundle_sha256"])

    def test_semantic_plan_cli_stops_before_verifier_outputs_are_required(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = pathlib.Path(raw)
            case = build_case(root)
            claims_path = root / "claims.json"
            checks_path = root / "semantic-plan-checks.json"
            findings_path = root / "findings.json"
            out_path = root / "semantic-plan-preflight.json"
            claims_path.write_text(json.dumps(case["claims_doc"]))
            checks_path.write_text(json.dumps({
                "contract_version": WORKFLOW_VERSION,
                "sources": case["checks_doc"]["sources"],
                "checks": [],
            }))
            findings_path.write_text(json.dumps({"inventory": case["inventory"]}))

            original = sys.argv
            try:
                sys.argv = [
                    "accept.py", "--semantic-plan-only",
                    "--report", str(case["report_path"]),
                    "--claims", str(claims_path), "--checks", str(checks_path),
                    "--findings", str(findings_path),
                    "--evidence-dir", str(root), "--out", str(out_path),
                ]
                self.assertEqual(accept.main(), 0)
            finally:
                sys.argv = original
            record = json.loads(out_path.read_text())
            self.assertEqual(record["validation_stage"], "semantic_plan")
            self.assertEqual(record["repair_reasons"], [])

    def test_final_cli_requires_the_exact_complete_preflight_digest(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = pathlib.Path(raw)
            case = build_case(root)
            claims_path = root / "claims.json"
            checks_path = root / "checks.json"
            findings_path = root / "findings.json"
            claims_path.write_text(json.dumps(case["claims_doc"]))
            checks_path.write_text(json.dumps(case["checks_doc"]))
            findings_path.write_text(json.dumps({"inventory": case["inventory"]}))
            preflight_path = root / "preflight.json"
            receipts_path = root / "receipts.json"

            original = sys.argv
            try:
                sys.argv = [
                    "accept.py", "--preflight-only", "--report", str(case["report_path"]),
                    "--claims", str(claims_path), "--checks", str(checks_path),
                    "--findings", str(findings_path), "--evidence-dir", str(root),
                    "--out", str(preflight_path),
                ]
                self.assertEqual(accept.main(), 0)
                preflight = json.loads(preflight_path.read_text())
                self.assertRegex(preflight["bundle_sha256"], r"^[0-9a-f]{64}$")

                sys.argv = [
                    "accept.py", "--report", str(case["report_path"]),
                    "--claims", str(claims_path), "--checks", str(checks_path),
                    "--findings", str(findings_path), "--evidence-dir", str(root),
                    "--preflight-record", str(preflight_path),
                    "--out", str(receipts_path),
                ]
                self.assertEqual(accept.main(), 0)
                case["checks_doc"]["role_provenance"][
                    "repair_passes_used"] = 1
                add_repair_context(case, "RR-yoy", repair_pass_id=1)
                checks_path.write_text(json.dumps(case["checks_doc"]))
                self.assertEqual(accept.main(), 2)
            finally:
                sys.argv = original

    def test_role_provenance_rejects_reads_outside_the_bounded_input(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            case = build_case(pathlib.Path(raw))
            run = case["checks_doc"]["role_provenance"]["runs"][0]
            run["observed_read_paths"].append("prior-artifact/grade-artifact.json")
            self.assertIn(
                "role run 'RR-claim' observed undeclared read path 'prior-artifact/grade-artifact.json'",
                reasons(case),
            )

    def test_role_input_bundle_must_match_its_exact_stage_contract(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = pathlib.Path(raw)
            case = build_case(root)
            run = case["checks_doc"]["role_provenance"]["runs"][0]
            input_path = root / run["input_bundle"]["path"]
            payload = json.loads(input_path.read_text())
            payload.pop("inventory")
            input_path.chmod(0o644)
            input_path.write_text(json.dumps(payload))
            input_path.chmod(0o444)
            run["input_bundle"]["sha256"] = hashlib.sha256(
                input_path.read_bytes()).hexdigest()
            self.assertIn(
                "role run 'RR-claim' input_bundle is missing required field 'inventory'",
                reasons(case),
            )

    def test_role_bundles_are_cross_wired_to_the_accepted_sources_and_claims(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = pathlib.Path(raw)
            case = build_case(root)
            rewrite_role_bundle(
                case, "RR-plan", "input_bundle",
                lambda payload: payload["approved_source_manifest"].clear(),
            )
            self.assertIn(
                "role run 'RR-plan' coordinator semantic-plan input does not exactly "
                "match claim-taker outputs, inventory, metadata, and approved sources",
                reasons(case),
            )

            case = build_case(root)
            rewrite_role_bundle(
                case, "RR-plan", "output_bundle",
                lambda payload: payload["canonical_claims"][0][
                    "member_clause_ids"].pop(),
            )
            self.assertIn(
                "role run 'RR-plan' coordinator semantic-plan output does not exactly "
                "match the merged coordinator handoff",
                reasons(case),
            )

    def test_verifier_and_global_resolution_outputs_match_the_final_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = pathlib.Path(raw)
            case = build_case(root)
            rewrite_role_bundle(
                case, "RR-yoy", "output_bundle",
                lambda payload: payload["assessments"].pop(),
            )
            self.assertIn(
                "role verifier assessments is missing accepted identity 'AS-YOY-q3'",
                reasons(case),
            )

            case = build_case(root)
            rewrite_role_bundle(
                case, "RR-resolution", "output_bundle",
                lambda payload: payload["presentation"].update({
                    "summary": "A different final presentation was materialized."
                }),
            )
            self.assertIn(
                "role run 'RR-resolution' coordinator global-resolution output does "
                "not exactly match the final acceptance bundle",
                reasons(case),
            )

    def test_final_sources_cannot_omit_the_approved_role_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            case = build_case(pathlib.Path(raw))
            case["checks_doc"]["sources"] = []
            self.assertIn(
                "role run 'RR-plan' coordinator semantic-plan input does not exactly "
                "match claim-taker outputs, inventory, metadata, and approved sources",
                reasons(case),
            )

    def test_bundle_digest_covers_report_inventory_claims_checks_and_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = pathlib.Path(raw)
            case = build_case(root)
            original = validate(case)["bundle_sha256"]
            mutations = []
            changed = clone(case)
            changed["text"] += " "
            changed["report_path"].write_text(changed["text"])
            mutations.append(changed)
            for area in ("inventory", "proposed_claims", "checks_doc"):
                changed = clone(case)
                if area == "inventory":
                    changed[area]["items"][0]["location"] = "changed location"
                elif area == "proposed_claims":
                    changed[area][0]["context_occurrence_ids"].append("INV-PRIOR")
                else:
                    changed[area]["presentation"]["summary"] = (
                        "The accepted bundle now contains different customer-authored text."
                    )
                mutations.append(changed)
            for changed in mutations:
                self.assertNotEqual(validate(changed)["bundle_sha256"], original)


class CoordinatorV6RouteContractTests(unittest.TestCase):
    def test_native_and_sequential_routes_have_identical_explicit_stage_contracts(self) -> None:
        contract = json.loads((
            ROOT / "skills" / "verify" / "references" / "role-contracts.json"
        ).read_text())
        self.assertEqual(contract["contract_version"], WORKFLOW_VERSION)
        native = contract["routes"]["native_subagents"]
        sequential = contract["routes"]["sequential"]
        self.assertTrue(native["primary"])
        self.assertFalse(sequential["primary"])
        self.assertEqual(native["stages"], sequential["stages"])
        self.assertEqual(native["input_contracts"], sequential["input_contracts"])
        self.assertEqual(native["output_contracts"], sequential["output_contracts"])
        self.assertEqual(contract["role_provenance"]["cross_wiring"], {
            "claim_taker_outputs_equal_coordinator_partitions": True,
            "semantic_plan_input_equals_partition_inventory_metadata_and_source_manifest": True,
            "semantic_plan_output_equals_merged_coordinator_handoff": True,
            "verifier_inputs_equal_coordinator_assignments_and_source_plan": True,
            "verifier_assessments_and_source_results_equal_global_resolution_input": True,
            "global_resolution_output_equals_final_acceptance_bundle": True,
            "comparison_basis": "opaque ids and exact values only",
        })
        self.assertEqual(native["stages"], [
            "mechanical_intake",
            "claim_taking",
            "coordinator_semantic_plan",
            "semantic_plan_preflight",
            "dependency_ordered_verification",
            "coordinator_global_resolution",
            "full_preflight",
            "single_repair_if_required",
            "final_acceptance_render_audit",
        ])


if __name__ == "__main__":
    unittest.main()
