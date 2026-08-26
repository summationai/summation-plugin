"""Drive shipped extract.py then write_claim_taker_inputs.py on the planted HTML fixture."""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
EXTRACT = ROOT / "skills/verify/scripts/extract.py"
SCRIPT = ROOT / "skills/verify/scripts/write_claim_taker_inputs.py"
PACKAGED = ROOT / "plugins/summation/skills/verify/scripts/write_claim_taker_inputs.py"
FIXTURE = ROOT / "tests/fixtures/verify/weekly-sales-snapshot.html"


class WriteClaimTakerInputsTests(unittest.TestCase):
    def test_splits_extracted_inventory_by_kind_without_classifying(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            visible = tmp_path / "report-visible.txt"
            findings = tmp_path / "findings.json"
            inputs_dir = tmp_path / "role-inputs"
            extract = subprocess.run(
                [
                    sys.executable,
                    str(EXTRACT),
                    "--report",
                    str(FIXTURE),
                    "--visible",
                    str(visible),
                    "--out",
                    str(findings),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(extract.returncode, 0, extract.stderr)
            proc = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--findings",
                    str(findings),
                    "--visible",
                    str(visible),
                    "--dir",
                    str(inputs_dir),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            paths = [pathlib.Path(line) for line in proc.stdout.splitlines() if line.strip()]
            self.assertGreaterEqual(len(paths), 2)
            items = json.loads(findings.read_text())["inventory"]["items"]
            seen = []
            for path in paths:
                bundle = json.loads(path.read_text())
                self.assertEqual(bundle["role"], "claim_taker")
                self.assertEqual(bundle["stage"], "claim_taking")
                for item in bundle["inventory"]["items"]:
                    self.assertEqual(item["importance"], "unclassified")
                    seen.append(item["id"])
            self.assertEqual(sorted(seen), sorted(row["id"] for row in items))
            self.assertEqual(len(seen), len(set(seen)))

    def test_packaged_plugin_copy_matches(self) -> None:
        self.assertFalse(PACKAGED.is_file())
