#!/usr/bin/env python3
"""Write one role output JSON file under run/role-outputs/. Chat is not a role output.

Usage:
    python3 write_role_output.py --dir run/role-outputs --name claim-taker-narrative --json bundle.json
    python3 write_role_output.py --dir run/role-outputs --name claim-taker-narrative --stdin < bundle.json
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dir", required=True, type=pathlib.Path)
    ap.add_argument("--name", required=True)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--json", type=pathlib.Path)
    src.add_argument("--stdin", action="store_true")
    args = ap.parse_args()
    if not NAME_RE.match(args.name):
        print("write_role_output: --name must be a short file stem", file=sys.stderr)
        return 2
    out_dir = args.dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = (out_dir / f"{args.name}.json").resolve()
    if dest.parent != out_dir:
        print("write_role_output: refused path outside --dir", file=sys.stderr)
        return 2
    if args.stdin:
        raw = sys.stdin.read()
    else:
        if not args.json.is_file():
            print(f"write_role_output: missing {args.json}", file=sys.stderr)
            return 2
        raw = args.json.read_text()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"write_role_output: invalid JSON: {exc}", file=sys.stderr)
        return 2
    if not isinstance(payload, dict):
        print("write_role_output: top-level JSON must be an object", file=sys.stderr)
        return 2
    dest.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(str(dest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
