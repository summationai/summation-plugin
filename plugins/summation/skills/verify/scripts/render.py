#!/usr/bin/env python3
"""Render grade-artifact/v1 from coldverify findings.json. Fail closed."""
from __future__ import annotations

import argparse
from decimal import Decimal, InvalidOperation
import hashlib
import html
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = "grade-artifact/v1"
MIN_CLAIMS = 1
SHAREABLE_CHECK_KEYS = (
    "id", "type", "basis", "verdict", "importance", "severity",
    "report_quote", "report_quote_2", "explanation", "claim_id",
    "location", "metric_label",
)
CLAIM_PUBLIC_KEYS = (
    "id", "quote", "importance", "outcome", "check_id", "found_by",
    "location", "inventory_ids",
)
GROUNDED_OUTCOMES = frozenset({
    "confirmed", "contradicted", "not_checkable", "changed_since_report", "error",
})
UNFINISHED_SEMANTIC = frozenset({"not_run", "failed", "skipped"})
REQUIRED = (
    "schema_version",
    "run_id",
    "generated_at",
    "source",
    "source_result",
    "verdict",
    "score",
    "findings",
    "evidence_checks",
    "evidence_findings",
    "evidence_coverage",
    "decision",
    "actions",
    "decision_limits",
    "diagnostics",
    "checks",
    "verification",
    "limitations",
    "offer",
    "claims",
)
VERDICTS = frozenset(
    {"safe_to_share", "share_with_caveats", "fix_first", "unable_to_grade"}
)
PUBLIC_VERDICTS = VERDICTS
MATERIAL_REPORT_ONLY_TYPES = frozenset(
    {"internal", "logic", "arithmetic", "units", "selection"}
)
CUSTOMER_CHECK_IDS = frozenset({
    "ari_total_footing",
    "ari_total_footing_precision",
    "uni_percent_vs_points",
    "per_period_misaligned",
    "sel_order_violated",
    "gnd_ungrounded_claim",
})


def coverage(raw: dict) -> dict:
    return raw.get("coverage") or {}


def claim_count(raw: dict) -> int:
    return int(coverage(raw).get("claims_in_ledger") or 0)


def coverage_ok(raw: dict) -> bool:
    cov = coverage(raw)
    if int(cov.get("checks_errored") or 0) != 0:
        return False
    if raw.get("findings_truncated"):
        return False
    inv = raw.get("inventory") or {}
    if inv.get("complete"):
        if raw.get("inventory_missing"):
            return False
        n = int(cov.get("inventory_material") or 0)
        if n == 0:
            n = sum(
                1 for item in (inv.get("items") or [])
                if item.get("importance") == "material")
        if n == 0:
            return False
        ext = cov.get("extractor_checkable_fraction")
        eng = cov.get("engine_checkable_fraction")
        return (
            isinstance(ext, (int, float)) and ext >= 1
            and isinstance(eng, (int, float)) and eng >= 1
        )
    claims = claim_count(raw)
    reached = int(cov.get("claims_reached_by_a_check") or 0)
    if claims < MIN_CLAIMS:
        return False
    if reached < claims:
        return False
    return True


def _is_diagnostic_record(f: dict) -> bool:
    """True when a finding describes scanner coverage, not a report defect."""
    cid = str(f.get("check_id") or "")
    return cid not in CUSTOMER_CHECK_IDS


def verdict_of(raw: dict) -> str:
    if not isinstance(raw, dict) or "findings" not in raw:
        return "unable_to_grade"
    findings = raw.get("findings")
    if not isinstance(findings, list):
        return "unable_to_grade"
    inv = raw.get("inventory") or {}
    if raw.get("intake_error") and not inv.get("complete"):
        return "unable_to_grade"
    if (raw.get("agentic_only") and not raw.get("agentic_scan_completed")
            and not inv.get("complete")):
        return "unable_to_grade"
    tiers = {str(f.get("tier")) for f in findings if not _is_diagnostic_record(f)}
    if "D" in tiers:
        return "fix_first"
    if inv.get("complete"):
        if not coverage_ok(raw):
            return "needs_review"
        if "C" in tiers:
            return "share_with_caveats"
        return "safe_to_share"
    if claim_count(raw) < MIN_CLAIMS:
        return "unable_to_grade"
    if not coverage_ok(raw):
        return "needs_review"
    return "share_with_caveats"


def limitations_of(raw: dict) -> list[str]:
    if raw.get("agentic_only"):
        method = raw.get("extraction_method") or "a format adapter"
        deterministic_error = raw.get("deterministic_error")
        if deterministic_error:
            if raw.get("agentic_scan_completed"):
                return [
                    "The rule-based document checks did not complete.",
                    f"Visible content was extracted with {method} and read by the semantic verifier.",
                ]
            return [
                "The rule-based document checks did not complete.",
                "The semantic review did not complete. No substantive assessment was produced.",
            ]
        if raw.get("agentic_scan_completed"):
            return [
                f"Visible content was extracted with {method} and read by the semantic verifier.",
                "Rule-based document checks are not yet available for this file format, so a clean semantic review is still partial.",
            ]
        return [
            f"Visible content was extracted with {method}, but the semantic review was skipped.",
            "No substantive assessment was produced.",
        ]
    if raw.get("intake_error"):
        return [
            str(raw["intake_error"]),
            "No report text was extracted, so no report claim was checked.",
        ]
    out: list[str] = []
    cov = coverage(raw)
    if claim_count(raw) < MIN_CLAIMS:
        out.append("No claims were available to assess.")
    if raw.get("findings_truncated"):
        out.append("Finding list was truncated.")
    frac = cov.get("extractor_checkable_fraction")
    if isinstance(frac, (int, float)) and frac < 1:
        out.append(
            f"Extractor could check {frac:.0%} of inventory figures."
        )
    if cov.get("checks_errored"):
        out.append(f"{cov['checks_errored']} check(s) errored.")
    reached = int(cov.get("claims_reached_by_a_check") or 0)
    claims = claim_count(raw)
    if claims and reached < claims:
        out.append(f"Checks reached {reached} of {claims} claims.")
    eng = cov.get("engine_checkable_fraction")
    if isinstance(eng, (int, float)) and eng < 1:
        out.append("Engine checkable fraction is below the inventory.")
    src = (raw.get("source") or {}).get("format")
    if src and src != "html":
        out.append(f"Source format is {src}. Extraction may be model-written.")
    if not out:
        out.append("Checks ran offline on the document ledger. No warehouse was used.")
    return out


def source_public(raw: dict) -> dict:
    src = raw.get("source") or {}
    raw_path = str(src.get("path") or "")
    return {
        "path": Path(raw_path).name if raw_path else "",
        "format": src.get("format") or "unknown",
        "sha256": src.get("sha256"),
        "period_label": src.get("period_label"),
        "report_date": src.get("report_date"),
    }


def _public_layer2(layer2: list[dict] | None) -> list[dict]:
    public = []
    for f in layer2 or []:
        verdict = str(f.get("verdict") or "")
        row = {
            "id": str(f.get("id") or "L2"),
            "type": str(f.get("type") or "semantic"),
            "basis": str(f.get("basis") or (
                "report" if f.get("type") in MATERIAL_REPORT_ONLY_TYPES else "evidence")),
            "verdict": verdict,
            "importance": str(f.get("importance") or "material"),
            "severity": (str(f.get("severity") or "medium")
                         if verdict == "contradicted" else None),
            "report_quote": str(f.get("report_quote") or ""),
            "report_quote_2": f.get("report_quote_2"),
            "explanation": public_explanation(f),
            "claim_id": f.get("claim_id"),
            "location": f.get("location"),
            "metric_label": f.get("metric_label"),
        }
        public.append({key: row[key] for key in SHAREABLE_CHECK_KEYS if key in row})
    return public


