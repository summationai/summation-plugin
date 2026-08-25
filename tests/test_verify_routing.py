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
        self.assertNotIn("run the `validate` skill", local)
        self.assertIn("Do not start that path during the local grade", local)

    def test_optional_local_fastmcp_fallback_is_bounded(self) -> None:
        text = skill("verify")
        local, _, _ = text.partition("## Connected path")
        start = local.index("### Optional local source wrapper")
        end = local.index("## Run directory", start)
        wrapper = local[start:end]
        self.assertIn("direct read-only API or CLI call remains valid", wrapper)
        self.assertIn("only after explicit consent", wrapper)
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

    def test_role_contract_wires_public_label_and_identical_handoffs(self) -> None:
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

        contract = json.loads(
            (SKILLS / "verify" / "references" / "role-contracts.json").read_text()
        )
        claim_output = contract["claim_taker"]["output"]["claim_required"]
        verifier_input = contract["evidence_verifier"]["input"]["claim_required"]
        self.assertEqual(claim_output, verifier_input)
        self.assertIn("public_label", claim_output)
        self.assertEqual(
            contract["claim_taker"]["input"]["inventory_item_required"],
            ["id", "displayed", "location"],
        )
        native = contract["routes"]["native_subagents"]
        sequential = contract["routes"]["sequential"]
        self.assertTrue(native["primary"])
        self.assertFalse(sequential["primary"])
        self.assertEqual(native["stages"], sequential["stages"])
        self.assertEqual(native["input_contracts"], sequential["input_contracts"])
        self.assertEqual(native["output_contracts"], sequential["output_contracts"])

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
