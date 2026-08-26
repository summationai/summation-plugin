#!/usr/bin/env python3
"""Write claims.json by accepting claim-taker decisions as-is.

Does not invent title/claim classifications. Each material clause becomes
one canonical claim. Source pairs default to consider for approved files.
Dependencies stay empty.

Usage:
    python3 write_claims_json.py \
      --plan run/role-inputs/coordinator-semantic-plan.json \
      --out run/claims.json
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

WORKFLOW_VERSION = "verify-role-handoff/coordinator-v6"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--plan", required=True, type=pathlib.Path)
    ap.add_argument("--out", required=True, type=pathlib.Path)
    args = ap.parse_args()
    if not args.plan.is_file():
        print(f"write_claims_json: missing {args.plan}", file=sys.stderr)
        return 2
    plan = json.loads(args.plan.read_text())
    partitions = plan.get("partition_results") or []
    if not isinstance(partitions, list) or not partitions:
        print("write_claims_json: partition_results must be a non-empty list", file=sys.stderr)
        return 2
    reviews = []
    claims = []
    clause_by_id = {}
    for part in partitions:
        partition_id = str(part.get("partition_id") or "").strip() or "partition"
        for clause in part.get("clauses") or []:
            if isinstance(clause, dict) and clause.get("id"):
                clause_by_id[str(clause["id"])] = clause
        for decision in part.get("occurrence_decisions") or []:
            if not isinstance(decision, dict):
                continue
            occurrence_id = str(decision.get("occurrence_id") or "").strip()
            classification = str(decision.get("classification") or "").strip()
            analytical_role = str(decision.get("analytical_role") or "").strip()
            clause_ids = [str(cid) for cid in (decision.get("clause_ids") or []) if cid]
            reviews.append({
                "occurrence_id": occurrence_id,
                "claim_taker_partition_id": partition_id,
                "proposed_classification": classification,
                "final_classification": classification,
                "analytical_role": analytical_role,
                "decision": "accept",
                "reason": "Accept the claim-taker classification as written.",
                "accepted_clause_ids": clause_ids,
            })
            if classification != "material_claim":
                continue
            for clause_id in clause_ids:
                clause = clause_by_id.get(clause_id) or {}
                quote = str(clause.get("quote") or "").strip()
                label = str(clause.get("public_label") or clause_id)
                occ = str(clause.get("occurrence_id") or occurrence_id)
                claims.append({
                    "id": f"L-{len(claims)+1}",
                    "quote": quote,
                    "primary_quote": quote,
                    "public_label": label,
                    "importance": "material",
                    "classification": "material_claim",
                    "analytical_role": "load_bearing_analytical_assertion",
                    "primary_clause_id": clause_id,
                    "member_clause_ids": [clause_id],
                    "occurrence_ids": [occ],
                    "inventory_ids": [occ],
                    "context_occurrence_ids": list(clause.get("context_occurrence_ids") or []),
                    "population_requirements": [],
                })
    sources = plan.get("approved_source_manifest") or []
    source_plan = []
    for source in sources:
        source_id = str(source.get("id") or "").strip()
        if not source_id:
            continue
        for claim in claims:
            source_plan.append({
                "source_id": source_id,
                "claim_id": claim["id"],
                "decision": "consider",
                "reason": "This supplied file was approved for the current run.",
            })
    assignments = [
        {"verifier_id": f"V-{index+1}", "claim_ids": [claim["id"]]}
        for index, claim in enumerate(claims)
    ]
    coordinator = {
        "classification_reviews": reviews,
        "canonical_claims": claims,
        "source_consideration_plan": source_plan,
        "claim_dependencies": [],
        "verifier_assignments": assignments,
        "partition_results": partitions,
    }
    payload = {
        "contract_version": WORKFLOW_VERSION,
        "claims": claims,
        "coordinator": coordinator,
    }
    dest = args.out.resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(payload, indent=2) + "\n")
    print(str(dest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