def _has_claim_evidence_receipt(check: dict) -> bool:
    """Recognize the two validated receipt shapes exposed by the artifact."""
    if (check.get("basis") != "evidence"
            or check.get("verdict") not in {
                "confirmed", "contradicted", "changed_since_report"}):
        return False
    single_file = bool(
        check.get("evidence_file")
        and (check.get("evidence_quote") or check.get("evidence_json")))
    multi_file = any(
        receipt.get("evidence_file") and receipt.get("evidence_json")
        for receipt in check.get("evidence_receipts") or []
        if isinstance(receipt, dict)
    )
    return single_file or multi_file


def _evidence_coverage(raw: dict, checks: list[dict]) -> dict:
    supplied = [str(path) for path in raw.get("evidence_files") or []]
    cited_names = set()
    for check in checks:
        if not _has_claim_evidence_receipt(check):
            continue
        if check.get("evidence_file"):
            cited_names.add(str(check["evidence_file"]))
        cited_names.update(
            str(receipt.get("evidence_file"))
            for receipt in check.get("evidence_receipts") or []
            if receipt.get("evidence_file"))
    cited = sorted(cited_names)
    material = [check for check in checks if check.get("importance") == "material"]
    external = [check for check in checks if check.get("basis") == "evidence"]
    internal = [check for check in checks if check.get("basis") == "report"]
    review = raw.get("evidence_review") or {}
    return {
        "document_claims_total": claim_count(raw),
        "document_claims_reached": int(
            coverage(raw).get("claims_reached_by_a_check") or 0),
        "claim_outcomes_proposed": int(
            review.get("outcomes_proposed")
            if review.get("outcomes_proposed") is not None else len(checks)),
        "material_claims_reviewed": len(material),
        "supporting_claims_reviewed": len(checks) - len(material),
        "confirmed": sum(check.get("verdict") == "confirmed" for check in checks),
        "contradicted": sum(check.get("verdict") == "contradicted" for check in checks),
        "not_checkable": sum(check.get("verdict") == "not_checkable" for check in checks),
        "evidence_confirmed": sum(
            check.get("verdict") == "confirmed" for check in external),
        "evidence_contradicted": sum(
            check.get("verdict") == "contradicted" for check in external),
        "evidence_not_checkable": sum(
            check.get("verdict") == "not_checkable" for check in external),
        "report_confirmed": sum(
            check.get("verdict") == "confirmed" for check in internal),
        "report_contradicted": sum(
            check.get("verdict") == "contradicted" for check in internal),
        "report_not_checkable": sum(
            check.get("verdict") == "not_checkable" for check in internal),
        "validated_outcomes": len(checks),
        "receipt_failures": int(review.get("receipt_failures") or 0),
        "evidence_files_supplied": 0,
        "evidence_files_cited": [],
        "provenance_groups": [],
        "source_independence": "not_assessed",
    }


def _public_guidance(guidance: dict | None) -> tuple[dict | None, list[dict], list[dict]]:
    guidance = guidance or {}
    decision_in = guidance.get("decision")
    decision = None
    if isinstance(decision_in, dict):
        decision = {
            "outcome": str(decision_in.get("outcome") or "not_checkable"),
            "text": str(decision_in.get("text") or ""),
            "report_quote": str(decision_in.get("report_quote") or ""),
            "explanation": str(decision_in.get("explanation") or ""),
            "supporting_check_ids": [
                str(item) for item in decision_in.get("supporting_check_ids") or []],
            "key_points": [
                {"check_id": str(item.get("check_id") or ""),
                 "text": str(item.get("text") or "")}
                for item in decision_in.get("key_points") or []
                if isinstance(item, dict)],
            "recommended_action_ids": [
                str(item) for item in decision_in.get("recommended_action_ids") or []],
            "key_limit_ids": [
                str(item) for item in decision_in.get("key_limit_ids") or []],
        }
    def items(name: str) -> list[dict]:
        return [{
            "id": str(item.get("id") or ""),
            "text": str(item.get("text") or ""),
            "report_quote": str(item.get("report_quote") or ""),
        } for item in guidance.get(name) or [] if isinstance(item, dict)]
    return decision, items("actions"), items("limits")


def _public_source_result(source: dict | None) -> dict | None:
    """Shareable JSON never copies a live-source payload."""
    return None


def _public_claim(row: dict) -> dict:
    out = {}
    for key in CLAIM_PUBLIC_KEYS:
        if key in row:
            out[key] = row[key]
    return out


def _verification_public(raw: dict, source: dict | None,
                         layer2: list[dict] | None = None) -> dict:
    supplied = raw.get("verification") or {}
    document = supplied.get("document") or {
        "status": "not_available" if raw.get("agentic_only") else "complete",
        "detail": None,
    }
    semantic = supplied.get("semantic") or {
        "status": "not_run",
        "detail": "No semantic review status was recorded.",
    }
    changed = [
        check for check in (source or {}).get("checks", [])
        if check.get("verdict") == "changed_since_report"
    ]
    current_matches = [
        check for check in (source or {}).get("checks", [])
        if check.get("verdict") == "matches_current_source"
    ]
    changed_detail = (
        f" {len(changed)} current-source difference"
        f"{'s were' if len(changed) != 1 else ' was'} measured after the report's "
        "snapshot date; those differences do not prove the historical claims were wrong."
        if changed else ""
    )
    current_match_detail = (
        f" {len(current_matches)} current value"
        f"{'s still match' if len(current_matches) != 1 else ' still matches'} the dated "
        "report, but a current-only query is not independent historical proof."
        if current_matches else ""
    )
    if source and source.get("status") == "partial":
        live = {
            "status": "partial",
            "detail": str(source.get("error") or "The live source check was incomplete.")
                      + changed_detail + current_match_detail,
        }
    elif source and source.get("status") == "not_applicable":
        live = {
            "status": "not_available",
            "detail": source.get("error"),
        }
    elif source:
        live = {
            "status": "failed" if source.get("status") == "failed" else "complete",
            "detail": (str(source.get("error") or "") + changed_detail
                       + current_match_detail).strip() or None,
        }
    else:
        evidence_files = list(raw.get("evidence_files") or [])
        has_evidence_receipt = any(
            _has_claim_evidence_receipt(finding) for finding in (layer2 or []))
        if has_evidence_receipt:
            detail = (
                "No direct live query ran. Supplied evidence was used for the "
                "receipted outcomes shown in this assessment."
            )
        elif evidence_files:
            count = len(evidence_files)
            detail = (
                f"No direct live query ran. The semantic review received {count} "
                f"supplied evidence file{'s' if count != 1 else ''}, but no "
                "claim-level evidence receipt was produced. Treat this as a fallback assessment."
            )
        else:
            detail = (
                "No direct live query or current evidence check ran. "
                "Treat this as a fallback assessment."
            )
        live = {
            "status": "not_run",
            "detail": detail,
        }
    return {"document": document, "semantic": semantic, "live_source": live}


def _combined_verdict(base: str, layer2: list[dict], source: dict | None) -> str:
    contradicted = [
        check for check in layer2 if check.get("verdict") == "contradicted"]
    if source and source.get("status") != "failed" and int(source.get("contradicted") or 0):
        return "fix_first"
    if any(f.get("severity") in {"high", "medium"} for f in contradicted):
        return "fix_first"
    if contradicted and base == "safe_to_share":
        return "share_with_caveats"
    if any(
        check.get("verdict") == "not_checkable"
        and check.get("importance") == "material"
        for check in layer2
    ) and base in {"safe_to_share", "share_with_caveats"}:
        return "needs_review"
    if (
        any(check.get("verdict") == "changed_since_report" for check in layer2)
        or (
            source and any(
                check.get("verdict") == "changed_since_report"
                for check in source.get("checks") or []
            )
        )
    ) and base in {"safe_to_share", "share_with_caveats"}:
        return "needs_review"
    if source and source.get("status") in {"failed", "partial", "not_applicable"}:
        if base in {"safe_to_share", "share_with_caveats"}:
            return "needs_review"
    return base


