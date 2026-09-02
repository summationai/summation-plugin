"""Install the onboarding skill and grader from inside the package.

Distributed as a named package with a console script — not a piped install script —
because a named package is one the person can inspect, pin, and uninstall, and the
files it writes are auditable and reversible. That is the honest reason: installs you
can see and undo, not installs you have to trust.

    uv tool install summation-onboard      # or pipx / pip
    summation-onboard-install

Writes:
  ~/.claude/skills/summation-onboard/     the skill and its output format
  ~/.summation-onboard/grader/            the grader the skill invokes
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

PAYLOAD = Path(__file__).resolve().parent / "payload"
SKILL_DEST = Path.home() / ".claude" / "skills" / "summation-onboard"
TOOL_DEST = Path.home() / ".summation-onboard"


def _copy(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst) if dst.is_dir() else dst.unlink()
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst) if src.is_dir() else shutil.copy2(src, dst)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="summation-onboard-install")
    ap.add_argument("--check", action="store_true",
                    help="report what would be written; change nothing")
    args = ap.parse_args(argv)

    if not PAYLOAD.is_dir():
        print("install: package payload missing — reinstall summation-onboard", file=sys.stderr)
        return 1

    plan = [
        (PAYLOAD / "summation-onboard", SKILL_DEST, "skill + output format"),
        (PAYLOAD / "grader", TOOL_DEST / "grader", "report grader"),
        (PAYLOAD / "grade_artifact", TOOL_DEST / "grade_artifact", "artifact renderer"),
        (PAYLOAD / "layer2", TOOL_DEST / "layer2", "semantic-review contract"),
        (PAYLOAD / "install-check.sh", TOOL_DEST / "install-check.sh", "read-only setup check"),
    ]
    for src, dst, what in plan:
        if not src.exists():
            continue
        if args.check:
            print(f"  would write {dst}  ({what})")
            continue
        _copy(src, dst)
        print(f"  {what}: {dst}")

    if args.check:
        print("Nothing changed. Run without --check to install.")
        return 0

    try:
        import jsonschema  # noqa: F401
    except ImportError:
        print("  note: jsonschema is a declared dependency but is not importable —"
              " the artifact renderer will fail until it is present", file=sys.stderr)

    print(f"Done. Read {SKILL_DEST / 'SKILL.md'} and follow it —"
          " it is the contract for this session.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
