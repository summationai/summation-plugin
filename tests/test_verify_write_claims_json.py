"""Drive shipped extract/split/coordinator-input then write_claims_json.py."""
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
SCRIPT = ROOT / "skills/verify/scripts/write_claims_json.py"
PACKAGED = ROOT / "plugins/summation/skills/verify/scripts/write_claims_json.py"
FIXTURE = ROOT / "tests/fixtures/verify/weekly-sales-snapshot.html"


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, check=False)


class WriteClaimsJsonTests(unittest.TestCase):
    def test_copies_claim_taker_classifications_without_inventing_them(self) -> None:
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
                    if displayed.startswith("$") or "%" in displayed:
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
            proc = _run([
                sys.executable, str(SCRIPT),
                "--plan", str(plan),
                "--out", str(claims_path),
            ])
            self.assertEqual(proc.returncode, 0, proc.stderr)
            doc = json.loads(claims_path.read_text())
            reviews = doc["coordinator"]["classification_reviews"]
            self.assertTrue(all(row["decision"] == "accept" for row in reviews))
            titles = [row for row in reviews if "Weekly Sales Snapshot" in json.dumps(row)]
            # Title occurrence is not a dollar/% so it stays structural.
            structural = [row for row in reviews if row["final_classification"] == "structural_context"]
            material = [row for row in reviews if row["final_classification"] == "material_claim"]
            self.assertGreater(len(structural), 0)
            self.assertGreater(len(material), 0)
            self.assertEqual(len(doc["claims"]), len(material))
            self.assertEqual(doc["coordinator"]["claim_dependencies"], [])

    def test_packaged_plugin_copy_matches(self) -> None:
        self.assertEqual(SCRIPT.read_bytes(), PACKAGED.read_bytes())