def _offer(findings: list[dict], layer2: list[dict], source: dict | None,
           verdict: str, raw: dict) -> str:
    display = customer_verdict(verdict)
    n_err = sum(1 for item in findings or [] if item.get("tier") == "D")
    n_err += sum(1 for item in layer2 or [] if item.get("verdict") == "contradicted")
    if display == "fix_first" or n_err:
        noun = "error" if n_err == 1 else "errors"
        return (
            f"fix the {spell_count(n_err) if n_err else ''} {noun} above, "
            "then have Summation Verify check the report again."
        ).replace("  ", " ")
    return ""


def artifact_from_findings(raw: dict, *, run_id: str, generated_at: str,
                           layer2: list[dict] | None = None,
                           source: dict | None = None,
                           guidance: dict | None = None) -> dict:
    if not isinstance(raw, dict):
        raise SystemExit("render: input is not JSON object")
    findings_in = raw.get("findings") if isinstance(raw.get("findings"), list) else []
    headline = raw.get("headline") or {}
    cov = coverage(raw)
    findings = []
    diagnostics = []
    for f in findings_in:
        public = {
            "check_id": f.get("check_id"),
            "family": f.get("family"),
            "tier": f.get("tier"),
            "severity": f.get("severity"),
            "statement": f.get("statement"),
            "location": f.get("location"),
            "claim_ids": list(f.get("claim_ids") or []),
        }
        detail = f.get("detail")
        if isinstance(detail, dict) and "stated" in detail and "computed" in detail:
            public["arithmetic"] = {
                "stated": detail.get("stated"),
                "computed": detail.get("computed"),
                "discrepancy": detail.get("discrepancy"),
                "addends": [
                    {"label": row.get("label"), "value": row.get("value")}
                    for row in (detail.get("addends") or [])
                    if isinstance(row, dict)
                ],
            }
        if _is_diagnostic_record(f):
            diagnostics.append({
                "check_id": str(f.get("check_id") or "diagnostic"),
                "statement": str(f.get("statement") or ""),
                "location": f.get("location"),
                "severity": f.get("severity"),
            })
        else:
            findings.append(public)
    evidence_checks = _public_layer2(layer2)
    evidence_findings = [
        check for check in evidence_checks
        if check.get("verdict") == "contradicted"
    ]
    evidence_coverage = _evidence_coverage(raw, evidence_checks)
    score = None
    if "tier_d_per_100_claims" in headline:
        score = {
            "kind": "tier_d_per_100_claims",
            "value": headline["tier_d_per_100_claims"],
        }
    verdict = _combined_verdict(verdict_of(raw), list(layer2 or []), source)
    semantic_status = (((raw.get("verification") or {}).get("semantic") or {})
                       .get("status"))
    if semantic_status in {"failed", "not_run", "skipped"} and verdict in {
        "safe_to_share", "share_with_caveats"
    }:
        verdict = "needs_review"
    verdict = public_verdict(verdict)
    art = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "generated_at": generated_at,
        "source": source_public(raw),
        "source_result": None,
        "verdict": verdict,
        "score": score,
        "findings": findings,
        "evidence_checks": evidence_checks,
        "evidence_findings": evidence_findings,
        "evidence_coverage": evidence_coverage,
        "decision": None,
        "actions": [],
        "decision_limits": [],
        "diagnostics": diagnostics,
        "checks": {
            "registered": int(cov.get("checks_registered") or 0),
            "with_findings": int(cov.get("checks_with_findings") or 0),
            "found_nothing": int(cov.get("checks_found_nothing") or 0),
            "errored": int(cov.get("checks_errored") or 0),
            "skipped_note": (
                "Outcome counts come from coverage in findings.json. "
                "Individual check rows are not copied."
            ),
        },
        "verification": _verification_public(raw, source, list(layer2 or [])),
        "limitations": limitations_of(raw),
        "offer": {"text": _offer(findings, evidence_checks, source, verdict, raw),
                  "accepted": None},
        "claims": [_public_claim(row) for row in (raw.get("claims") or [])
                   if isinstance(row, dict)],
    }
    validate_artifact(art)
    return art


def validate_artifact(art: dict) -> None:
    missing = [k for k in REQUIRED if k not in art]
    if missing:
        raise SystemExit(f"render: artifact missing {missing}")
    if art.get("schema_version") != SCHEMA_VERSION:
        raise SystemExit("render: bad schema_version")
    if art.get("verdict") not in VERDICTS:
        raise SystemExit(f"render: bad verdict {art.get('verdict')!r}")
    if not isinstance(art.get("findings"), list):
        raise SystemExit("render: findings must be a list")
    if not isinstance(art.get("source"), dict) or "/" in str(art["source"].get("path") or ""):
        raise SystemExit("render: source.path must be a filename, not a path")
    schema_path = Path(__file__).resolve().parent.parent / "schema.v1.json"
    if not schema_path.is_file():
        raise SystemExit(f"render: missing schema {schema_path}")
    try:
        import jsonschema
    except ImportError as exc:
        raise SystemExit("render: jsonschema is required") from exc
    jsonschema.validate(art, json.loads(schema_path.read_text()))



import re as _re

