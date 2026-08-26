"""Skill text must tell each role to write a JSON file and stop."""
from __future__ import annotations

import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
NEEDLE_SKILL = (
    "Each role writes its entire output as one JSON file under `run/role-outputs/`"
)
NEEDLE_STOP = "Do not paste the bundle into chat."
NEEDLE_ROLES = (
    "The output JSON is a file under `run/role-outputs/`. Write it with `write_role_output.py`, then stop."
)
NEEDLE_CLAIM = (
    "Write that object with `write_role_output.py` to `run/role-outputs/` named for this partition, then stop."
)
NEEDLE_EXTRACT_FIRST = (
    "Run `extract.py` now. Do not read `accept.py`, `render.py`, or `role-contracts.json` before `findings.json`"
)
NEEDLE_NO_DISK_SEARCH = "Do not search the disk."
NEEDLE_NO_ACCEPT_UNTIL_ROLE_FILE = (
    "Do not read `accept.py` or `role-contracts.json` until at least one file exists in `run/role-outputs/`"
)


class RoleOutputFileInstructionTests(unittest.TestCase):
    def test_shipped_skill_requires_role_output_files_not_chat(self) -> None:
        skill = (ROOT / "skills/verify/SKILL.md").read_text()
        self.assertIn(NEEDLE_SKILL, skill)
        self.assertIn(NEEDLE_STOP, skill)

    def test_first_two_minutes_run_extract_before_reading_accept(self) -> None:
        skill = (ROOT / "skills/verify/SKILL.md").read_text()
        first = skill.split("## Run directory", 1)[0]
        self.assertIn(NEEDLE_EXTRACT_FIRST, first)
        self.assertIn(NEEDLE_NO_DISK_SEARCH, first)
        self.assertIn(NEEDLE_NO_ACCEPT_UNTIL_ROLE_FILE, first)
        self.assertNotIn("nine-stage private", first)

    def test_shipped_roles_require_write_file_then_stop(self) -> None:
        roles = (ROOT / "skills/verify/references/roles.md").read_text()
        self.assertIn(NEEDLE_ROLES, roles)
        self.assertIn(NEEDLE_CLAIM, roles)
        self.assertIn(NEEDLE_STOP, roles)

    def test_packaged_plugin_copy_matches_canonical_skill_text(self) -> None:
        for rel in (
            "skills/verify/SKILL.md",
            "skills/verify/references/roles.md",
        ):
            canonical = (ROOT / rel).read_bytes()
            packaged = (ROOT / "plugins/summation" / rel).read_bytes()
            self.assertEqual(canonical, packaged, rel)
