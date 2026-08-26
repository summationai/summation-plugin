#!/usr/bin/env python3
"""Write evidence-verifier input files from claims.json.

Does not author assessments, verdicts, or public receipts.
First wave = claims that are not downstream of another claim.

Usage:
    python3 write_verifier_inputs.py \
      --claims run/claims.json \
      --visible run/report-visible.txt \
      --checks run/checks.json \
      --dir run/role-inputs
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

WORKFLOW_VERSION = "verify-role-handoff/coordinator-v6"
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--claims", required=True, type=pathlib.Path)
    ap.add_argument("--visible", required=True, type=pathlib.Path)
    ap.add_argument("--checks", required=True, type=pathlib.Path)
    ap.add_argument("--dir", required=True, type=pathlib.Path)
    args = ap.parse_args()
    for path in (args.claims, args.visible, args.checks):
        if not path.is_file():
            print(f"write_verifier_inputs: missing {path}", file=sys.stderr)
            return 2
    claims_doc = json.loads(args.claims.read_text())
    checks_doc = json.loads(args.checks.read_text())
    visible = args.visible.read_text()
    claims = claims_doc.get("claims") or []
    coordinator = claims_doc.get("coordinator") or {}
    assignments = coordinator.get("verifier_assignments") or []
    deps = coordinator.get("claim_dependencies") or []
    source_plan = coordinator.get("source_consideration_plan") or []
    sources = {str(row.get("id") or ""): row for row in (checks_doc.get("sources") or []) if isinstance(row, dict)}
    downstream = {
        str(row.get("downstream_claim_id") or "")
        for row in deps if isinstance(row, dict)
    }
    claim_by_id = {
        str(row.get("id") or ""): row
        for row in claims if isinstance(row, dict) and row.get("id")
    }
    out_dir = args.dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for assignment in assignments:
        if not isinstance(assignment, dict):
            continue
        verifier_id = str(assignment.get("verifier_id") or "").strip()
        claim_ids = [str(cid) for cid in (assignment.get("claim_ids") or []) if cid]
        if not ID_RE.match(verifier_id) or not claim_ids:
            continue
        if any(cid in downstream for cid in claim_ids):
            continue
        assigned_claims = [claim_by_id[cid] for cid in claim_ids if cid in claim_by_id]
        if not assigned_claims:
            continue
        plan_rows = [
            row for row in source_plan
            if isinstance(row, dict) and str(row.get("claim_id") or "") in claim_ids
        ]
        assigned_sources = []
        seen = set()
        for row in plan_rows:
            if str(row.get("decision") or "") != "consider":
                continue
            source_id = str(row.get("source_id") or "")
            if source_id in seen:
                continue
            seen.add(source_id)
            if source_id in sources:
                assigned_sources.append(sources[source_id])
        dest = (out_dir / f"verifier-{verifier_id}.json").resolve()
        if dest.parent != out_dir:
            print("write_verifier_inputs: refused path outside --dir", file=sys.stderr)
            return 2
        bundle = {
            "contract_version": WORKFLOW_VERSION,
            "role": "evidence_verifier",
            "stage": "dependency_ordered_verification",
            "verifier_id": verifier_id,
            "canonical_claims": assigned_claims,
            "relevant_report_text": visible,
            "assigned_sources": assigned_sources,
            "source_consideration_plan": plan_rows,
            "accepted_upstream_assessment_results": [],
        }
        dest.write_text(json.dumps(bundle, indent=2) + "\n")
        written.append(str(dest))
    if not written:
        print("write_verifier_inputs: no first-wave verifier assignments", file=sys.stderr)
        return 2
    for path in written:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