PAGE_CSS = """
  :root{
    --ink:#191b1e; --ink-2:#4b5158; --ink-3:#787f87;
    --paper:#fdfdfc; --panel:#f4f4f1; --line:#e3e3de;
    --red:#b42318; --red-soft:#fdf0ee;
    --green:#1a7f4b; --green-soft:#eef7f1;
    --amber:#9a5b0b; --amber-soft:#fbf4e8;
    --gray:#5d646c; --gray-soft:#f0f1f2;
  }
  *{box-sizing:border-box;margin:0;padding:0}
  html{-webkit-text-size-adjust:100%}
  body{font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;
    color:var(--ink);background:var(--paper);padding:0 24px 64px}
  .page{max-width:730px;margin:0 auto}
  .num{font-variant-numeric:tabular-nums}
  header{display:flex;justify-content:space-between;align-items:baseline;
    padding:24px 0 14px;border-bottom:1px solid var(--line)}
  .wordmark{font-weight:700;font-size:15px}
  .wordmark span{color:var(--ink-3);font-weight:500}
  .runmeta{font-size:13px;color:var(--ink-3)}
  .verdict{padding:40px 0 8px}
  .chip{display:inline-block;font-size:12px;font-weight:700;letter-spacing:.08em;
    padding:4px 10px;border-radius:4px;margin-bottom:14px}
  .chip.fix{background:var(--red-soft);color:var(--red);border:1px solid #ecc8c3}
  .chip.safe{background:var(--green-soft);color:var(--green);border:1px solid #c6e2d2}
  .chip.warn{background:var(--amber-soft);color:var(--amber);border:1px solid #ecd9b8}
  h1{font-size:31px;line-height:1.15;letter-spacing:-.015em;font-weight:700;max-width:30ch;text-wrap:balance}
  .verdict p{margin-top:12px;font-size:16px;color:var(--ink-2);max-width:60ch;text-wrap:pretty}
  .file{font-size:13px;color:var(--ink-3);margin-top:16px}
  .file code{font:12.5px ui-monospace,SFMono-Regular,Menlo,monospace;background:var(--panel);
    padding:2px 6px;border-radius:4px;color:var(--ink-2);white-space:nowrap}
  .stats{display:grid;grid-template-columns:repeat(4,1fr);border:1px solid var(--line);
    border-radius:8px;overflow:hidden;margin:30px 0 0;background:#fff}
  .stat{padding:16px 18px 14px;border-left:1px solid var(--line)}
  .stat:first-child{border-left:none}
  .stat .n{font-size:26px;font-weight:700;letter-spacing:-.02em}
  .stat .l{font-size:13px;font-weight:600;margin-top:2px}
  .stat .s{font-size:12px;color:var(--ink-3);margin-top:2px;text-wrap:balance}
  .stat .n.na{font-size:14px;color:var(--ink-3);font-weight:600;padding:12px 0 6px}
  .stat.red .l{color:var(--red)} .stat.green .l{color:var(--green)}
  .stat.amber .l{color:var(--amber)} .stat.gray .l{color:var(--gray)}
  section{margin-top:44px}
  h2{font-size:18px;letter-spacing:-.01em;margin-bottom:6px}
  .sectionlede{font-size:14px;color:var(--ink-2);margin-bottom:16px;max-width:62ch}
  .card{border:1px solid var(--line);border-radius:8px;background:#fff;padding:20px 22px}
  .card + .card{margin-top:12px}
  .card .tag{font-size:11.5px;font-weight:700;letter-spacing:.07em;border-radius:4px;
    display:inline-block;padding:3px 8px;margin-bottom:10px}
  .card.err{border-left:3px solid var(--red)}
  .card.err .tag{background:var(--red-soft);color:var(--red)}
  .card.ok{border-left:3px solid var(--green)}
  .card.ok .tag{background:var(--green-soft);color:var(--green)}
  .card.chg{border-left:3px solid var(--amber)}
  .card.chg .tag{background:var(--amber-soft);color:var(--amber)}
  .card h3{font-size:16px;text-wrap:balance}
  .card .where{font-size:13px;color:var(--ink-3);margin-top:2px}
  .card p{font-size:14px;color:var(--ink-2);margin-top:10px;max-width:62ch}
  table.math{margin-top:14px;border-collapse:collapse;font-size:14px;width:100%;max-width:380px}
  table.math td{padding:5px 0}
  table.math td.v{text-align:right;padding-left:24px;font-variant-numeric:tabular-nums;white-space:nowrap}
  table.math tr.sum td{border-top:1px solid var(--line);font-weight:600}
  table.math tr.bad td{color:var(--red);font-weight:700}
  table.math tr.bad td:first-child{font-weight:600}
  .receipt{margin-top:14px;border-top:1px dashed var(--line);padding-top:12px;
    display:grid;grid-template-columns:110px 1fr;row-gap:6px;column-gap:14px;font-size:13px}
  .receipt .k{color:var(--ink-3)}
  .receipt .q{font-variant-numeric:tabular-nums;overflow-wrap:anywhere}
  .receipt .q code{font:12px ui-monospace,SFMono-Regular,Menlo,monospace;background:var(--panel);
    padding:1px 5px;border-radius:3px}
  .machine{font-size:12px;color:var(--ink-3);font-weight:600;margin-top:10px}
  .compare{display:flex;gap:12px;margin-top:14px;flex-wrap:wrap}
  .compare .box{flex:1;min-width:150px;border:1px solid var(--line);border-radius:6px;padding:12px 14px}
  .compare .box .bl{font-size:12px;color:var(--ink-3)}
  .compare .box .bv{font-size:20px;font-weight:700;margin-top:2px;font-variant-numeric:tabular-nums}
  ul.plain{list-style:none;margin-top:4px}
  ul.plain li{padding:12px 0;border-bottom:1px solid var(--line);font-size:14px;color:var(--ink-2)}
  ul.plain li:last-child{border-bottom:none}
  ul.plain li strong{color:var(--ink)}
  ul.plain .w{display:block;max-width:66ch}
  .scope{display:flex;gap:26px;flex-wrap:wrap;margin-top:8px;font-size:13px}
  .scope div{color:var(--ink-3);max-width:200px;text-wrap:pretty}
  .scope b{display:block;color:var(--ink);font-weight:600;font-size:13.5px}
  .next{margin-top:34px;background:var(--panel);border-radius:8px;padding:16px 20px;
    font-size:14px;color:var(--ink-2)}
  .next b{color:var(--ink)}
  details{margin-top:26px;font-size:13px;color:var(--ink-3)}
  details summary{cursor:pointer;font-weight:600;color:var(--ink-2)}
  details p{margin:8px 0;max-width:70ch}
  details ul{margin:8px 0 0 18px}
  details li{margin-top:6px;max-width:70ch}
  details code{font:12px ui-monospace,SFMono-Regular,Menlo,monospace;background:var(--panel);
    padding:1px 5px;border-radius:3px}
  footer{margin-top:52px;border-top:1px solid var(--line);padding-top:18px;
    display:flex;justify-content:space-between;gap:16px;flex-wrap:wrap;
    font-size:13px;color:var(--ink-3)}
  @media (max-width:640px){
    .stats{grid-template-columns:repeat(2,1fr)}
    .stat:nth-child(3){border-left:none}
    .stat{border-top:1px solid var(--line)}
    .stat:nth-child(-n+2){border-top:none}
    table.math{max-width:none}
    table.math td.v{padding-left:12px}
  }
  @media (max-width:480px){
    .receipt{grid-template-columns:1fr;row-gap:2px}
    .receipt .k{margin-top:8px}
  }
  @media print{body{padding:0}.card,.stats{break-inside:avoid}}
"""

_ONES = {
    0: "no", 1: "one", 2: "two", 3: "three", 4: "four",
    5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine",
}
CONFIRM_CARDS = 2
_MONTHS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)


def public_verdict(verdict: str) -> str:
    if verdict == "needs_review":
        return "share_with_caveats"
    if verdict in PUBLIC_VERDICTS:
        return verdict
    return "unable_to_grade"


def customer_verdict(verdict: str) -> str:
    if verdict == "needs_review":
        return "share_with_caveats"
    if verdict == "unable_to_grade":
        return "unable_to_grade"
    return public_verdict(verdict)


def public_explanation(check: dict) -> str:
    """Mechanical shareable explanation. Never copy host-authored prose."""
    verdict = str(check.get("verdict") or "")
    quote = str(check.get("report_quote") or "").strip()
    named = f'The report claim "{quote}"' if quote else "The report claim"
    if verdict == "confirmed":
        return f"{named} is confirmed."
    if verdict == "contradicted":
        return f"{named} is contradicted."
    if verdict == "not_checkable":
        return f"{named} could not be checked."
    if verdict == "changed_since_report":
        if quote:
            return f'Today\'s value differs from the report claim "{quote}".'
        return "Today's value differs from the report claim."
    if verdict == "error":
        return f"{named} is wrong."
    if verdict:
        return f"{named} has verdict {verdict}."
    return f"{named} was graded."


def _finding_quantity(finding: dict):
    detail = finding.get("detail") or finding.get("evidence") or {}
    if isinstance(detail, dict) and "stated" in detail:
        try:
            return Decimal(str(detail["stated"]))
        except (InvalidOperation, ValueError):
            return None
    return None


