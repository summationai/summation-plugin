#!/usr/bin/env python3
"""Write local git evidence for evaluation setup. Not user-facing.

Usage:
    git_evidence.py --repo PATH --out git-evidence.json
"""
from __future__ import annotations

import argparse
import json
import pathlib
import subprocess


def _git(repo: pathlib.Path, *args: str) -> tuple[int, str]:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
    )
    return proc.returncode, (proc.stdout or "").strip()


def collect(repo: pathlib.Path) -> dict:
    head_code, head = _git(repo, "rev-parse", "HEAD")
    branch_code, branch = _git(repo, "branch", "--show-current")
    status_code, porcelain = _git(repo, "status", "--porcelain=v1")
    up_code, upstream = _git(repo, "rev-parse", "--abbrev-ref", "@{upstream}")
    contained = None
    unpushed = None
    if up_code == 0 and upstream:
        anc_code, _ = _git(repo, "merge-base", "--is-ancestor", "HEAD", upstream)
        contained = anc_code == 0
        count_code, count = _git(repo, "rev-list", "--count", f"{upstream}..HEAD")
        if count_code == 0:
            try:
                unpushed = int(count)
            except ValueError:
                unpushed = None
    return {
        "repo": str(repo),
        "head": head if head_code == 0 else None,
        "branch": branch if branch_code == 0 else None,
        "status_porcelain": porcelain if status_code == 0 else None,
        "worktree_clean": status_code == 0 and porcelain == "",
        "upstream": upstream if up_code == 0 else None,
        "contained_in_upstream": contained,
        "unpushed_commit_count": unpushed,
        "local_only": up_code != 0 or (unpushed or 0) > 0,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", required=True, type=pathlib.Path)
    ap.add_argument("--out", required=True, type=pathlib.Path)
    args = ap.parse_args()
    if not args.repo.is_dir():
        print(f"git_evidence: missing repo {args.repo}", flush=True)
        return 2
    payload = collect(args.repo)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n")
    print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
