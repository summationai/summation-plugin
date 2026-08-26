#!/usr/bin/env python3
"""Split findings.json inventory by machine kind into claim-taker input files.

Does not classify titles, owners, dates, or claims. Each item stays unclassified.

Usage:
    python3 write_claim_taker_inputs.py \
      --findings findings.json \
      --visible report-visible.txt \
      --dir run/role-inputs
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

WORKFLOW_VERSION = "verify-role-handoff/coordinator-v6"
KIND_RE = re.compile(r"^[a-z0-9][a-z0-9_]*$")


def _kind_stem(kind: str) -> str:
    return kind.replace("_", "-")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--findings", required=True, type=pathlib.Path)
    ap.add_argument("--visible", required=True, type=pathlib.Path)
    ap.add_argument("--dir", required=True, type=pathlib.Path)
    args = ap.parse_args()
    if not args.findings.is_file():
        print(f"write_claim_taker_inputs: missing {args.findings}", file=sys.stderr)
        return 2
    if not args.visible.is_file():
        print(f"write_claim_taker_inputs: missing {args.visible}", file=sys.stderr)
        return 2
    findings = json.loads(args.findings.read_text())
    items = ((findings.get("inventory") or {}).get("items") or [])
    if not isinstance(items, list) or not items:
        print("write_claim_taker_inputs: inventory.items must be a non-empty list", file=sys.stderr)
        return 2
    visible = args.visible.read_text()
    source = findings.get("source") or {}
    groups: dict[str, list] = {}
    for item in items:
        if not isinstance(item, dict):
            print("write_claim_taker_inputs: inventory item is not an object", file=sys.stderr)
            return 2
        kind = str(item.get("kind") or "").strip()
        if not KIND_RE.match(kind):
            print(f"write_claim_taker_inputs: bad inventory kind {kind!r}", file=sys.stderr)
            return 2
        groups.setdefault(kind, []).append(item)
    out_dir = args.dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for kind, group in groups.items():
        partition_id = _kind_stem(kind)
        dest = (out_dir / f"claim-taker-{partition_id}.json").resolve()
        if dest.parent != out_dir:
            print("write_claim_taker_inputs: refused path outside --dir", file=sys.stderr)
            return 2
        bundle = {
            "contract_version": WORKFLOW_VERSION,
            "role": "claim_taker",
            "stage": "claim_taking",
            "partition_id": partition_id,
            "visible_text": visible,
            "inventory": {"items": group},
            "report_metadata": {
                "source_path": source.get("path"),
                "format": source.get("format"),
            },
        }
        dest.write_text(json.dumps(bundle, indent=2) + "\n")
        written.append(str(dest))
    for path in written:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
