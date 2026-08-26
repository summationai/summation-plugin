"""Drive shipped claims helpers then write_verifier_inputs.py."""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
EXTRACT = ROOT / "skills/verify/scripts/extract.py"
SPLIT = ROOT / "skills/verify/scripts/write_claim_taker_inputs.py"
COORD = ROOT / "skills/verify/scripts/write_coordinator_input.py"
CLAIMS = ROOT / "skills/verify/scripts/write_claims_json.py"
SCRIPT = ROOT / "skills/verify/scripts/write_verifier_inputs.py"
PACKAGED = ROOT / "plugins/summation/skills/verify/scripts/write_verifier_inputs.py"
FIXTURE = ROOT / "tests/fixtures/verify/weekly-sales-snapshot.html"


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, check=False)


class WriteVerifierInputsTests(unittest.TestCase):
    def test_writes_first_wave_inputs_without_verdicts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            visible = tmp_path / "report-visible.txt"
            findings = tmp_path / "findings.json"
            evidence = tmp_path / "evidence"
            evidence.mkdir()
            (evidence / "q3.json").write_text('{"units":10481}\n')
            role_in = tmp_path / "role-inputs"
            role_out = tmp_path / "role-outputs"
            role_out.mkdir()
            self.assertEqual(_run([
                sys.executable, str(EXTRACT),
                "--report", str(FIXTURE),
                "--visible", str(visible),
                "--out", str(findings),
            ]).returncode, 0)
            self.assertEqual(_run([
                sys.executable, str(SPLIT),
                "--findings", str(findings),
                "--visible", str(visible),
                "--dir", str(role_in),
            ]).returncode, 0)
            for path in role_in.glob("claim-taker-*.json"):
                inp = json.loads(path.read_text())
                decisions = []
                clauses = []
                for item in inp["inventory"]["items"]:
                    displayed = str(item.get("displayed") or "")
                    if displayed.startswith("$"):
                        cid = f"CL-{item['id']}"
                        decisions.append({
                            "occurrence_id": item["id"],
                            "classification": "material_claim",
                            "analytical_role": "load_bearing_analytical_assertion",
                            "reason": "test material",
                            "clause_ids": [cid],
                        })
                        clauses.append({
                            "id": cid,
                            "occurrence_id": item["id"],
                            "span": {"start": 0, "end": len(displayed)},
                            "quote": displayed,
                            "public_label": displayed,
                            "context_occurrence_ids": [],
                        })
                    else:
                        decisions.append({
                            "occurrence_id": item["id"],
                            "classification": "structural_context",
                            "analytical_role": "structural_context",
                            "reason": "test structural",
                            "clause_ids": [],
                        })
                (role_out / f"{inp['partition_id']}.json").write_text(json.dumps({
                    "partition_id": inp["partition_id"],
                    "role": "claim_taker",
                    "stage": "claim_taking",
                    "occurrence_decisions": decisions,
                    "clauses": clauses,
                }) + "\n")
            plan = role_in / "coordinator-semantic-plan.json"
            self.assertEqual(_run([
                sys.executable, str(COORD),
                "--findings", str(findings),
                "--role-outputs", str(role_out),
                "--evidence", str(evidence),
                "--out", str(plan),
            ]).returncode, 0)
            claims_path = tmp_path / "claims.json"
            self.assertEqual(_run([
                sys.executable, str(CLAIMS),
                "--plan", str(plan),
                "--out", str(claims_path),
            ]).returncode, 0)
            claims_doc = json.loads(claims_path.read_text())
            sources = []
            for row in (json.loads(plan.read_text()).get("approved_source_manifest") or []):
                sources.append(row)
            checks_path = tmp_path / "checks.json"
            checks_path.write_text(json.dumps({
                "contract_version": "verify-role-handoff/coordinator-v6",
                "sources": sources,
                "checks": [],
            }) + "\n")
            proc = _run([
                sys.executable, str(SCRIPT),
                "--claims", str(claims_path),
                "--visible", str(visible),
                "--checks", str(checks_path),
                "--dir", str(role_in),
            ])
            self.assertEqual(proc.returncode, 0, proc.stderr)
            paths = [pathlib.Path(line) for line in proc.stdout.splitlines() if line.strip()]
            self.assertGreaterEqual(len(paths), 1)
            for path in paths:
                bundle = json.loads(path.read_text())
                self.assertEqual(bundle["role"], "evidence_verifier")
                self.assertNotIn("assessments", bundle)
                self.assertNotIn("checks", bundle)
                self.assertEqual(bundle["accepted_upstream_assessment_results"], [])
                self.assertTrue(bundle["canonical_claims"])

    def test_packaged_plugin_copy_matches(self) -> None:
        self.assertEqual(SCRIPT.read_bytes(), PACKAGED.read_bytes())