def ungraded_reason(raw: dict, layer2_named: bool, receipts: dict | list | None
                    ) -> str | None:
    """Refuse a shareable page when the host review did not finish."""
    payload = receipts if isinstance(receipts, dict) else {}
    semantic = payload.get("semantic_status")
    if semantic is None:
        semantic = ((raw.get("verification") or {}).get("semantic") or {}).get(
            "status")
    claims = list(payload.get("claims") or raw.get("claims") or [])
    material = [row for row in claims if row.get("importance") == "material"]
    grounded = [
        row for row in material
        if row.get("outcome") in GROUNDED_OUTCOMES
    ]
    inv = payload.get("inventory") or raw.get("inventory") or {}
    if layer2_named:
        if semantic in UNFINISHED_SEMANTIC:
            return "semantic review did not complete"
        if "claims" in payload and not grounded:
            return "no grounded material claims"
        checks = payload.get("checks") or payload.get("validated") or []
        if isinstance(receipts, list):
            checks = receipts
        if not checks and not grounded:
            return "no grounded material claims"
        if inv.get("complete"):
            unfinished = [
                row for row in material
                if row.get("outcome") not in GROUNDED_OUTCOMES
            ]
            if unfinished:
                return "material claims are not complete"
            discarded_claims = [
                row for row in (payload.get("discarded_claims") or [])
                if row.get("importance") == "material"
            ]
            if discarded_claims:
                return "material claims were discarded"
            if payload.get("discarded"):
                return "receipt failures remain"
    if (raw.get("agentic_only") and not raw.get("agentic_scan_completed")
            and not inv.get("complete")):
        if semantic not in {"complete", "partial"}:
            return "host review did not complete"
    return None


def document_errors_unaccounted(raw: dict) -> bool:
    """True when D findings exist that the receipts ledger does not cover."""
    claims = list(raw.get("claims") or [])
    if not claims:
        return False
    d_findings = [
        item for item in (raw.get("findings") or [])
        if str(item.get("tier")) == "D" and not _is_diagnostic_record(item)
    ]
    if not d_findings:
        return False
    for finding in d_findings:
        stated = _finding_quantity(finding)
        cid = str(finding.get("check_id") or "")
        accounted = False
        for claim in claims:
            if claim.get("found_by") == "arithmetic":
                if not cid or str(claim.get("check_id") or "") in {cid, ""}:
                    accounted = True
                    break
            if str(claim.get("check_id") or "") == cid and cid:
                accounted = True
                break
            if stated is not None:
                quote = str(claim.get("quote") or "")
                try:
                    q = Decimal(_re.sub(r"[^\d.\-]+", "", quote) or "nan")
                except (InvalidOperation, ValueError):
                    q = None
                if q == stated:
                    accounted = True
                    break
        if not accounted:
            return True
    return False


def spell_count(n: int) -> str:
    n = int(n)
    if 0 <= n <= 9:
        return _ONES[n]
    return f"{n:,}"


def pretty_date(value) -> str:
    text = str(value or "").strip()
    match = _re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    if not match:
        return text
    year, month, day = (int(part) for part in match.groups())
    if 1 <= month <= 12:
        return f"{_MONTHS[month - 1]} {day}, {year}"
    return text


def money(value, cents: bool = False) -> str:
    try:
        number = Decimal(str(value).replace(",", "").replace("$", "").strip())
    except (InvalidOperation, ValueError, AttributeError):
        return str(value)
    if cents or number.as_tuple().exponent < 0:
        return f"${number:,.2f}"
    if number == number.to_integral():
        return f"${number:,.0f}"
    return f"${number:,.2f}"


def figure(value) -> str:
    if isinstance(value, bool) or value is None:
        return "" if value is None else str(value)
    text = str(value).strip()
    if text.endswith("%"):
        body = figure(text[:-1].strip())
        return f"{body}%" if body else text
    if text.startswith("$") or (text[:1].isdigit() is False and "$" in text):
        try:
            Decimal(text.replace(",", "").replace("$", ""))
            return money(text)
        except (InvalidOperation, ValueError):
            return text
    try:
        number = Decimal(text.replace(",", ""))
    except (InvalidOperation, ValueError):
        return text
    if number == number.to_integral():
        return f"{number:,.0f}"
    return f"{number:,.4f}".rstrip("0").rstrip(".")


def curly(text: str) -> str:
    return f"&ldquo;{html.escape(text)}&rdquo;"


def pointer_name(pointer: str) -> str:
    token = str(pointer or "").rstrip("/").split("/")[-1]
    return token.replace("~1", "/").replace("~0", "~")


def where_from(location) -> str:
    text = str(location or "").strip()
    if not text:
        return ""
    parts = text.split("/")
    if len(parts) == 3 and parts[0].lower().startswith("table"):
        digits = _re.sub(r"\D+", "", parts[0]) or "1"
        return f"Table {int(digits)}, {parts[1]} row, {parts[2]} column"
    return text


def evidence_value_line(check: dict) -> str:
    return html.escape(public_explanation(check))


def receipt_block(report_says: str, evidence_html: str, report_label: str = "Report says",
                  evidence_label: str = "Evidence says") -> str:
    return (
        '<div class="receipt">'
        f'<div class="k">{report_label}</div><div class="q">{report_says}</div>'
        f'<div class="k">{evidence_label}</div><div class="q">{evidence_html}</div>'
        "</div>"
    )


def math_table(finding: dict) -> str:
    detail = finding.get("arithmetic") or finding.get("evidence") or {}
    if not isinstance(detail, dict) or "stated" not in detail or "computed" not in detail:
        return ""
    stated = detail["stated"]
    computed = detail["computed"]
    delta = detail.get("discrepancy", (Decimal(str(stated)) - Decimal(str(computed))))
    rows = []
    for addend in detail.get("addends") or []:
        if not isinstance(addend, dict):
            continue
        label = html.escape(str(addend.get("label") or "row"))
        rows.append(
            f'<tr><td>{label}</td><td class="v">{html.escape(money(addend.get("value"), cents=True))}</td></tr>'
        )
    rows.append(
        f'<tr class="sum"><td>Sum of the rows</td><td class="v">{html.escape(money(computed, cents=True))}</td></tr>'
    )
    rows.append(
        f'<tr class="bad"><td>The report shows</td><td class="v">{html.escape(money(stated, cents=True))}</td></tr>'
    )
    rows.append(
        f'<tr class="sum"><td>Difference</td><td class="v">{html.escape(money(abs(Decimal(str(delta))), cents=True))}</td></tr>'
    )
    return '<table class="math num">' + "".join(rows) + "</table>"


def arith_title(finding: dict) -> str:
    loc = str(finding.get("location") or "")
    parts = loc.split("/")
    col = parts[2] if len(parts) == 3 else "total"
    detail = finding.get("arithmetic") or finding.get("evidence") or {}
    delta = abs(Decimal(str(detail.get("discrepancy") or 0))) if isinstance(detail, dict) else Decimal(0)
    return f"The {col} total is {money(delta, cents=True)} too high"


def arith_fix(finding: dict) -> str:
    loc = str(finding.get("location") or "")
    parts = loc.split("/")
    row = parts[1] if len(parts) == 3 else "Total"
    col = parts[2] if len(parts) == 3 else "value"
    detail = finding.get("arithmetic") or finding.get("evidence") or {}
    computed = detail.get("computed") if isinstance(detail, dict) else None
    if computed is None:
        return ""
    return f"Change the {row} row, {col} column to {money(computed, cents=True)}."


def is_as_of_confirmed(check: dict) -> bool:
    if check.get("verdict") != "confirmed":
        return False
    if check.get("type") == "staleness":
        return True
    if check.get("current_as_of"):
        return True
    return False


ERROR_OUTCOMES = frozenset({"error", "contradicted"})
CSR_OUTCOMES = frozenset({"changed_since_report"})
OK_OUTCOMES = frozenset({"confirmed"})


def claim_bucket(outcome) -> str:
    if outcome in ERROR_OUTCOMES:
        return "errors"
    if outcome in CSR_OUTCOMES:
        return "today-differs"
    if outcome in OK_OUTCOMES:
        return "confirmed"
    return "not-checkable"


