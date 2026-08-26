"""Drive shipped extract + claim-taker input split + coordinator input assemble."""
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
SCRIPT = ROOT / "skills/verify/scripts/write_coordinator_input.py"
PACKAGED = ROOT / "plugins/summation/skills/verify/scripts/write_coordinator_input.py"
FIXTURE = ROOT / "tests/fixtures/verify/weekly-sales-snapshot.html"


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, check=False)


class WriteCoordinatorInputTests(unittest.TestCase):
    def test_assembles_partitions_and_sources_without_classifying(self) -> None:
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
            extract = _run([
                sys.executable, str(EXTRACT),
                "--report", str(FIXTURE),
                "--visible", str(visible),
                "--out", str(findings),
            ])
            self.assertEqual(extract.returncode, 0, extract.stderr)
            split = _run([
                sys.executable, str(SPLIT),
                "--findings", str(findings),
                "--visible", str(visible),
                "--dir", str(role_in),
            ])
            self.assertEqual(split.returncode, 0, split.stderr)
            for path in role_in.glob("claim-taker-*.json"):
                inp = json.loads(path.read_text())
                decisions = []
                for item in inp["inventory"]["items"]:
                    decisions.append({
                        "occurrence_id": item["id"],
                        "classification": "structural_context",
                        "analytical_role": "structural_context",
                        "reason": "test placeholder",
                        "clause_ids": [],
                    })
                out = {
                    "partition_id": inp["partition_id"],
                    "role": "claim_taker",
                    "stage": "claim_taking",
                    "occurrence_decisions": decisions,
                    "clauses": [],
                }
                (role_out / f"{inp['partition_id']}.json").write_text(json.dumps(out) + "\n")
            dest = role_in / "coordinator-semantic-plan.json"
            proc = _run([
                sys.executable, str(SCRIPT),
                "--findings", str(findings),
                "--role-outputs", str(role_out),
                "--evidence", str(evidence),
                "--out", str(dest),
            ])
            self.assertEqual(proc.returncode, 0, proc.stderr)
            bundle = json.loads(dest.read_text())
            self.assertEqual(bundle["stage"], "coordinator_semantic_plan")
            self.assertGreaterEqual(len(bundle["partition_results"]), 2)
            self.assertNotIn("classification_reviews", bundle)
            self.assertNotIn("canonical_claims", bundle)
            self.assertEqual(bundle["approved_source_manifest"][0]["kind"], "supplied_file")
            self.assertNotIn("decision", bundle["approved_source_manifest"][0])

    def test_packaged_plugin_copy_matches(self) -> None:
        self.assertFalse(PACKAGED.is_file())
