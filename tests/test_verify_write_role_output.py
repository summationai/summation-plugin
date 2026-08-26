"""Drive shipped write_role_output.py: a role bundle is a file, not chat."""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills/verify/scripts/write_role_output.py"
PACKAGED = ROOT / "plugins/summation/skills/verify/scripts/write_role_output.py"


class WriteRoleOutputTests(unittest.TestCase):
    def test_writes_object_json_under_role_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = pathlib.Path(tmp) / "role-outputs"
            src = pathlib.Path(tmp) / "bundle.json"
            src.write_text(json.dumps({"partition_id": "narrative", "clauses": []}))
            proc = subprocess.run(
                [sys.executable, str(SCRIPT), "--dir", str(out_dir), "--name", "claim-taker-narrative", "--json", str(src)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            dest = out_dir / "claim-taker-narrative.json"
            self.assertEqual(pathlib.Path(proc.stdout.strip()), dest.resolve())
            self.assertTrue(dest.is_file())
            self.assertEqual(json.loads(dest.read_text())["partition_id"], "narrative")

    def test_invalid_json_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = pathlib.Path(tmp) / "role-outputs"
            src = pathlib.Path(tmp) / "bad.json"
            src.write_text("{not json")
            proc = subprocess.run(
                [sys.executable, str(SCRIPT), "--dir", str(out_dir), "--name", "claim-taker-narrative", "--json", str(src)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 2)
            self.assertFalse((out_dir / "claim-taker-narrative.json").exists())

    def test_path_escape_in_name_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = pathlib.Path(tmp) / "role-outputs"
            src = pathlib.Path(tmp) / "bundle.json"
            src.write_text("{}")
            proc = subprocess.run(
                [sys.executable, str(SCRIPT), "--dir", str(out_dir), "--name", "../escape", "--json", str(src)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 2)

    def test_packaged_plugin_copy_matches(self) -> None:
        self.assertEqual(SCRIPT.read_bytes(), PACKAGED.read_bytes())