def card_title(check: dict, kind: str) -> str:
    label = str(check.get("metric_label") or "").strip()
    quote = str(check.get("report_quote") or "").strip()
    if kind == "confirmed":
        if label and is_as_of_confirmed(check):
            return f"The {html.escape(label.lower())} figure matches the source, as of the report&rsquo;s own period"
        if label:
            return f"The {html.escape(label.lower())} figure matches your evidence"
        return html.escape(quote or "Confirmed")
    if kind == "error":
        if label:
            return f"The {html.escape(label.lower())} figure does not match your evidence"
        return html.escape(quote or "The figure does not match your evidence")
    if kind == "csr":
        if label:
            return f"{html.escape(label)}: today&rsquo;s value differs from the report&rsquo;s"
        return html.escape(quote) if quote else "Today&rsquo;s value differs from the report&rsquo;s"
    return html.escape(quote or kind)


def location_line(check_or_finding: dict) -> str:
    where = where_from(check_or_finding.get("location"))
    if not where:
        return ""
    return f'<div class="where">{html.escape(where)}</div>'


def live_source_ran(art: dict) -> bool:
    live = ((art.get("verification") or {}).get("live_source") or {})
    status = str(live.get("status") or "not_run")
    if status in {"complete", "partial", "failed"}:
        return True
    source = art.get("source_result") or {}
    if source and source.get("status") not in {None, "not_run", "not_applicable"}:
        return True
    return False


