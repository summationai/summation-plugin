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
    "The output JSON is a file under `run/role-outputs/`. Write that file, then stop."
)
NEEDLE_CLAIM = (
    "Write that object as one JSON file under `run/role-outputs/` named for this partition, then stop."
)


class RoleOutputFileInstructionTests(unittest.TestCase):
    def test_shipped_skill_requires_role_output_files_not_chat(self) -> None:
        skill = (ROOT / "skills/verify/SKILL.md").read_text()
        self.assertIn(NEEDLE_SKILL, skill)
        self.assertIn(NEEDLE_STOP, skill)

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
