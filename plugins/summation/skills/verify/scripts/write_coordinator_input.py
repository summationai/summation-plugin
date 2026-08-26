#!/usr/bin/env python3
"""Assemble the coordinator semantic-plan input from claim-taker files.

Does not classify, merge claims, or decide source relevance.

Usage:
    python3 write_coordinator_input.py \
      --findings findings.json \
      --role-outputs run/role-outputs \
      --evidence run/evidence \
      --out run/role-inputs/coordinator-semantic-plan.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys

WORKFLOW_VERSION = "verify-role-handoff/coordinator-v6"


def _sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--findings", required=True, type=pathlib.Path)
    ap.add_argument("--role-outputs", required=True, type=pathlib.Path)
    ap.add_argument("--evidence", required=True, type=pathlib.Path)
    ap.add_argument("--out", required=True, type=pathlib.Path)
    args = ap.parse_args()
    if not args.findings.is_file():
        print(f"write_coordinator_input: missing {args.findings}", file=sys.stderr)
        return 2
    if not args.role_outputs.is_dir():
        print(f"write_coordinator_input: missing {args.role_outputs}", file=sys.stderr)
        return 2
    findings = json.loads(args.findings.read_text())
    partitions = []
    for path in sorted(args.role_outputs.glob("*.json")):
        payload = json.loads(path.read_text())
        if not isinstance(payload, dict):
            print(f"write_coordinator_input: {path.name} is not an object", file=sys.stderr)
            return 2
        if payload.get("role") == "claim_taker" or payload.get("stage") == "claim_taking":
            partitions.append(payload)
        elif "occurrence_decisions" in payload:
            partitions.append(payload)
    if not partitions:
        print("write_coordinator_input: no claim-taker outputs in --role-outputs", file=sys.stderr)
        return 2
    sources = []
    if args.evidence.is_dir():
        for path in sorted(args.evidence.iterdir()):
            if path.is_file() and not path.name.startswith("."):
                sources.append({
                    "id": f"SRC-{path.stem}",
                    "kind": "supplied_file",
                    "evidence_file": str(path.name),
                    "result_sha256": _sha256(path),
                })
    source = findings.get("source") or {}
    bundle = {
        "contract_version": WORKFLOW_VERSION,
        "role": "coordinator",
        "stage": "coordinator_semantic_plan",
        "partition_results": partitions,
        "inventory": findings.get("inventory") or {},
        "report_metadata": {
            "source_path": source.get("path"),
            "format": source.get("format"),
        },
        "internal_candidates": findings.get("internal_candidates") or [],
        "approved_source_manifest": sources,
    }
    dest = args.out.resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(bundle, indent=2) + "\n")
    print(str(dest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