def html_of(art: dict, raw: dict | None = None,
            ledger_raw: dict | None = None, source: dict | None = None) -> str:
    findings = [f for f in (art.get("findings") or []) if f.get("tier") == "D"]
    checks = list(art.get("evidence_checks") or [])
    claims = list(art.get("claims") or [])
    if claims:
        n_err = sum(1 for row in claims if claim_bucket(row.get("outcome")) == "errors")
        n_ok = sum(1 for row in claims if claim_bucket(row.get("outcome")) == "confirmed")
        n_csr = sum(1 for row in claims if claim_bucket(row.get("outcome")) == "today-differs")
        n_nc = sum(1 for row in claims if claim_bucket(row.get("outcome")) == "not-checkable")
        ledger = len(claims)
        chosen_check_ids = {
            str(row.get("check_id") or "") for row in claims if row.get("check_id")}
        contradicted = [
            c for c in checks
            if c.get("verdict") == "contradicted" and c.get("id") in chosen_check_ids]
        confirmed = [
            c for c in checks
            if c.get("verdict") == "confirmed" and c.get("id") in chosen_check_ids]
        csr = [
            c for c in checks
            if c.get("verdict") == "changed_since_report" and c.get("id") in chosen_check_ids]
        not_checkable = [
            c for c in checks
            if c.get("verdict") == "not_checkable" and c.get("id") in chosen_check_ids]
        unreached = [
            row for row in claims if row.get("outcome") in (None, "not_reached")]
        other = []
    else:
        contradicted = [c for c in checks if c.get("verdict") == "contradicted"]
        confirmed = [c for c in checks if c.get("verdict") == "confirmed"]
        csr = [c for c in checks if c.get("verdict") == "changed_since_report"]
        not_checkable = [c for c in checks if c.get("verdict") == "not_checkable"]
        other = [
            c for c in checks
            if c.get("verdict") not in {
                "confirmed", "contradicted", "not_checkable", "changed_since_report",
            }
        ]
        unreached = []
        n_err = len(findings) + len(contradicted) + len(other)
        n_ok = len(confirmed)
        n_csr = len(csr)
        n_nc = len(not_checkable)
        coverage_total = int(
            (art.get("evidence_coverage") or {}).get("document_claims_total") or 0)
        classified = n_err + n_ok + n_csr + n_nc
        ledger = coverage_total or classified
        if ledger > classified:
            n_nc += ledger - classified

    csr_ran = n_csr > 0 or live_source_ran(art)
    page_v = customer_verdict(str(art.get("verdict") or "needs_review"))
    if n_err:
        page_v = "fix_first"
    elif page_v == "fix_first":
        page_v = "share_with_caveats"

    src = art.get("source") or {}
    filename = src.get("path") or "report"
    period = src.get("period_label") or ""
    iso_date = src.get("report_date") or ""
    if not iso_date and raw:
        iso_date = str((raw.get("source") or {}).get("report_date") or "")
    verified = pretty_date(art.get("generated_at"))
    report_date = pretty_date(iso_date) if iso_date else ""
    if not report_date and period and _re.search(r"\d{4}-\d{2}-\d{2}", str(period)):
        report_date = pretty_date(period)

    if page_v == "fix_first":
        chip, chip_class = "FIX FIRST", "fix"
        noun = "error" if n_err == 1 else "errors"
        h1 = f"Fix {spell_count(n_err)} {noun} before you share this report."
        next_text = (
            f"fix the {spell_count(n_err)} {noun} above, then have Summation Verify "
            "check the report again."
        )
    elif page_v == "safe_to_share":
        chip, chip_class = "SAFE TO SHARE", "safe"
        if ledger == 1:
            h1 = "No errors found. The one claim was checked."
        else:
            h1 = f"No errors found. All {spell_count(ledger)} claims were checked."
        next_text = ""
    elif page_v == "unable_to_grade":
        chip, chip_class = "UNABLE TO GRADE", "gray"
        h1 = "This report could not be graded."
        next_text = ""
    else:
        chip, chip_class = "SHARE WITH CAVEATS", "warn"
        if n_nc:
            h1 = (
                f"No errors found. {spell_count(n_nc).capitalize()} "
                f"{'claim' if n_nc == 1 else 'claims'} could not be checked."
            )
        elif n_csr:
            h1 = (
                "No errors found. Today&rsquo;s value differs for "
                f"{spell_count(n_csr)} {'claim' if n_csr == 1 else 'claims'}."
            )
        else:
            h1 = "No errors found. Part of the assessment did not complete."
        next_text = ""

    clauses = [f"The report makes {spell_count(ledger)} {'claim' if ledger == 1 else 'claims'}."]
    if n_err:
        clauses.append(
            f"{spell_count(n_err).capitalize()} "
            f"{'is' if n_err == 1 else 'are'} wrong."
        )
    if n_ok:
        clauses.append(
            f"{spell_count(n_ok).capitalize()} "
            f"{'is' if n_ok == 1 else 'are'} confirmed correct."
        )
    if n_csr:
        clauses.append(
            f"For {spell_count(n_csr)}, today&rsquo;s value differs and the "
            "report-date value is not checkable."
        )
    if n_nc:
        clauses.append(
            f"{spell_count(n_nc).capitalize()} could not be checked."
        )
    verdict_p = " ".join(clauses)

    file_line = f"Report examined: <code>{html.escape(str(filename))}</code>"
    if period:
        file_line += f" ({html.escape(str(period))})"

    def stat_tile(count, ran: bool, css: str, label: str, sub: str, slug: str) -> str:
        if not ran:
            nhtml = '<div class="n na">Not run</div>'
            count_attr = "not-run"
        else:
            nhtml = f'<div class="n num">{int(count)}</div>'
            count_attr = str(int(count))
        return (
            f'<div class="stat {css}" data-bucket="{slug}" data-count="{count_attr}">'
            f"{nhtml}<div class=\"l\">{label}</div><div class=\"s\">{sub}</div></div>"
        )

    err_sub = "fix these first" if n_err else "nothing to fix"
    ok_sub = "checked and correct"
    if csr_ran:
        csr_sub = "report-date value not checkable" if n_csr else "live source ran"
    else:
        csr_sub = "no live source connected"
    nc_sub = "no evidence for these" if n_nc else "every claim had evidence"

    stats = (
        '<div class="stats" role="group" aria-label="Verification results" '
        f'data-ledger="{ledger}">'
        + stat_tile(n_err, True, "red" if n_err else "gray", "Errors found", err_sub, "errors")
        + stat_tile(n_ok, True, "green" if n_ok else "gray", "Confirmed", ok_sub, "confirmed")
        + stat_tile(
            n_csr, csr_ran,
            "amber" if n_csr else "gray",
            "Today&rsquo;s value differs", csr_sub, "today-differs")
        + stat_tile(
            n_nc, True,
            "amber" if n_nc else "gray",
            "Not checkable", nc_sub, "not-checkable")
        + "</div>"
    )

    sections = []

    error_cards = []
    for finding in findings:
        body = math_table(finding)
        fix = arith_fix(finding)
        error_cards.append(
            '<div class="card err" data-kind="error">'
            '<span class="tag">ERROR</span>'
            f"<h3>{html.escape(arith_title(finding))}</h3>"
            f"{location_line(finding)}"
            f"{body}"
            + (f"<p>{html.escape(fix)}</p>" if fix else "")
            + '<div class="machine">Checked by a program: the total was recomputed from the report itself.</div>'
            "</div>"
        )
    for check in contradicted:
        error_cards.append(
            '<div class="card err" data-kind="error">'
            '<span class="tag">ERROR</span>'
            f"<h3>{card_title(check, 'error')}</h3>"
            f"{location_line(check)}"
            + receipt_block(curly(check.get("report_quote") or ""), evidence_value_line(check))
            + f"<p>{html.escape(public_explanation(check))}</p>"
            + '<div class="machine">Checked by a program: the report quote and the evidence value do not match.</div>'
            "</div>"
        )
    for check in other:
        error_cards.append(
            '<div class="card err" data-kind="error">'
            f'<span class="tag">{html.escape(str(check.get("verdict") or "ERROR").upper())}</span>'
            f"<h3>{html.escape(check.get('report_quote') or 'Finding')}</h3>"
            f"{location_line(check)}"
            + f"<p>{html.escape(public_explanation(check))}</p>"
            + f'<div class="machine">Checked by a program: {html.escape(str(check.get("verdict")))}.</div>'
            "</div>"
        )
    if error_cards:
        sections.append(
            '<section data-section="errors">'
            "<h2>Errors: fix these first</h2>"
            + "".join(error_cards)
            + "</section>"
        )

    shown_confirmed = confirmed[:CONFIRM_CARDS]
    hidden_confirmed = confirmed[CONFIRM_CARDS:]
    confirm_cards = []
    for check in shown_confirmed:
        as_of = is_as_of_confirmed(check)
        title = card_title(check, "confirmed")
        if as_of:
            machine = "Checked by a program: the report value was compared with the live query result."
            ev_label = "Source says"
        else:
            machine = "Checked by a program: the report quote and the evidence value match."
            ev_label = "Evidence says"
        confirm_cards.append(
            '<div class="card ok" data-kind="confirmed">'
            '<span class="tag">CONFIRMED</span>'
            f"<h3>{title}</h3>"
            f"{location_line(check)}"
            + receipt_block(
                curly(check.get("report_quote") or ""),
                evidence_value_line(check),
                evidence_label=ev_label,
            )
            + f"<p>{html.escape(public_explanation(check))}</p>"
            + f'<div class="machine">{machine}</div>'
            "</div>"
        )
    confirm_html = "".join(confirm_cards)
    if hidden_confirmed:
        n_hidden = len(hidden_confirmed)
        confirm_html += (
            f'<p class="sectionlede" style="margin-top:12px">The other {spell_count(n_hidden)} '
            f"confirmed {'claim' if n_hidden == 1 else 'claims'} are listed under technical detail.</p>"
        )
    sections.append(
        '<section data-section="confirmed">'
        "<h2>Confirmed correct</h2>"
        + (confirm_html or '<p class="sectionlede">No claims were confirmed.</p>')
        + "</section>"
    )

    if csr:
        csr_cards = []
        for check in csr:
            quote = str(check.get("report_quote") or "")
            found = _re.search(r"\$?-?\d[\d,]*(?:\.\d+)?%?", quote)
            report_val = figure(found.group(0)) if found else quote
            report_label = f"Report, {html.escape(report_date)}" if report_date else "Report"
            csr_cards.append(
                '<div class="card chg" data-kind="today-differs">'
                '<span class="tag">TODAY DIFFERS</span>'
                f"<h3>{card_title(check, 'csr')}</h3>"
                f"{location_line(check)}"
                '<div class="compare">'
                f'<div class="box"><div class="bl">{report_label}</div>'
                f'<div class="bv">{html.escape(report_val)}</div></div>'
                "</div>"
                + f"<p>{html.escape(public_explanation(check))}</p>"
                + '<div class="machine">Checked by a program: the report value was compared with a later value.</div>'
                + f'<div class="q" hidden>{html.escape(check.get("report_quote") or "")}</div>'
                "</div>"
            )
        sections.append(
            '<section data-section="today-differs">'
            "<h2>Today&rsquo;s value differs</h2>"
            + "".join(csr_cards)
            + "</section>"
        )

    nc_items = []
    for check in not_checkable:
        nc_items.append(
            "<li><span class=\"w\"><strong>"
            f"{curly(check.get('report_quote') or 'Claim')}</strong> "
            f"{html.escape(public_explanation(check))}</span></li>"
        )
    for row in unreached:
        nc_items.append(
            "<li><span class=\"w\"><strong>"
            f"{curly(row.get('quote') or 'Claim')}</strong> "
            "No check reached this claim.</span></li>"
        )
    if n_nc and not nc_items:
        nc_items.append(
            "<li><span class=\"w\"><strong>"
            f"{spell_count(n_nc).capitalize()} "
            f"{'claim' if n_nc == 1 else 'claims'} had no accepted check."
            "</strong></span></li>"
        )
    if not nc_items:
        nc_list = '<ul class="plain"><li><span class="w"><strong>Every claim had evidence.</strong></span></li></ul>'
        lede = ""
    else:
        lede = (
            f'<p class="sectionlede">Read '
            f"{'this' if n_nc == 1 else 'these ' + spell_count(n_nc)} as unverified.</p>"
        )
        nc_list = f'<ul class="plain">{"".join(nc_items)}</ul>'
    sections.append(
        '<section data-section="not-checkable">'
        "<h2>What we could not check, and why</h2>"
        + lede + nc_list
        + "</section>"
    )

    doc = (art.get("verification") or {}).get("document") or {}
    live = (art.get("verification") or {}).get("live_source") or {}
    cited = []
    arith_status = str(doc.get("status") or "not_run")
    if arith_status == "complete":
        arith_text = (
            f"Ran on the report. {spell_count(len(findings)).capitalize()} "
            f"{'error' if len(findings) == 1 else 'errors'} "
            f"{'was' if len(findings) == 1 else 'were'} found."
            if findings else
            "Ran on the report. Every total that was checked equals the sum of its rows."
        )
    elif arith_status in {"not_available", "not_run", "skipped"}:
        arith_text = "Did not run."
    else:
        arith_text = html.escape(str(doc.get("detail") or arith_status))
    if csr_ran or n_csr:
        live_text = "Ran."
    else:
        live_text = "Did not run."
    ev_text = "Checked against the evidence supplied with the report."
    checked_n = n_err + n_ok + n_csr
    claims_text = (
        f"Every headline figure, table total, and named metric counts as a claim; "
        f"{spell_count(ledger)} found. {spell_count(checked_n).capitalize()} "
        f"{'was' if checked_n == 1 else 'were'} checked"
        + (f"; {spell_count(n_nc)} could not be checked" if n_nc else "")
        + "."
    )
    sections.append(
        '<section data-section="what-ran">'
        "<h2>What ran</h2>"
        '<div class="scope">'
        f"<div><b>Claims</b>{claims_text}</div>"
        f"<div><b>Document arithmetic</b>{arith_text}</div>"
        f"<div><b>Later value</b>{live_text}</div>"
        f"<div><b>Evidence used</b>{ev_text}</div>"
        "</div></section>"
    )

    next_html = (
        f'<div class="next"><b>Next:</b> {next_text}</div>'
        if next_text else ""
    )

    tech_bits = []
    for check in hidden_confirmed:
        line = (
            f"{curly(check.get('report_quote') or 'Claim')} "
            f"{evidence_value_line(check)}"
        )
        tech_bits.append(f"<li>{line}</li>")
    for finding in findings:
        detail = finding.get("arithmetic") or finding.get("evidence") or {}
        if isinstance(detail, dict) and "computed" in detail:
            tech_bits.append(
                "<li>"
                f"{html.escape(where_from(finding.get('location')))}: report shows "
                f"{html.escape(money(detail.get('stated'), cents=True))}; "
                f"the rows sum to {html.escape(money(detail.get('computed'), cents=True))}."
                "</li>"
            )
    tech_list = (
        "<p>The other confirmed claims:</p><ul>" + "".join(tech_bits) + "</ul>"
        if hidden_confirmed else
        ("<p>Confirmed claims:</p><ul>" + "".join(tech_bits) + "</ul>" if tech_bits else "")
    )
    technical = (
        "<details><summary>Technical detail</summary>"
        "<p>A claim with no accepted check is listed under "
        "&ldquo;What we could not check, and why.&rdquo;</p>"
        f"{tech_list}"
        "</details>"
    )

    footer = (
        "<footer>"
        "<div>Checked automatically by Summation Verify</div>"
        f'<div class="num">Run {html.escape(str(art.get("run_id") or ""))} · {html.escape(verified)}</div>'
        "</footer>"
    )

    title = f"Verification: {html.escape(str(filename))}"
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>{PAGE_CSS}</style>
</head>
<body>
<div class="page">
<header>
  <div class="wordmark">Summation <span>/ Verify</span></div>
  <div class="runmeta num">Verified {html.escape(verified)}</div>
