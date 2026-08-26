#!/usr/bin/env python3
"""Write claims.json by accepting claim-taker decisions as-is.

Does not invent title/claim classifications. Each material clause becomes
one canonical claim. Supporting-provenance occurrences become supporting
claims. Source pairs default to consider for material claims only.
Dependencies stay empty. Also writes a temporary checks.json (sources,
empty checks) so semantic-plan preflight and write_verifier_inputs.py
do not require the host to copy that shape from accept.py.

Usage:
    python3 write_claims_json.py \
      --plan run/role-inputs/coordinator-semantic-plan.json \
      --out run/claims.json \
      --checks run/checks.json
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

WORKFLOW_VERSION = "verify-role-handoff/coordinator-v6"
ACCEPT_REASON = "Accept the claim-taker classification as written."
SUPPORTING_REASON = (
    "Accept the claim-taker supporting_provenance classification as written."
)


def _substantive_reason(value, fallback: str) -> str:
    text = str(value or "").strip()
    words = text.replace("%", " ").replace("$", " ").split()
    if len(words) >= 6 and text.endswith((".", "!", "?")):
        return text
    return fallback


def _as_span(span, quote: str) -> dict:
    start = end = None
    if isinstance(span, dict):
        start = span.get("start")
        end = span.get("end")
    elif isinstance(span, (list, tuple)) and len(span) == 2:
        start, end = span[0], span[1]
    if isinstance(start, bool) or isinstance(end, bool):
        start = end = None
    if isinstance(start, int) and isinstance(end, int) and end > start >= 0:
        return {"start": start, "end": end}
    if quote:
        return {"start": 0, "end": len(quote)}
    return {"start": 0, "end": 0}


def _normalize_partitions(partitions: list) -> list:
    out = []
    for part in partitions:
        if not isinstance(part, dict):
            continue
        cloned = json.loads(json.dumps(part))
        clauses = []
        for clause in cloned.get("clauses") or []:
            if not isinstance(clause, dict):
                continue
            quote = str(clause.get("quote") or "")
            clause["span"] = _as_span(clause.get("span"), quote)
            clauses.append(clause)
        cloned["clauses"] = clauses
        decisions = []
        for decision in cloned.get("occurrence_decisions") or []:
            if not isinstance(decision, dict):
                continue
            decision["reason"] = _substantive_reason(
                decision.get("reason"), ACCEPT_REASON
            )
            decisions.append(decision)
        cloned["occurrence_decisions"] = decisions
        out.append(cloned)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--plan", required=True, type=pathlib.Path)
    ap.add_argument("--out", required=True, type=pathlib.Path)
    ap.add_argument("--checks", type=pathlib.Path, default=None)
    args = ap.parse_args()
    if not args.plan.is_file():
        print(f"write_claims_json: missing {args.plan}", file=sys.stderr)
        return 2
    plan = json.loads(args.plan.read_text())
    partitions = _normalize_partitions(plan.get("partition_results") or [])
    if not partitions:
        print("write_claims_json: partition_results must be a non-empty list", file=sys.stderr)
        return 2
    inventory_by_id = {}
    for item in ((plan.get("inventory") or {}).get("items") or []):
        if isinstance(item, dict) and item.get("id"):
            inventory_by_id[str(item["id"])] = item
    reviews = []
    claims = []
    clause_by_id = {}
    supporting_n = 0
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
                "reason": ACCEPT_REASON,
                "accepted_clause_ids": clause_ids,
            })
            if classification == "material_claim":
                for clause_id in clause_ids:
                    clause = clause_by_id.get(clause_id) or {}
                    quote = str(clause.get("quote") or "").strip()
                    label = str(clause.get("public_label") or clause_id)
                    occ = str(clause.get("occurrence_id") or occurrence_id)
                    claims.append({
                        "id": f"L-{sum(1 for c in claims if c['classification']=='material_claim')+1}",
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
                        "context_occurrence_ids": list(
                            clause.get("context_occurrence_ids") or []
                        ),
                        "population_requirements": [],
                    })
            elif classification == "supporting_provenance":
                item = inventory_by_id.get(occurrence_id) or {}
                quote = ""
                label = occurrence_id
                if clause_ids:
                    clause = clause_by_id.get(clause_ids[0]) or {}
                    quote = str(clause.get("quote") or "").strip()
                    label = str(clause.get("public_label") or quote or occurrence_id)
                if not quote:
                    quote = str(item.get("quote") or item.get("displayed") or "").strip()
                    label = quote or occurrence_id
                reason = _substantive_reason(decision.get("reason"), SUPPORTING_REASON)
                supporting_n += 1
                claims.append({
                    "id": f"S-{supporting_n}",
                    "quote": quote,
                    "public_label": label,
                    "importance": "supporting",
                    "classification": "supporting_provenance",
                    "analytical_role": "supporting_provenance",
                    "occurrence_ids": [occurrence_id],
                    "inventory_ids": [occurrence_id],
                    "reason": reason,
                })
    material_claims = [
        claim for claim in claims if claim.get("classification") == "material_claim"
    ]
    sources = []
    for source in plan.get("approved_source_manifest") or []:
        if not isinstance(source, dict):
            continue
        source_id = str(source.get("id") or "").strip()
        if not source_id:
            continue
        evidence_file = str(source.get("evidence_file") or "").strip()
        row = {
            "id": source_id,
            "kind": str(source.get("kind") or "supplied_file"),
            "evidence_file": evidence_file,
            "result_sha256": str(source.get("result_sha256") or ""),
            "label": str(source.get("label") or evidence_file or source_id),
        }
        sources.append(row)
    source_plan = []
    for source in sources:
        for claim in material_claims:
            source_plan.append({
                "source_id": source["id"],
                "claim_id": claim["id"],
                "decision": "consider",
                "reason": "This supplied file was approved for the current run.",
            })
    assignments = [
        {"verifier_id": f"V-{index+1}", "claim_ids": [claim["id"]]}
        for index, claim in enumerate(material_claims)
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
    checks_path = (args.checks or dest.with_name("checks.json")).resolve()
    checks_path.parent.mkdir(parents=True, exist_ok=True)
    checks_path.write_text(json.dumps({
        "contract_version": WORKFLOW_VERSION,
        "sources": sources,
        "checks": [],
    }, indent=2) + "\n")
    print(str(checks_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
