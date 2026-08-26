"""Verify is the implementation. Validate is an alias. Routes stay distinct."""
from __future__ import annotations

import json
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"
GENERATED = ROOT / "plugins" / "summation" / "skills"

TEACH_VALIDATE = re.compile(
    r"("
    r"run the `validate` skill|"
    r"offer the `validate` skill|"
    r"offer \*\*validate\*\*|"
    r"/summation:validate|"
    r"\$summation-validate|"
    r"`validate` skill before|"
    r", `validate`,|"
    r"\| `validate` \|"
    r")",
    re.I,
)


def skill(name: str) -> str:
    return (SKILLS / name / "SKILL.md").read_text()


class RoutingTests(unittest.TestCase):
    def test_validate_is_alias_stub_with_no_flow_or_tool_call(self) -> None:
        text = skill("validate")
        self.assertIn("name: validate", text)
        self.assertIn("Alias for verify", text)
        self.assertIn("Prefer verify", text)
        self.assertIn("**`verify`**", text)
        self.assertNotIn("validate_report", text)
        self.assertNotIn("## Flow", text)
        self.assertNotIn("whoami", text)
        self.assertNotIn("list_reports", text)
        self.assertNotIn("sumcli", text)

    def test_local_file_route_has_no_connected_call_before_artifact(self) -> None:
        text = skill("verify")
        self.assertIn("## Connected path", text)
        local, _, _ = text.partition("## Connected path")
        blob = local.lower()
        for needle in (
            "signin",
            "whoami",
            "sumcli auth",
            "tenant guidance",
            "validate_report",
            "request_file_upload",
            "upload_file",
            "addison",
        ):
            self.assertNotIn(needle, blob, needle)
        self.assertIn("grade-artifact.html", local)
        self.assertIn("Zero Summation login for the local grade", local)
        self.assertIn("prompt that forbids questions cannot prove", local)
        self.assertNotIn("run the `validate` skill", local)
        self.assertIn("Do not start that path during the local grade", local)

    def test_optional_local_fastmcp_fallback_is_bounded(self) -> None:
        text = skill("verify")
        local, _, _ = text.partition("## Connected path")
        start = local.index("### Optional local source wrapper")
        end = local.index("## Run directory", start)
        wrapper = local[start:end]
        self.assertIn("Prefer that wrapper over a direct API or CLI call", wrapper)
        self.assertIn("direct read-only API or CLI call remains valid", wrapper)
        self.assertIn("only after explicit consent", wrapper)
        self.assertIn("Do not copy secrets into the host home", wrapper)
        self.assertIn("source-specific typed functions", wrapper)
        self.assertIn("rather than arbitrary SQL or shell input", wrapper)
        self.assertIn("without copying secrets", wrapper)
        for annotation in ("read-only", "non-destructive", "idempotent"):
            self.assertIn(annotation, wrapper)
        self.assertIn("save the raw result", wrapper)
        self.assertIn("make one test call", wrapper)
        self.assertIn("current host workflow", wrapper)
        self.assertIn("equivalent source connection inside Summation", wrapper)
        self.assertIn("add no backend, relay, default-grade dependency", wrapper)
        self.assertIn("mandatory wrapper step", wrapper)

    def test_temporal_receipt_requires_explicit_report_operand(self) -> None:
        text = skill("verify")
        self.assertIn("`report_value` must be the visible report operand", text)

    def test_unread_file_still_writes_unable_to_grade_page(self) -> None:
        text = skill("verify")
        self.assertIn('"verdict": "unable_to_grade"', text)
        self.assertIn("Do not stop at chat", text)
        self.assertIn("one Next that names a supported file type", text)
        self.assertIn("If extract exits non-zero and `findings.json` exists, keep going", text)

    def test_changed_since_report_needs_reconstruction_attempt(self) -> None:
        text = skill("verify")
        local, _, _ = text.partition("## Connected path")
        self.assertIn("`changed_since_report` card needs `reconstruction_attempt`", local)

    def test_live_tool_is_declared_in_grade_json(self) -> None:
        text = skill("verify")
        local, _, _ = text.partition("## Connected path")
        self.assertIn('"kind": "live_tool"', local)
        self.assertIn("Live source Ran", local)
        self.assertIn("`evidence_file` equal to the saved file name", local)
        self.assertIn("Name that file in `grade.json` `sources`", local)

    def test_rate_delta_uses_percentage_points(self) -> None:
        text = skill("verify")
        local, _, _ = text.partition("## Connected path")
        self.assertIn("percentage points (`pp`)", local)
        self.assertIn("result `3 pp`", local)
        self.assertIn("Say `3 pp` in the Next step", local)
        self.assertIn("relative 7.5%", local)
        self.assertIn("improved 3 pp week over week", local)

    def test_role_contract_wires_coordinator_v6_and_identical_routes(self) -> None:
        verify = skill("verify")
        roles = (SKILLS / "verify" / "references" / "roles.md").read_text()
        self.assertIn("native subagents", verify)
        self.assertIn("primary path", verify)
        self.assertIn("public_label", verify)
        self.assertIn("public_label", roles)
        self.assertIn("same input schema", roles)
        self.assertIn("same output schema", roles)
        self.assertIn("sequentially", roles)
        self.assertIn("not execution proof", roles.lower())
        self.assertIn("read-only input", roles)
        self.assertIn("observed read paths", roles)
        self.assertIn("nine stage", roles)

        contract = json.loads(
            (SKILLS / "verify" / "references" / "role-contracts.json").read_text()
        )
        self.assertEqual(
            contract["contract_version"], "verify-role-handoff/coordinator-v6")
        self.assertEqual(contract["public_contract"], {
            "schema_version": "grade-artifact/public-receipt-v1",
            "schema_change": False,
            "private_fields_are_serialized": False,
        })
        claim_taker = contract["claim_taker"]
        self.assertEqual(
            claim_taker["input"]["required"],
            ["partition_id", "visible_text", "inventory", "report_metadata"],
        )
        self.assertEqual(claim_taker["input"]["inventory_importance"], "unclassified")
        self.assertEqual(
            claim_taker["output"]["required"],
            ["partition_id", "occurrence_decisions", "clauses"],
        )
        self.assertEqual(
            claim_taker["output"]["material_clause_required"],
            [
                "id", "occurrence_id", "span", "quote", "public_label",
                "context_occurrence_ids",
            ],
        )
        self.assertIn("reason", claim_taker["output"]["occurrence_decision_required"])
        self.assertIn(
            "analytical_role",
            claim_taker["output"]["occurrence_decision_required"],
        )
        self.assertEqual(claim_taker["output"]["analytical_roles"], [
            "load_bearing_analytical_assertion",
            "supporting_provenance",
            "structural_context",
        ])

        plan = contract["coordinator_semantic_plan"]
        self.assertEqual(plan["output"]["required"], [
            "classification_reviews", "canonical_claims",
            "source_consideration_plan", "claim_dependencies",
            "verifier_assignments",
        ])
        self.assertEqual(
            plan["output"]["classification_review_decisions"],
            ["accept", "demote", "challenge"],
        )
        self.assertIn(
            "analytical_role",
            plan["output"]["classification_review_required"],
        )
        structural_policy = plan["output"]["structural_classification_policy"]
        self.assertEqual(structural_policy["owner"], "claim_taker_and_coordinator")
        self.assertFalse(structural_policy["python_text_heuristics"])
        self.assertIn("report_title", structural_policy["context_categories"])
        self.assertIn("owner_identifier", structural_policy["context_categories"])
        self.assertIn("reporting_period", structural_policy["context_categories"])
        self.assertIn("source_origin", structural_policy["context_categories"])
        self.assertEqual(
            plan["output"]["source_consideration_plan_required"],
            ["source_id", "claim_id", "decision", "reason"],
        )
        self.assertIn("population_requirements", plan["output"]["material_claim_required"])
        self.assertEqual(plan["output"]["claim_dependency_role"], "decisive_operand")

        verifier = contract["evidence_verifier"]
        self.assertEqual(
            verifier["input"]["claims_from"],
            "coordinator_semantic_plan.output.canonical_claims",
        )
        self.assertEqual(
            verifier["output"]["calculation"]["result"],
            "public_numeric_value",
        )
        for field in ("addressed_clause_ids", "assessment_ids", "public_receipt"):
            self.assertIn(field, verifier["output"]["check_required"])
        self.assertEqual(verifier["output"]["operand_origins"], {
            "report_occurrence": ["kind", "occurrence_id"],
            "source_receipt": ["kind", "source_id", "receipt"],
            "assessment_result": ["kind", "assessment_id", "field"],
        })
        population = verifier["output"]["population_alignment"]
        self.assertEqual(
            population["required_for"],
            "evidence assessment whose canonical claim declares population requirements",
        )
        self.assertEqual(population["statuses"], ["same_population", "unreconciled"])
        self.assertIn("requirement_id", population["link_required"])
        self.assertIn("reconciliation_action", population["unreconciled_required"])
        comparison = verifier["output"]["numeric_comparison"]
        self.assertEqual(comparison["modes"], ["rounded", "absolute_tolerance"])
        self.assertTrue(comparison["private_from_public_output"])

        final_merge = contract["coordinator_global_resolution"]
        self.assertEqual(final_merge["output"]["source_consideration_required"], [
            "source_id", "claim_id", "coordinator_decision",
            "coordinator_reason", "verifier_decision", "verifier_reason",
            "assessment_ids",
        ])
        self.assertIn("resolutions", final_merge["output"]["required"])
        self.assertIn("role_provenance", final_merge["output"]["required"])
        self.assertEqual(final_merge["output"]["action_required"], [
            "id", "kind", "text", "report_quote", "check_ids", "resolution_ids",
        ])
        self.assertFalse(
            final_merge["output"]["dependency_unresolved_behavior"]
            ["correct_report_allowed"]
        )

        acceptance = contract["mechanical_acceptance"]
        self.assertEqual(acceptance["validator"], "validate_acceptance_bundle")
        self.assertTrue(acceptance["pure"])
        self.assertEqual(
            acceptance["semantic_plan_preflight"]["validation_stage"],
            "semantic_plan",
        )
        self.assertEqual(
            acceptance["semantic_plan_preflight"]["runs_before"],
            "dependency_ordered_verification",
        )
        self.assertTrue(acceptance["final_bundle_digest_must_match"])
        self.assertEqual(acceptance["repair_passes"], 1)

        provenance = contract["role_provenance"]
        self.assertTrue(provenance["input_bundle_read_only"])
        self.assertTrue(provenance["observed_reads_must_be_allowed"])
        self.assertIn("assigned evidence files", provenance["allowed_reads"])
        self.assertEqual(
            set(provenance["input_bundle_stage_required"]),
            {
                "claim_taking", "coordinator_semantic_plan",
                "dependency_ordered_verification", "coordinator_global_resolution",
            },
        )
        self.assertEqual(
            set(provenance["input_bundle_stage_required"]),
            set(provenance["output_bundle_stage_required"]),
        )

        native = contract["routes"]["native_subagents"]
        sequential = contract["routes"]["sequential"]
        self.assertTrue(native["primary"])
        self.assertFalse(sequential["primary"])
        self.assertEqual(native["stages"], contract["stage_sequence"])
        self.assertEqual(len(native["stages"]), 9)
        self.assertEqual(native["stages"], sequential["stages"])
        self.assertEqual(native["input_contracts"], sequential["input_contracts"])
        self.assertEqual(native["output_contracts"], sequential["output_contracts"])

        blindness = contract["independent_semantic_authorship"]
        for forbidden in (
            "claim_classifications", "verdicts", "severities", "check_ids",
            "public_labels", "operands", "calculations", "expected_counts",
            "score", "next_action", "prior_grade_artifact", "claim_dependencies",
            "verdict_summary", "action_text",
        ):
            self.assertIn(forbidden, blindness["initial_prompt_forbidden"])
            self.assertIn(forbidden, blindness["repair_prompt_forbidden"])
        for forbidden in ("numeric_precision_choice", "source_side_winner"):
            self.assertIn(forbidden, blindness["initial_prompt_forbidden"])
            self.assertIn(forbidden, blindness["repair_prompt_forbidden"])
        self.assertEqual(
            blindness["repair_prompt_allowed"],
            [
                "original_role_input_bundle", "prior_role_output",
                "mechanical_repair_reasons", "repair_pass_id",
            ],
        )
        self.assertEqual(
            contract["role_provenance"]["required"],
            ["route", "repair_passes_used", "runs"],
        )
        self.assertEqual(
            contract["role_provenance"]["repair_passes_used"], [0, 1])
        self.assertEqual(
            contract["role_provenance"]["repair_context_optional"],
            [
                "repair_pass_id", "prior_role_output",
                "mechanical_repair_reasons",
            ],
        )
        self.assertEqual(contract["role_provenance"]["repair_pass_id"], 1)
        self.assertEqual(
            set(verifier["output"]["check_allowed"]),
            {
                "id", "claim_id", "type", "basis", "verdict", "importance",
                "severity", "addressed_clause_ids", "assessment_ids",
                "report_quote", "public_receipt", "correction_notice",
                "evidence_json", "evidence_quote", "report_value",
                "report_date", "current_value", "current_as_of",
                "reconstruction_attempt", "date_receipt",
            },
        )
        self.assertIn("answer key", roles)
        self.assertIn("prior grade artifact", roles)
        self.assertIn("Population alignment lives on an evidence assessment", roles)
        self.assertIn("source_consideration_plan", roles)
        self.assertIn("dependency closure", roles)
        live_status = contract["mechanical_outputs"]["verification.live_source"]
        self.assertEqual(live_status["input"], "accepted sources[].kind")
        self.assertEqual(
            live_status["live_tool_present"],
            {"status": "complete", "detail": None},
        )
        self.assertEqual(
            live_status["otherwise"],
            {"status": "not_run", "detail": None},
        )
        self.assertFalse(live_status["host_authored"])

    def test_connected_path_is_consent_then_addison_once(self) -> None:
        text = skill("verify")
        _, _, connected = text.partition("## Connected path")
        self.assertTrue(connected)
        self.assertIn("Itemized consent first", connected)
        self.assertIn("Authentication begins only after that consent", connected)
        self.assertLess(
            connected.lower().index("consent"),
            connected.lower().index("signin"),
        )
        self.assertEqual(connected.count("Do this path once"), 1)
        self.assertIn("request_file_upload", connected)
        self.assertIn("upload_file", connected)
        self.assertIn("finalize_file_upload", connected)
        self.assertIn("project chat with Addison", connected)
        self.assertIn("authors playbooks", connected)
        self.assertIn("verifies project reports through its existing skills", connected)
        self.assertIn("existing Workflow tools", connected)
        self.assertIn("Do not invoke the `validate` alias", connected)
        self.assertNotIn("run the `validate` skill", connected)
        self.assertNotIn("validate_report", connected)
        self.assertNotIn("V2", connected)
        self.assertNotIn("connected-verification-build", connected)
        self.assertNotIn("API gap", connected)
        self.assertIn("not the local `grade-artifact.html`", connected)

    def test_primary_docs_do_not_teach_validate_as_a_separate_action(self) -> None:
        skip = {SKILLS / "validate" / "SKILL.md"}
        hits = []
        roots = [SKILLS, ROOT / "README.md", ROOT / "packaging" / "plugin.json"]
        files = []
        for root in roots:
            if root.is_file():
                files.append(root)
            else:
                files.extend(p for p in root.rglob("*") if p.is_file())
        for path in files:
            if path in skip or path.suffix not in {".md", ".py", ".json"}:
                continue
            if "__pycache__" in path.parts:
                continue
            text = path.read_text()
            match = TEACH_VALIDATE.search(text)
            if match:
                hits.append(f"{path.relative_to(ROOT)}: {match.group(0)}")
        self.assertEqual(hits, [])

    def test_start_stays_a_separate_onboarding_path(self) -> None:
        start = skill("start")
        self.assertIn("name: start", start)
        self.assertIn("signin", start)
        self.assertIn("offer **verify**", start)
        self.assertNotIn("offer **schedule**", start)
        verify = skill("verify")
        _, _, connected = verify.partition("## Connected path")
        self.assertNotIn("the `start` skill", connected)
        self.assertIn("If they ask for a cadence", connected)

    def test_source_and_generated_package_match(self) -> None:
        src_files = []
        for path in SKILLS.rglob("*"):
            if "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            if path.is_file():
                src_files.append(path)
        self.assertTrue(src_files)
        for path in src_files:
            rel = path.relative_to(SKILLS)
            generated = GENERATED / rel
            self.assertTrue(generated.is_file(), str(rel))
            self.assertEqual(path.read_bytes(), generated.read_bytes(), str(rel))
        src_plugin = ROOT / "packaging" / "plugin.json"
        gen_plugin = ROOT / "plugins" / "summation" / "plugin.json"
        self.assertEqual(src_plugin.read_bytes(), gen_plugin.read_bytes())


if __name__ == "__main__":
    unittest.main()
