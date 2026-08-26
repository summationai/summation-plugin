"""Customer-path skill text is a direct analyst skill, not a role DAG."""
from __future__ import annotations

import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
NEEDLE_EXTRACT = "`extract.py`"
NEEDLE_PAGE = "`page.py`"
NEEDLE_NO_DISK = "Do not search the disk."
NEEDLE_GRADE = "Write `run/grade.json`."
NEEDLE_PERIOD = "`report_period`"
NEEDLE_COUNT = "The summary count of material outcomes must match the `cards` array."
BANNED = (
    "write_claim_taker_inputs.py",
    "write_coordinator_input.py",
    "write_claims_json.py",
    "write_verifier_inputs.py",
    "coordinator-v6",
)


class AnalystSkillInstructionTests(unittest.TestCase):
    def test_local_grade_is_extract_then_grade_then_page(self) -> None:
        skill = (ROOT / "skills/verify/SKILL.md").read_text()
        local = skill.split("## Connected path", 1)[0]
        self.assertIn(NEEDLE_EXTRACT, local)
        self.assertIn(NEEDLE_PAGE, local)
        self.assertIn(NEEDLE_NO_DISK, local)
        self.assertIn(NEEDLE_GRADE, local)
        self.assertIn(NEEDLE_PERIOD, local)
        self.assertIn(NEEDLE_COUNT, local)
        self.assertIn("If you wrote two cards, do not write four metrics", local)
        self.assertIn("The lead sentence count must match the number of cards", skill)
        for banned in BANNED:
            self.assertNotIn(banned, local)

    def test_packaged_plugin_copy_matches_canonical_skill_text(self) -> None:
        for rel in (
            "skills/verify/SKILL.md",
            "skills/verify/references/roles.md",
        ):
            canonical = (ROOT / rel).read_bytes()
            packaged = (ROOT / "plugins/summation" / rel).read_bytes()
            self.assertEqual(canonical, packaged, rel)

    def test_packaged_plugin_does_not_ship_overlay_helpers(self) -> None:
        scripts = ROOT / "plugins/summation/skills/verify/scripts"
        self.assertTrue((scripts / "page.py").is_file())
        self.assertTrue((scripts / "extract.py").is_file())
        for name in (
            "write_claim_taker_inputs.py",
            "write_coordinator_input.py",
            "write_claims_json.py",
            "write_role_output.py",
            "write_verifier_inputs.py",
        ):
            self.assertFalse((scripts / name).is_file(), name)
