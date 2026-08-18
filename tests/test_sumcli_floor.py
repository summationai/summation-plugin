"""Guard: prose CLI floors must match hooks/sumcli.json minVersion."""
from __future__ import annotations

import json
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "packaging" / "com.anthropic.claude" / "hooks" / "sumcli.json"

# Lines that declare a sumcli version floor. A stale copy in a skill has
# agents installing a version the SessionStart hook then rejects.
_FLOOR = re.compile(
    r"(?:"
    r"sumcli\s*[≥>=]{1,2}\s*"
    r"|Need \*\*≥\s*"
    r"|Plugin minimum is \*\*"
    r"|Present but `< "
    r"|Already ≥ "
    r"|minVersion "
    r")(\d+\.\d+\.\d+)"
)

_SCAN = (
    ROOT / "README.md",
    ROOT / "skills" / "sumcli" / "SKILL.md",
    ROOT / "skills" / "api" / "SKILL.md",
    ROOT / "skills" / "api" / "references" / "sumcli.md",
    ROOT / "skills" / "diagnose" / "SKILL.md",
    ROOT / "skills" / "start" / "SKILL.md",
    ROOT / "packaging" / "com.anthropic.claude" / "hooks" / "ensure_sumcli.py",
)


class FloorProseTests(unittest.TestCase):
    def test_prose_floors_match_contract(self) -> None:
        floor = json.loads(CONTRACT.read_text(encoding="utf-8"))["minVersion"]
        self.assertRegex(floor, r"^\d+\.\d+\.\d+$")
        found = 0
        for path in _SCAN:
            text = path.read_text(encoding="utf-8")
            for match in _FLOOR.finditer(text):
                found += 1
                self.assertEqual(
                    match.group(1),
                    floor,
                    f"{path.relative_to(ROOT)} states {match.group(0)!r}; "
                    f"hooks/sumcli.json minVersion is {floor}",
                )
        self.assertGreater(found, 0, "expected at least one prose floor to check")


if __name__ == "__main__":
    unittest.main()