</header>
<div class="verdict">
  <span class="chip {chip_class}">{chip}</span>
  <h1>{h1}</h1>
  <p>{verdict_p}</p>
  <div class="file">{file_line}</div>
</div>
{stats}
{''.join(sections)}
{next_html}
{technical}
{footer}
</div>
</body>
</html>
"""

def attach_receipts_ledger(raw: dict, receipts: dict) -> None:
    """Copy the grounded claims ledger onto findings coverage."""
    if not isinstance(raw, dict) or not isinstance(receipts, dict):
        return
    claims = list(receipts.get("claims") or [])
    ledger_n = int(receipts.get("claims_in_ledger", len(claims)))
    reached_n = int(receipts.get("claims_reached_by_a_check", sum(
        1 for row in claims if row.get("outcome") not in (None, "not_reached")
    )))
    cov = raw.setdefault("coverage", {})
    cov["claims_in_ledger"] = ledger_n
    cov["claims_reached_by_a_check"] = reached_n
    review = raw.setdefault("evidence_review", {})
    review["outcomes_proposed"] = int(receipts.get("proposed") or 0)
    review["receipt_failures"] = len(receipts.get("discarded") or [])
    if claims:
        raw["claims"] = claims
    if isinstance(receipts.get("inventory"), dict):
        raw["inventory"] = receipts["inventory"]
    raw["inventory_missing"] = list(receipts.get("inventory_missing") or [])
    if receipts.get("extractor_checkable_fraction") is not None:
        cov["extractor_checkable_fraction"] = receipts["extractor_checkable_fraction"]
    if receipts.get("engine_checkable_fraction") is not None:
        cov["engine_checkable_fraction"] = receipts["engine_checkable_fraction"]
    material_n = sum(
        1 for item in (raw.get("inventory") or {}).get("items") or []
        if item.get("importance") == "material")
    cov["inventory_material"] = material_n
    status = receipts.get("semantic_status")
    if status:
        verification = raw.setdefault("verification", {})
        verification["semantic"] = {
            "status": status,
            "detail": (
                f"{reached_n} of {ledger_n} ledger claims have an accepted outcome."
            ),
        }
    if status in {"complete", "partial"}:
        raw["agentic_scan_completed"] = True
    src = raw.setdefault("source", {})
    if receipts.get("report_period"):
        src["period_label"] = receipts["report_period"]
    if receipts.get("report_date"):
        src["report_date"] = receipts["report_date"]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--findings", required=True, type=Path)
    p.add_argument("--out-dir", required=True, type=Path)
    p.add_argument("--run-id", default=None)
    p.add_argument("--layer2", type=Path, default=None,
                   help="validated Layer 2 findings JSON (list or {findings:[...]}); HTML only")
    p.add_argument("--ledger", type=Path, default=None,
                   help="ledger.json for naming where unchecked figures live; HTML only")
    p.add_argument("--source", type=Path, default=None,
                   help="source-findings.json from sourcecheck.py; HTML only")
    p.add_argument("--claims", type=Path, default=None,
                   help="claims.json ledger; required if the path is named")
    args = p.parse_args()
    if not args.findings.is_file():
        print(f"render: missing findings {args.findings}", file=sys.stderr)
        return 2
    if args.layer2 is not None and not args.layer2.is_file():
        print(f"render: missing layer2 {args.layer2}", file=sys.stderr)
        return 2
    if args.claims is not None and not args.claims.is_file():
        print(f"render: missing claims {args.claims}", file=sys.stderr)
        return 2
    raw = json.loads(args.findings.read_text())
    layer2 = []
    guidance = {"decision": None, "actions": [], "limits": []}
    l2raw = None
    if args.layer2 is not None:
        l2raw = json.loads(args.layer2.read_text())
        if isinstance(l2raw, list):
            layer2 = l2raw
        else:
            layer2 = (
                l2raw.get("checks")
                or l2raw.get("validated")
                or l2raw.get("findings")
                or []
            )
            attach_receipts_ledger(raw, l2raw)
            missing = list(l2raw.get("inventory_missing") or [])
            inv = l2raw.get("inventory") or {}
            if inv.get("complete") and missing:
                shown = ", ".join(
                    str(row.get("displayed") or row.get("id")) for row in missing[:8])
                print(
                    "render: claims.json does not account for every material "
                    f"inventory item ({shown}).",
                    file=sys.stderr,
                )
                return 2
            if document_errors_unaccounted(raw):
                print(
                    "render: findings contain errors the claims ledger does not "
                    "account for. Run accept.py with --findings.",
                    file=sys.stderr,
                )
                return 2
    reason = ungraded_reason(raw, args.layer2 is not None, l2raw)
    if reason:
        print(f"render: {reason}. No shareable artifact written.", file=sys.stderr)
        return 2
    ledger_raw = None
    if args.ledger and args.ledger.is_file():
        ledger_raw = json.loads(args.ledger.read_text())
    elif args.ledger is None:
        sibling = args.findings.with_name("ledger.json")
        if sibling.is_file():
            ledger_raw = json.loads(sibling.read_text())
    source = None
    if args.source and args.source.is_file():
        source = json.loads(args.source.read_text())
    digest = str((raw.get("source") or {}).get("sha256") or "")
    if len(digest) < 6:
        digest = hashlib.sha256(args.findings.read_bytes()).hexdigest()
    run_id = args.run_id or f"sf-{digest[:6]}"
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    art = artifact_from_findings(raw, run_id=run_id, generated_at=generated_at,
                                 layer2=layer2, source=source, guidance=guidance)
    if art.get("verdict") == "unable_to_grade":
        print(
            "render: report could not be graded. No shareable artifact written.",
            file=sys.stderr,
        )
        return 2
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "grade-artifact.json").write_text(json.dumps(art, indent=2) + "\n")
    (args.out_dir / "grade-artifact.html").write_text(html_of(art, raw, ledger_raw))
    print(args.out_dir / "grade-artifact.json")
    print(args.out_dir / "grade-artifact.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
