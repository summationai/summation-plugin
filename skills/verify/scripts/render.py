#!/usr/bin/env python3
"""Render grade-artifact/v1 from coldverify findings.json. Fail closed."""
from __future__ import annotations

import argparse
from decimal import Decimal, InvalidOperation
import html
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = "grade-artifact/v1"
MIN_CLAIMS = 1
# safe_to_share requires every figure the extractor could see to be checkable.
MIN_EXTRACTOR_FRACTION = 1.0
MIN_ENGINE_FRACTION = 1.0
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
)
VERDICTS = frozenset(
    {"safe_to_share", "share_with_caveats", "fix_first", "needs_review", "unable_to_grade"}
)
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
    claims = claim_count(raw)
    reached = int(cov.get("claims_reached_by_a_check") or 0)
    ext = cov.get("extractor_checkable_fraction")
    eng = cov.get("engine_checkable_fraction")
    if claims < MIN_CLAIMS:
        return False
    if reached < claims:
        return False
    if not isinstance(ext, (int, float)) or ext < MIN_EXTRACTOR_FRACTION:
        return False
    if not isinstance(eng, (int, float)) or eng < MIN_ENGINE_FRACTION:
        return False
    if int(cov.get("checks_errored") or 0) != 0:
        return False
    if raw.get("findings_truncated"):
        return False
    return True


def _is_diagnostic_record(f: dict) -> bool:
    """True when a finding describes scanner coverage, not a report defect."""
    cid = str(f.get("check_id") or "")
    return cid not in CUSTOMER_CHECK_IDS


def verdict_of(raw: dict) -> str:
    if not isinstance(raw, dict) or "findings" not in raw:
        return "unable_to_grade"
    if raw.get("agentic_only"):
        return "needs_review" if raw.get("agentic_scan_completed") else "unable_to_grade"
    if claim_count(raw) < MIN_CLAIMS:
        return "unable_to_grade"
    findings = raw.get("findings")
    if not isinstance(findings, list):
        return "unable_to_grade"
    tiers = {str(f.get("tier")) for f in findings if not _is_diagnostic_record(f)}
    if "D" in tiers:
        return "fix_first"
    if not coverage_ok(raw):
        return "needs_review"
    if "C" in tiers:
        return "share_with_caveats"
    return "safe_to_share"


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
    if isinstance(frac, (int, float)) and frac < MIN_EXTRACTOR_FRACTION:
        out.append(
            f"Extractor could check {frac:.0%} of figures (need {MIN_EXTRACTOR_FRACTION:.0%})."
        )
    if cov.get("checks_errored"):
        out.append(f"{cov['checks_errored']} check(s) errored.")
    reached = int(cov.get("claims_reached_by_a_check") or 0)
    claims = claim_count(raw)
    if claims and reached < claims:
        out.append(f"Checks reached {reached} of {claims} claims.")
    eng = cov.get("engine_checkable_fraction")
    if isinstance(eng, (int, float)) and eng < MIN_ENGINE_FRACTION:
        out.append("Engine checkable fraction is below policy.")
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
    }


def _public_layer2(layer2: list[dict] | None) -> list[dict]:
    public = []
    for f in layer2 or []:
        verdict = str(f.get("verdict") or "contradicted")
        public.append({
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
            "evidence_file": f.get("evidence_file"),
            "evidence_quote": f.get("evidence_quote"),
            "evidence_json": list(f.get("evidence_json") or []),
            "evidence_receipts": list(f.get("evidence_receipts") or []),
            "evidence_receipt_mode": f.get("evidence_receipt_mode"),
            "explanation": str(f.get("explanation") or ""),
        })
    return public


def _has_claim_evidence_receipt(check: dict) -> bool:
    """Recognize the two validated receipt shapes exposed by the artifact."""
    if (check.get("basis") != "evidence"
            or check.get("verdict") not in {"confirmed", "contradicted"}):
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
    provenance_groups = list(review.get("provenance_groups") or [])
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
        "evidence_files_supplied": len(supplied),
        "evidence_files_cited": cited,
        "provenance_groups": provenance_groups,
        "source_independence": (
            "grouped_by_declared_provenance" if provenance_groups else "not_assessed"),
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
    if not source:
        return None
    return {
        "status": str(source.get("status") or "complete"),
        "error": source.get("error"),
        "provider": str(source.get("provider") or "sum-api"),
        "profile": str(source.get("profile") or ""),
        "source_identity": source.get("source_identity"),
        "suggested_source": source.get("suggested_source"),
        "generated_at": source.get("generated_at"),
        "tables": [str(table) for table in source.get("tables") or []],
        "confirmed": int(source.get("confirmed") or 0),
        "contradicted": int(source.get("contradicted") or 0),
        "not_run": int(source.get("not_run") or 0),
        "checks": list(source.get("checks") or []),
    }


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
    if source and any(
        check.get("verdict") == "changed_since_report"
        for check in source.get("checks") or []
    ) and base in {"safe_to_share", "share_with_caveats"}:
        return "needs_review"
    if source and source.get("status") in {"failed", "partial", "not_applicable"}:
        if base in {"safe_to_share", "share_with_caveats"}:
            return "needs_review"
    return base


def _offer(findings: list[dict], layer2: list[dict], source: dict | None,
           verdict: str, raw: dict) -> str:
    evidence_findings = [
        check for check in layer2 if check.get("verdict") == "contradicted"]
    semantic_status = (((raw.get("verification") or {}).get("semantic") or {})
                       .get("status"))
    if semantic_status == "failed":
        return ("Next: retry the semantic review once. If it stops again, keep this "
                "artifact and share the run ID with support.")
    if verdict == "unable_to_grade":
        if raw.get("deterministic_error"):
            return "Next: retry this assessment once. If it stops again, share the run ID with support."
        return ("Provide one supported report file (HTML, Markdown, text, CSV, XLSX, "
                "PPTX, DOCX, or PDF) to assess it.")
    if source and source.get("status") == "failed":
        return "Next: repair the source connection, then rerun the live check."
    if source and source.get("status") == "partial":
        return "Next: retry the live check. The document and semantic findings are preserved."
    if source and source.get("status") == "not_applicable":
        if source.get("suggested_source"):
            return (f"Next: connect or provide {source.get('suggested_source')}, the "
                    "authoritative source identified for these claims, then rerun the assessment.")
        return "Next: provide the authoritative source for the unverified claims, then rerun the assessment."
    if source and int(source.get("contradicted") or 0):
        return "Next: correct a copy with the current source values, then rerun the assessment."
    if source and any(
        check.get("verdict") == "changed_since_report"
        for check in source.get("checks") or []
    ):
        return ("Next: if this report is meant to describe the current state, refresh a copy. "
                "If it is a historical record, keep its snapshot date and do not treat later "
                "source changes as report errors.")
    if source and any(
        check.get("verdict") == "matches_current_source"
        for check in source.get("checks") or []
    ):
        return ("Next: keep the dated scope visible. Use a same-period snapshot or "
                "time-aligned query if you need independent historical confirmation.")
    if source is None:
        evidence_files = list(raw.get("evidence_files") or [])
        has_evidence_receipt = any(
            _has_claim_evidence_receipt(finding) for finding in layer2)
        if has_evidence_receipt:
            return ("Next: use a direct live query if you need confirmation beyond "
                    "the cited evidence files.")
        if evidence_files:
            return ("Next: retrieve or connect a current source and rerun. The supplied "
                    "files produced no claim-level source receipt.")
        return ("Next: retrieve or connect the current source and rerun before relying "
                "on this fallback assessment.")
    if findings or evidence_findings:
        return "Next: correct a copy, then rerun the assessment."
    return "Next: save this as a repeatable verification check."


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
            "evidence": f.get("detail"),
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
    decision, actions, decision_limits = _public_guidance(guidance)
    source_result = _public_source_result(source)
    score = None
    if "tier_d_per_100_claims" in headline:
        score = {
            "kind": "tier_d_per_100_claims",
            "value": headline["tier_d_per_100_claims"],
        }
    verdict = _combined_verdict(verdict_of(raw), evidence_checks, source_result)
    semantic_status = (((raw.get("verification") or {}).get("semantic") or {})
                       .get("status"))
    if semantic_status in {"failed", "not_run", "skipped"} and verdict in {
        "safe_to_share", "share_with_caveats"
    }:
        verdict = "needs_review"
    art = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "generated_at": generated_at,
        "source": source_public(raw),
        "source_result": source_result,
        "verdict": verdict,
        "score": score,
        "findings": findings,
        "evidence_checks": evidence_checks,
        "evidence_findings": evidence_findings,
        "evidence_coverage": evidence_coverage,
        "decision": decision,
        "actions": actions,
        "decision_limits": decision_limits,
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
        "verification": _verification_public(raw, source_result, evidence_checks),
        "limitations": limitations_of(raw),
        "offer": {"text": _offer(findings, evidence_checks, source_result, verdict, raw),
                  "accepted": None},
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



# ---------------------------------------------------------------------------
# Presentation. The model is a good compiler error: say what is wrong in plain
# words, point at the exact spot, show the numbers so the reader can verify it
# in seconds. Engine bookkeeping never appears as a "problem". It lives in a
# collapsed coverage section. No tier letters, no claim ids, no check ids in
# the reader's view.
# ---------------------------------------------------------------------------

import re as _re

#: check_id -> plain title, for the checks a reader can meet today.
TITLES = {
    "ari_total_footing": "A total does not add up",
    "ari_total_footing_precision": "A total does not add up at the precision shown",
    "uni_percent_vs_points": "A change in points is written as a percent",
    "per_period_misaligned": "Compared periods do not line up",
    "sel_order_violated": "A ranked list is not in the order it claims",
    "gnd_ungrounded_claim": "A claim has no source in the document",
}
FAMILY_TITLES = {
    "internal_arithmetic": "The numbers do not agree with each other",
    "units": "Units are mixed up",
    "grounding": "A claim lacks support",
    "period": "Time periods do not line up",
    "rounding": "Rounding hides a real change",
    "selection": "A list or ranking is inconsistent",
    "direction": "A direction word contradicts the numbers",
}
L2_TITLES = {
    "internal": "The report contradicts itself",
    "arithmetic": "The numbers do not add up",
    "units": "The units or scale are wrong",
    "selection": "The selected or ranked items do not match the claim",
    "logic": "The conclusion does not follow from the numbers",
}
VERDICT_LINES = {
    "safe_to_share": ("Ready to share",
                      "The complete checks found no material errors."),
    "share_with_caveats": ("Review before sharing",
                           "No material error was proven, but some items need review."),
    "fix_first": ("Fix before sharing",
                  "The assessment found material errors that need correction."),
    "needs_review": ("Review before sharing",
                     "The assessment was partial. The scope below shows what did and did not run."),
    "unable_to_grade": ("Assessment incomplete",
                        "The report could not be read or checked."),
}


def _partial_coverage_clause(art: dict) -> str:
    """One shared customer sentence for every partial semantic assessment."""
    semantic = ((art.get("verification") or {}).get("semantic") or {})
    if semantic.get("status") != "partial":
        return ""
    ec = art.get("evidence_coverage") or {}
    proposed = int(ec.get("claim_outcomes_proposed") or 0)
    retained = int(ec.get("validated_outcomes") or 0)
    detail = str(semantic.get("detail") or "")
    batch_match = _re.search(
        r"(\d+) of (\d+) evidence batches completed", detail)
    parts = []
    batch_incomplete = False
    if batch_match:
        completed, total = (int(value) for value in batch_match.groups())
        parts.append(
            f"{completed} of {total} evidence batch"
            f"{'es' if total != 1 else ''} completed")
        batch_incomplete = completed < total
    if proposed:
        parts.append(
            f"{retained} of {proposed} proposed outcome"
            f"{'s' if proposed != 1 else ''} were retained in the assessment")
    clause = "The semantic evidence review was partial"
    if parts:
        clause += ": " + ", and ".join(parts)
    clause += "."
    if batch_incomplete or (proposed and retained < proposed):
        clause += " The issue count is incomplete."
    else:
        clause += " The scope below names what did not complete."
    return " " + clause


def assessment_line(verdict: str, art: dict, raw: dict | None) -> str | None:
    """Render a verdict about the report, never the report's own conclusion."""
    ec = art.get("evidence_coverage") or {}
    semantic_status = str(((art.get("verification") or {}).get("semantic") or {})
                          .get("status") or "")
    files_supplied = int(ec.get("evidence_files_supplied") or 0)
    total = int(ec.get("document_claims_total") or (
        claim_count(raw) if raw is not None else 0))
    reached = int(ec.get("document_claims_reached") or (
        coverage(raw).get("claims_reached_by_a_check") if raw is not None else 0) or 0)
    if total and reached == total:
        reach = f" Document checks reached all {total} extracted numeric claims."
    elif total:
        reach = f" Document checks reached {reached} of {total} extracted numeric claims."
    else:
        reach = ""
    if not (art.get("evidence_checks") or ec.get("claim_outcomes_proposed")):
        if files_supplied and semantic_status in {"failed", "not_run", "skipped"}:
            return (
                "This report is not cleared: the semantic evidence review did not "
                f"complete, so none of its {files_supplied} supplied evidence file"
                f"{'s' if files_supplied != 1 else ''} could be verified against its "
                f"claims.{reach} Rerun the assessment to complete the evidence review."
            )
        return None

    def count(key: str, legacy: str) -> int:
        return int(ec.get(key, ec.get(legacy)) or 0)

    confirmed = count("evidence_confirmed", "confirmed")
    contradicted = count("evidence_contradicted", "contradicted")
    not_established = count("evidence_not_checkable", "not_checkable")
    checked = (
        f"{confirmed} claim{'s were' if confirmed != 1 else ' was'} confirmed "
        f"against the supplied evidence and {contradicted} "
        f"{'were' if contradicted != 1 else 'was'} contradicted."
    )
    partial_clause = _partial_coverage_clause(art)
    if verdict == "fix_first":
        source_contradictions = int(
            ((art.get("source_result") or {}).get("contradicted") or 0))
        document_material_failures = sum(
            finding.get("tier") == "D" for finding in art.get("findings") or [])
        document_review_items = sum(
            finding.get("tier") != "D" for finding in art.get("findings") or [])
        supporting_failures = sum(
            (f.get("importance") or "material") != "material"
            for f in art.get("evidence_findings") or [])
        material_failures = (
            document_material_failures
            + len(art.get("evidence_findings") or []) - supporting_failures
            + source_contradictions
        )
        # Label failures by the artifact's own importance classification;
        # never promote supporting failures to material.
        parts = []
        if material_failures:
            parts.append(f"{material_failures} material claim"
                         f"{'s' if material_failures != 1 else ''}")
        if supporting_failures:
            parts.append(f"{supporting_failures} supporting claim"
                         f"{'s' if supporting_failures != 1 else ''}")
        failed = " and ".join(parts) or "verification checks"
        review_line = (
            f" {document_review_items} additional document item"
            f"{'s' if document_review_items != 1 else ''} "
            f"{'need' if document_review_items != 1 else 'needs'} review."
            if document_review_items else ""
        )
        return (
            f"Do not rely on this report yet: {failed} failed verification."
            f"{partial_clause} {checked}{reach}{review_line} "
            "The failures are itemized below."
        )
    if verdict == "safe_to_share":
        return (
            f"This report stands up to verification. {checked}{reach}{partial_clause} "
            "No material error was found."
        )
    if verdict == "share_with_caveats":
        return (
            f"This report largely holds up: {checked}{reach}{partial_clause} "
            "A few items below need review before you rely on them."
        )
    if verdict == "needs_review":
        gaps = []
        if semantic_status in {"failed", "not_run", "skipped"}:
            gaps.append("the semantic evidence review did not complete")
        if raw is not None:
            extractor_fraction = coverage(raw).get("extractor_checkable_fraction")
            if (isinstance(extractor_fraction, (int, float))
                    and extractor_fraction < MIN_EXTRACTOR_FRACTION):
                gaps.append(
                    f"only {extractor_fraction:.0%} of the report's figures could be "
                    "extracted for document checks")
        if not_established:
            gaps.append(
                f"{not_established} claim{'s' if not_established != 1 else ''} "
                "could not be established from the supplied evidence")
        lead = f"No material error was found in this report: {checked}{reach}{partial_clause}"
        if not gaps:
            if partial_clause:
                return f"{lead} The gaps are itemized below."
            gaps.append("part of the verification did not complete")
        if len(gaps) == 1:
            return (
                f"{lead} But {gaps[0]}, so it is not fully cleared. "
                "The gaps are itemized below."
            )
        return (
            f"{lead} It is not fully cleared — {'; '.join(gaps)}. "
            "The gaps are itemized below."
        )
    return None

#: What each check family verifies, in the reader's words. Used only for
#: families whose checks all came back clean.
FAMILY_VERBS = {
    "internal_arithmetic": "totals agree with their components",
    "units": "units and scales are consistent where they are stated",
    "period": "compared time periods line up",
    "rounding": "rounded figures stay within what their precision allows",
    "selection": "ranked lists are in the order they claim",
    "direction": "direction words (up, down, flat) match the numbers",
    "grounding": "prose claims trace back to figures in the document",
}
FAMILY_ORDER = ["internal_arithmetic", "units", "period", "rounding",
                "selection", "direction", "grounding"]


def _claim_index(ledger_raw: dict | None) -> dict:
    idx = {}
    for c in (ledger_raw or {}).get("claims", []):
        idx[c.get("claim_id")] = c
    return idx


def coverage_story(raw: dict, claim_index: dict) -> tuple[list[str], list[str]]:
    """Two human lists: what was verified, and what could not be checked (and why)."""
    if raw.get("intake_error"):
        return [], [
            f"No report text was extracted: {raw['intake_error']}",
            "Supported report formats are HTML, Markdown, text, CSV, XLSX, PPTX, DOCX, and PDF.",
        ]
    if raw.get("agentic_only"):
        method = raw.get("extraction_method") or "a format adapter"
        if raw.get("deterministic_error"):
            checked = ([f"Visible content was extracted with {method} and read for material contradictions, staleness, logic, arithmetic, units, and selection errors."]
                       if raw.get("agentic_scan_completed") else [])
            unchecked = [
                "The rule-based document checks stopped before completion.",
                "The semantic review is the only substantive assessment available for this report."
                if raw.get("agentic_scan_completed") else
                "The semantic review also stopped before completion.",
            ]
            return checked, unchecked
        checked = ([f"Visible content was extracted with {method} and read for material contradictions, staleness, logic, arithmetic, units, and selection errors."]
                   if raw.get("agentic_scan_completed") else [])
        unchecked = [
            "Rule-based document checks are not yet available for this file format. The semantic review is receipted, but a clean result remains partial.",
            "No warehouse or application source was used unless a live-source section appears above.",
        ]
        return checked, unchecked
    cov = coverage(raw)
    total = claim_count(raw)
    findings = raw.get("findings") or []
    fired_families = {f.get("family") for f in findings if f.get("tier") in ("D", "C")}
    ran_families = {c.get("family") for c in raw.get("checks_run", [])}
    checked: list[str] = []
    verbs = [FAMILY_VERBS[fam] for fam in FAMILY_ORDER
             if fam in ran_families and fam not in fired_families and fam in FAMILY_VERBS]
    if verbs:
        checked.append("The document was checked for whether "
                       + "; ".join(verbs) + ".")
    elif total:
        checked.append("The document was read, but no complete check family could be claimed.")

    unchecked: list[str] = []
    unit_f = next((f for f in findings if f.get("check_id") == "uni_unit_unknown"), None)
    if unit_f:
        ids = list(unit_f.get("claim_ids") or [])
        if ids:
            unchecked.append(
                "Some numbers in prose did not state what they count or measure. "
                "Unit, scale, and like-for-like comparisons did not apply to those numbers; "
                "table arithmetic still ran where a total supplied enough structure.")
    reached = int(cov.get("claims_reached_by_a_check") or 0)
    if total and reached < total:
        n = total - reached
        unchecked.append(f"{n} figure{'s' if n != 1 else ''} had no applicable check at all.")
    src_fmt = (raw.get("source") or {}).get("format")
    if src_fmt and src_fmt != "html":
        unchecked.append(
            f"The file is {src_fmt}, so the figures were transcribed by a model "
            "before checking; the transcription itself is a step to verify.")
    unchecked.append("This was a document-only assessment. No claim was compared with a warehouse "
                     "or application source.")
    return checked, unchecked


def _title_of(f: dict) -> str:
    return TITLES.get(str(f.get("check_id")), FAMILY_TITLES.get(
        str(f.get("family")), "Problem found"))


def _where(loc) -> str:
    if not loc:
        return ""
    s = str(loc)
    if _re.fullmatch(r"[bct]\d{4}", s):
        return ""
    parts = s.split("/")
    if len(parts) == 3 and parts[0].startswith("table"):
        return f"in the ‘{parts[1]}’ row, ‘{parts[2]}’ column"
    if s == "footnote":
        return "in a footnote"
    return f"at {s}"


def _strip_ids(text: str) -> str:
    text = _re.sub(r"\b(prose block|table|chart)\s+[bct]\d{4}\b", r"a \1", str(text))
    text = _re.sub(r"\b[bct]\d{4}\b(,?\s*(and\s+)?)?", "", text)
    return _re.sub(r"\s{2,}", " ", text).strip()


def _numbers_line(f: dict) -> str:
    d = f.get("evidence") or {}
    if isinstance(d, dict) and "stated" in d and "computed" in d:
        parts = [f"Shown: {d['stated']:,.12g}.", f"Computed: {d['computed']:,.12g}."]
        if "discrepancy" in d:
            parts.append(f"Difference: {abs(d['discrepancy']):,.12g}.")
        band = d.get("summed_band")
        if isinstance(band, (int, float)):
            parts.append(f"Rounding allowance: {band:,.12g}.")
        return " ".join(parts)
    return ""


def html_of(art: dict, raw: dict | None = None,
            ledger_raw: dict | None = None, source: dict | None = None) -> str:
    def esc(x) -> str:
        return html.escape("" if x is None else str(x))

    layer2 = list(art.get("evidence_findings") or [])
    evidence_checks = list(art.get("evidence_checks") or [])
    evidence_coverage = art.get("evidence_coverage") or {}
    confirmed_checks = [
        check for check in evidence_checks if check.get("verdict") == "confirmed"]
    external_confirmed = [
        check for check in confirmed_checks if check.get("basis") == "evidence"]
    report_confirmed = [
        check for check in confirmed_checks if check.get("basis") == "report"]
    not_checkable_checks = [
        check for check in evidence_checks if check.get("verdict") == "not_checkable"]
    evidence_bound = [
        check for check in evidence_checks
        if _has_claim_evidence_receipt(check)
    ]
    decision = art.get("decision")
    actions = list(art.get("actions") or [])
    decision_limits = list(art.get("decision_limits") or [])
    checked_story, unchecked_story = ([], [])
    if raw is not None:
        checked_story, unchecked_story = coverage_story(raw, _claim_index(ledger_raw))
    if evidence_bound:
        checked_story.append(
            f"The semantic review produced {len(evidence_bound)} validated claim-to-evidence "
            f"receipt{'s' if len(evidence_bound) != 1 else ''}."
        )
        unchecked_story = [
            statement for statement in unchecked_story
            if "document-only grade" not in statement
            and "No claim was compared with a warehouse" not in statement
            and "No warehouse or application source was used" not in statement
        ]
        unchecked_story.append(
            "The file receipts do not prove when the evidence was retrieved.")
    elif raw is not None and raw.get("evidence_files"):
        count = len(raw["evidence_files"])
        unchecked_story.append(
            f"The semantic review received {count} supplied evidence "
            f"file{'s' if count != 1 else ''}, but no finding was bound to "
            "them with a claim-level evidence receipt."
        )
    errors = [f for f in art["findings"] if f.get("tier") == "D"]
    suspects = [f for f in art["findings"] if f.get("tier") != "D"]
    l2_high = [f for f in layer2 if f.get("severity") == "high"]

    source = art.get("source_result") or source
    source_status = (source or {}).get("status")
    source_failed = bool(source and source_status == "failed")
    source_partial = bool(source and source_status == "partial")
    source_unavailable = bool(source and source_status == "not_applicable")
    source_complete = bool(source and source_status in {None, "complete", "partial"})
    src_checks = (source or {}).get("checks", []) if source_complete else []
    src_bad = [c for c in src_checks if c.get("verdict") == "contradicted"]
    src_ok = [c for c in src_checks if c.get("verdict") == "confirmed"]
    src_changed = [
        c for c in src_checks if c.get("verdict") == "changed_since_report"]
    src_current_matches = [
        c for c in src_checks if c.get("verdict") == "matches_current_source"]
    src_not_run = [c for c in src_checks if c.get("verdict") == "not_run"]

    def time_label(value) -> str:
        text = str(value or "")
        return text.replace("T", " ").removesuffix("Z") + (" UTC" if text.endswith("Z") else "")
    if source_complete and not source_partial:
        # The live comparison supersedes the document-alone scope line.
        unchecked_story = [s for s in unchecked_story
                           if "No claim was compared with a warehouse" not in s
                           and "No warehouse or application source was used" not in s
                           and "document-only grade" not in s]
    elif source_failed:
        unchecked_story = [s for s in unchecked_story
                           if "No claim was compared with a warehouse" not in s
                           and "No warehouse or application source was used" not in s
                           and "document-only grade" not in s]
        unchecked_story.append(
            "The live source check did not complete. No report claim was cleared against current source data.")
    elif source_partial:
        unchecked_story.append(
            "One or more live queries did not return a result. Those report claims were not cleared against current source data.")
    elif source_unavailable:
        unchecked_story = [s for s in unchecked_story
                           if "No claim was compared with a warehouse" not in s
                           and "No warehouse or application source was used" not in s
                           and "document-only grade" not in s]
        unchecked_story.append(
            "The source was available, but the report contained no claim that mapped to its columns.")
    if src_changed:
        unchecked_story.append(
            f"{len(src_changed)} current-source difference"
            f"{'s were' if len(src_changed) != 1 else ' was'} measured after the report's "
            "snapshot date. The current query cannot prove those historical claims were wrong.")

    verdict = art["verdict"]
    verification = art.get("verification") or {}
    semantic_status = str((verification.get("semantic") or {}).get("status") or "not_run")
    proposed_count = int(evidence_coverage.get("claim_outcomes_proposed") or 0)
    validated_count = int(evidence_coverage.get("validated_outcomes") or 0)
    receipt_failures = int(evidence_coverage.get("receipt_failures") or 0)
    evidence_confirmed_count = int(evidence_coverage.get("evidence_confirmed") or 0)
    evidence_contradicted_count = int(evidence_coverage.get("evidence_contradicted") or 0)
    evidence_not_checkable_count = int(evidence_coverage.get("evidence_not_checkable") or 0)
    document_total = int(evidence_coverage.get("document_claims_total") or (
        claim_count(raw) if raw is not None else 0))
    document_reached = int(evidence_coverage.get("document_claims_reached") or (
        coverage(raw).get("claims_reached_by_a_check") if raw is not None else 0) or 0)

    v_title, v_line = VERDICT_LINES.get(verdict, (verdict, ""))
    assessed = assessment_line(verdict, art, raw)
    if assessed:
        v_title = "Assessment"
        v_line = assessed
    source_completed = len(src_ok) + len(src_bad) + len(src_changed) + len(src_current_matches)
    document_substantive = (
        ((verification.get("document") or {}).get("status") == "complete")
        and int((art.get("checks") or {}).get("registered") or 0) > 0
    )
    hollow = (
        verdict == "needs_review"
        and not art["findings"]
        and not layer2
        and not evidence_checks
        and not source_completed
        and not document_substantive
    )
    if hollow and not assessed:
        v_line = (
            "Nothing substantive could be verified: no document check, evidence receipt, "
            "or live-source check produced a result. Treat this as an incomplete "
            "assessment, not a clean bill."
        )

    if src_changed and not src_bad:
        dates = sorted({
            str(check.get("report_snapshot_date"))
            for check in src_changed if check.get("report_snapshot_date")
        })
        date_text = dates[0] if len(dates) == 1 else "the report snapshot"
        v_line += (
            f" {len(src_changed)} current-source difference"
            f"{'s were' if len(src_changed) != 1 else ' was'} measured after {date_text}. "
            "These differences do not prove the dated report was wrong."
        )

    def complete_sentence(value) -> str:
        text = _re.sub(r"\s+", " ", _re.sub(
            r"<[^>]+>", " ", str(value or ""))).strip()
        match = _re.match(r"^(.+?[.!?])(?:\s|$)", text)
        return match.group(1) if match else text

    customer_issue_count = len(art["findings"]) + len(layer2) + len(src_bad)
    takeaways = []
    takeaway_title = "What we verified and where to be careful"
    if evidence_coverage.get("evidence_files_supplied"):
        takeaways.append(
            f"Supplied evidence confirmed {evidence_confirmed_count} claims and contradicted "
            f"{evidence_contradicted_count}."
        )
    if document_total:
        takeaways.append(
            f"Document checks reached {document_reached} of {document_total} extracted numeric claims."
        )
    if receipt_failures:
        takeaways.append(
            f"{receipt_failures} proposed semantic outcomes had invalid receipts and were not counted."
        )
    if evidence_not_checkable_count:
        takeaways.append(
            f"{evidence_not_checkable_count} evidence-based claims were not established."
        )
    if verdict == "unable_to_grade":
        takeaways.append("No substantive assessment completed.")
    elif customer_issue_count:
        noun = "issue" if customer_issue_count == 1 else "issues"
        verb = "needs" if customer_issue_count == 1 else "need"
        takeaways.append(
            f"{customer_issue_count} {noun} {verb} correction or review.")
    elif src_changed:
        takeaways.append(
            "The live source has changed since this dated report; those differences are not proven report errors.")
    elif decision:
        pass
    elif verdict == "needs_review":
        takeaways.append(
            "No material issue was proven, but part of the assessment did not complete.")
    else:
        takeaways.append(
            "No issue was found in the checks that completed.")

    if src_bad:
        takeaways.append(
            f"First priority: reconcile the live-source difference for “{complete_sentence(src_bad[0].get('quote'))}”.")
    elif errors:
        summary = complete_sentence(
            _strip_ids(errors[0].get("statement")) or _title_of(errors[0]))
        takeaways.append(f"First priority: {summary}")
    elif layer2:
        summary = complete_sentence(
            layer2[0].get("explanation")
            or L2_TITLES.get(
                layer2[0].get("type"), "The report contradicts its evidence"))
        takeaways.append(f"First priority: {summary}")
    elif suspects:
        takeaways.append(f"First review item: {_title_of(suspects[0])}.")

    if not takeaways:
        takeaways.append("The detailed scope below shows exactly what was and was not checked.")
    takeaway_class = (
        "urgent" if verdict == "fix_first"
        else "positive" if verdict == "safe_to_share"
        else "caution"
    )
    takeaways_html = (
        f"<section class='takeaways {takeaway_class}' aria-labelledby='takeaways-title'>"
        f"<h2 id='takeaways-title'>{esc(takeaway_title)}</h2><ul>"
        + "".join(f"<li>{esc(item)}</li>" for item in takeaways)
        + "</ul></section>"
    )

    def block(f: dict) -> str:
        where = _where(f.get("location"))
        nums = _numbers_line(f)
        return (
            "<div class='f'>"
            f"<div class='t'>{esc(_title_of(f))}</div>"
            + (f"<div class='w'>{esc(where)}</div>" if where else "")
            + f"<div class='s'>{esc(_strip_ids(f.get('statement')))}</div>"
            + (f"<div class='n'>{esc(nums)}</div>" if nums else "")
            + "</div>"
        )

    def l2_block(f: dict) -> str:
        kind = f.get("type")
        outcome = f.get("verdict") or "contradicted"
        if outcome == "confirmed":
            title = ("Confirmed by supplied evidence"
                     if f.get("basis") == "evidence"
                     else "Internally supported by the report")
        elif outcome == "not_checkable":
            title = ("Not established by supplied evidence"
                     if f.get("basis") == "evidence"
                     else "Not established from the report")
        else:
            title = L2_TITLES.get(kind, "The report contradicts its evidence")
        if outcome == "not_checkable":
            receipt = ""
        elif f.get("report_quote_2"):
            receipt = (f"<div class='q'>Report also says: "
                       f"“{esc(f.get('report_quote_2'))}”</div>")
        elif f.get("basis") == "report":
            receipt = ""
        elif f.get("evidence_receipts"):
            receipt = "".join(
                f"<div class='q'>Evidence fields ({esc(group.get('evidence_file'))}): "
                f"<code>{esc(json.dumps(group.get('evidence_json') or [], ensure_ascii=False))}</code></div>"
                for group in f.get("evidence_receipts") or [])
        elif f.get("evidence_receipt_mode") == "json-pointers":
            receipt = (
                f"<div class='q'>Evidence fields ({esc(f.get('evidence_file'))}): "
                f"<code>{esc(json.dumps(f.get('evidence_json') or [], ensure_ascii=False))}</code></div>"
            )
        elif f.get("evidence_receipt_mode") == "json-object-fields":
            receipt = (f"<div class='q'>Evidence fields ({esc(f.get('evidence_file'))}): "
                       f"<code>{esc(f.get('evidence_quote'))}</code></div>")
        else:
            receipt = (f"<div class='q'>Evidence ({esc(f.get('evidence_file'))}): "
                       f"“{esc(f.get('evidence_quote'))}”</div>")
        return (
            "<div class='f'>"
            f"<div class='t'>{esc(title)}</div>"
            f"<div class='s'>{esc(f.get('explanation'))}</div>"
            f"<div class='q'>Report says: “{esc(f.get('report_quote'))}”</div>"
            + receipt
            + "</div>"
        )

    def src_block(c: dict) -> str:
        mism = c.get("mismatches") or {}

        def label(value) -> str:
            return str(value).replace("_", " ").strip().capitalize()

        def shown(value, reference=None) -> str:
            if isinstance(value, bool) or value is None:
                return str(value)
            try:
                number = Decimal(str(value).replace(",", "").replace("$", ""))
            except (InvalidOperation, ValueError):
                return str(value)
            if reference is not None:
                reference_text = str(reference).replace(",", "").replace("$", "").replace("%", "")
                try:
                    Decimal(reference_text)
                except InvalidOperation:
                    pass
                else:
                    places = len(reference_text.partition(".")[2]) if "." in reference_text else 0
                    return f"{number:,.{places}f}"
            rendered = f"{number:,f}"
            if "." in rendered:
                rendered = rendered.rstrip("0").rstrip(".")
            return rendered

        changed_since_report = c.get("verdict") == "changed_since_report"
        matches_current = c.get("verdict") == "matches_current_source"
        if c.get("missing_row"):
            lines = (
                "<div class='comparison'>"
                "<strong>Matching record</strong>"
                "<span>Report expects <b>Present</b></span>"
                "<span>Source result <b>No matching row</b></span>"
                "</div>"
            )
        else:
            lines = "".join(
                "<div class='comparison'>"
                f"<strong>{esc(label(k))}</strong>"
                f"<span>{'Report snapshot value' if changed_since_report or matches_current else 'Report value'} "
                f"<b>{esc(shown(v['expected']))}</b></span>"
                f"<span>{'Current source value' if changed_since_report or matches_current else 'Source value'} "
                f"<b>{esc(shown(v['actual'], v['expected']))}</b></span>"
                "</div>"
                for k, v in mism.items())
        receipt = c.get("receipt") or {}
        if receipt.get("kind") == "mcp":
            source_name = ((receipt.get("source") or {}).get("server_name")
                           or source.get("profile"))
            receipt_html = (
                "<details class='receipt'><summary>Direct MCP receipt</summary>"
                f"<code>Source: {esc(source_name)}\nTool: {esc(receipt.get('tool'))}\n"
                f"Arguments: {esc(json.dumps(receipt.get('arguments') or {}, ensure_ascii=False, sort_keys=True))}\n"
                f"Response SHA-256: {esc(receipt.get('response_sha256'))}\n"
                f"Raw response: {esc(receipt.get('response_path'))}\n"
                f"Value paths: {esc(json.dumps(receipt.get('value_paths') or {}, ensure_ascii=False, sort_keys=True))}</code>"
                "</details>"
            )
        else:
            receipt_html = (
                f"<details class='receipt'><summary>Read-only query receipt</summary>"
                f"<code>{esc(c.get('sql'))}</code></details>"
            )
        return (
            "<div class='f'>"
            f"<div class='t'>{esc('Source changed after this report' if changed_since_report else ('Still matches the current source' if matches_current else ('The source disagrees' if mism else 'Confirmed against the source')))}</div>"
            f"<div class='q'>Report says: “{esc(_re.sub(r'<[^>]+>', ' ', str(c.get('quote') or '')))}”</div>"
            + (f"<div class='s'>{esc(c.get('why'))}</div>" if changed_since_report or matches_current else "")
            + lines
            + f"<div class='w'>Queried {esc(time_label(c.get('queried_at') or source.get('generated_at')))}</div>"
            + receipt_html
            + "</div>"
        )

    lead_sections = []
    ledger_sections = []
    if evidence_checks or (raw is not None and raw.get("evidence_files")):
        document_total = int(evidence_coverage.get("document_claims_total") or (
            claim_count(raw) if raw is not None else 0))
        document_reached = int(evidence_coverage.get("document_claims_reached") or (
            coverage(raw).get("claims_reached_by_a_check") if raw is not None else 0) or 0)
        cited_count = len(evidence_coverage.get("evidence_files_cited") or [])
        supplied_count = int(evidence_coverage.get("evidence_files_supplied") or 0)
        provenance_count = len(evidence_coverage.get("provenance_groups") or [])
        lead_sections.append(
            "<details class='confidence'>"
            "<summary>What was checked</summary>"
            "<div class='confidence-grid'>"
            f"<div><strong>{document_reached} / {document_total}</strong><span>extracted numeric claims reached by document checks</span></div>"
            f"<div><strong>{evidence_coverage.get('evidence_confirmed', 0)}</strong><span>claims confirmed by supplied evidence</span></div>"
            f"<div><strong>{evidence_coverage.get('evidence_contradicted', 0)}</strong><span>claims contradicted by supplied evidence</span></div>"
            f"<div><strong>{evidence_coverage.get('evidence_not_checkable', 0)}</strong><span>evidence-based claims not established</span></div>"
            "</div>"
            f"<p>{evidence_coverage.get('validated_outcomes', 0)} of "
            f"{evidence_coverage.get('claim_outcomes_proposed', 0)} inventoried claim outcomes "
            "had valid receipts. "
            f"The report itself also supplied {evidence_coverage.get('report_confirmed', 0)} "
            "internally supported conclusions and "
            f"{evidence_coverage.get('report_contradicted', 0)} internal contradictions; these "
            "are shown separately from external evidence.</p>"
            f"<p>{cited_count} of {supplied_count} supplied evidence file"
            f"{'s were' if supplied_count != 1 else ' was'} cited by validated outcomes. "
            f"{evidence_coverage.get('receipt_failures', 0)} proposed outcome"
            f"{'s had' if evidence_coverage.get('receipt_failures', 0) != 1 else ' had'} an invalid receipt and "
            "were not counted. "
            f"The cited files form {provenance_count} declared provenance group"
            f"{'s' if provenance_count != 1 else ''}. File or group count is not a probability "
            "and is not treated as independent confirmation.</p>"
            "</details>"
        )
    if source_failed:
        lead_sections.append(
            "<section class='source-failed' aria-labelledby='source-failed-title'>"
            "<div><h2 id='source-failed-title'>Live source check did not complete</h2>"
            "<p>The document assessment is still available. No claim was cleared against current source data.</p></div>"
            f"<div class='source-detail'><span>Source</span><strong>{esc(source.get('profile'))}</strong>"
            f"<p>{esc(source.get('error') or 'The live source check did not complete.')}</p></div>"
            "</section>")
    elif source_partial:
        completed = len(src_ok) + len(src_bad) + len(src_changed) + len(src_current_matches)
        total = completed + len(src_not_run)
        lead_sections.append(
            "<section class='source-failed' aria-labelledby='source-partial-title'>"
            "<div><h2 id='source-partial-title'>Live source check was partially complete</h2>"
            f"<p>{completed} of {total} planned source checks returned receipts. "
            "The document and semantic findings are preserved.</p></div>"
            f"<div class='source-detail'><span>Source</span><strong>{esc(source.get('profile'))}</strong>"
            f"<p>{esc(source.get('error'))}</p></div>"
            "</section>")
    elif source_unavailable:
        suggested = source.get("suggested_source")
        lead_sections.append(
            "<section class='source-failed source-unavailable' aria-labelledby='source-unavailable-title'>"
            "<div><h2 id='source-unavailable-title'>This source was not authoritative for the report claims</h2>"
            "<p>The document and semantic assessment are still available."
            + (f" Connect or provide {esc(suggested)} for the unverified claims." if suggested else "")
            + "</p></div>"
            f"<div class='source-detail'><span>Source</span><strong>{esc(source.get('profile'))}</strong>"
            f"<p>{esc(source.get('error'))}</p></div>"
            "</section>")
    source_main, source_more = src_bad[:3], src_bad[3:]
    err_blocks = ([block(f) for f in errors] + [l2_block(f) for f in l2_high]
                  + [src_block(c) for c in source_main])
    if err_blocks:
        lead_sections.append("<section class='findings'><h2>Issues to fix</h2>" +
                        "".join(err_blocks) + "</section>")
    if source_more:
        ledger_sections.append(
            f"<details><summary>{len(source_more)} more live-source mismatch"
            f"{'es' if len(source_more) != 1 else ''}</summary>"
            + "".join(src_block(c) for c in source_more) + "</details>")
    if confirmed_checks:
        decision_support_ids = set((decision or {}).get("supporting_check_ids") or [])
        decision_confirmed = [
            check for check in confirmed_checks
            if check.get("id") in decision_support_ids
        ]
        material_external = [
            check for check in external_confirmed
            if check.get("importance") == "material"
            and check.get("id") not in decision_support_ids
        ]
        supporting_external = [
            check for check in external_confirmed
            if check.get("importance") != "material"
            and check.get("id") not in decision_support_ids
        ]
        remaining_report = [
            check for check in report_confirmed
            if check.get("id") not in decision_support_ids
        ]
        primary_confirmed = decision_confirmed or material_external
        if not decision_confirmed:
            material_external = []
        remaining_external = material_external + supporting_external
        ledger_sections.append(
            "<section class='findings confirmed'><h2>"
            + ("Evidence behind the assessment" if decision_confirmed else "Evidence confirmed")
            + "</h2>"
            + "".join(l2_block(check) for check in primary_confirmed)
            + ("<details><summary>"
               f"{len(remaining_external)} additional external-evidence confirmation"
               f"{'s' if len(remaining_external) != 1 else ''}</summary>"
               + "".join(l2_block(check) for check in remaining_external)
               + "</details>" if remaining_external else "")
            + ("<details><summary>"
               f"{len(remaining_report)} additional internal consistency conclusion"
               f"{'s' if len(remaining_report) != 1 else ''}</summary>"
               + "".join(l2_block(check) for check in remaining_report)
               + "</details>" if remaining_report else "")
            + "</section>"
        )
    if not_checkable_checks:
        lead_sections.append(
            "<section class='findings review'><h2>What was not established</h2>"
            + "".join(l2_block(check) for check in not_checkable_checks)
            + "</section>"
        )
    if src_changed:
        lead_sections.append(
            "<section class='findings review'><h2>Source changes since this report</h2>"
            + "".join(src_block(c) for c in src_changed) + "</section>")
    if src_current_matches:
        ledger_sections.append(
            "<section class='findings confirmed'><h2>Current values that still match this report</h2>"
            + "".join(src_block(c) for c in src_current_matches) + "</section>")
    sus_blocks = [block(f) for f in suspects] + [l2_block(f) for f in layer2 if f not in l2_high]
    if sus_blocks:
        lead_sections.append("<section class='findings review'><h2>Items to review</h2>" +
                        "".join(sus_blocks) + "</section>")
    if src_ok:
        ledger_sections.append("<section class='findings confirmed'><h2>Confirmed against the live source</h2>"
                        + "".join(src_block(c) for c in src_ok) + "</section>")
    if src_not_run:
        lead_sections.append(
            f"<details><summary>{len(src_not_run)} source check"
            f"{'s' if len(src_not_run) != 1 else ''} could not run</summary><ul>"
            + "".join(f"<li>{esc(c.get('why') or 'No result')}</li>" for c in src_not_run)
            + "</ul></details>")
    if decision:
        conclusion_points = [
            complete_sentence(point.get("text"))
            for point in decision.get("key_points") or []
            if complete_sentence(point.get("text"))
        ]
        lead_sections.append(
            "<section class='decision-summary' aria-labelledby='report-conclusion-title'>"
            "<h2 id='report-conclusion-title'>What the report itself concludes</h2>"
            f"<p class='decision-text'>{esc(decision.get('text'))}</p>"
            + ("<ul>" + "".join(
                f"<li>{esc(point)}</li>" for point in conclusion_points) + "</ul>"
               if conclusion_points else "")
            + "<details class='receipt'><summary>Report receipt</summary>"
            f"<div class='q'>“{esc(decision.get('report_quote'))}”</div></details>"
            "<p>This is the report's own conclusion, shown for context — it is not a "
            "Summation finding. Whether its claims survive verification is stated at "
            "the top of this page and receipted below.</p>"
            "</section>"
        )
    action_ids = set((decision or {}).get("recommended_action_ids") or [])
    primary_actions = ([item for item in actions if item.get("id") in action_ids]
                       if action_ids else actions)
    other_actions = [item for item in actions if item not in primary_actions]
    if primary_actions:
        lead_sections.append(
            "<section class='actions' aria-labelledby='actions-title'>"
            "<h2 id='actions-title'>What to do</h2><ol>"
            + "".join(
                f"<li><strong>{esc(item.get('text'))}</strong>"
                f"<details class='receipt'><summary>Report receipt</summary>"
                f"<div class='q'>“{esc(item.get('report_quote'))}”</div></details></li>"
                for item in primary_actions
            )
            + "</ol>"
            + ("<details><summary>"
               f"{len(other_actions)} additional receipted action"
               f"{'s' if len(other_actions) != 1 else ''}</summary><ol>"
               + "".join(
                   f"<li><strong>{esc(item.get('text'))}</strong>"
                   f"<details class='receipt'><summary>Report receipt</summary>"
                   f"<div class='q'>“{esc(item.get('report_quote'))}”</div></details></li>"
                   for item in other_actions)
               + "</ol></details>" if other_actions else "")
            + "</section>"
        )
    limit_ids = set((decision or {}).get("key_limit_ids") or [])
    primary_limits = ([item for item in decision_limits if item.get("id") in limit_ids]
                      if limit_ids else decision_limits)
    other_limits = [item for item in decision_limits if item not in primary_limits]
    if primary_limits:
        lead_sections.append(
            "<section class='limits' aria-labelledby='limits-title'>"
            "<h2 id='limits-title'>What this does not prove</h2><ul>"
            + "".join(
                f"<li><strong>{esc(item.get('text'))}</strong>"
                f"<details class='receipt'><summary>Report receipt</summary>"
                f"<div class='q'>“{esc(item.get('report_quote'))}”</div></details></li>"
                for item in primary_limits
            )
            + "</ul>"
            + ("<details><summary>"
               f"{len(other_limits)} additional receipted limit"
               f"{'s' if len(other_limits) != 1 else ''}</summary><ul>"
               + "".join(
                   f"<li><strong>{esc(item.get('text'))}</strong>"
                   f"<details class='receipt'><summary>Report receipt</summary>"
                   f"<div class='q'>“{esc(item.get('report_quote'))}”</div></details></li>"
                   for item in other_limits)
               + "</ul></details>" if other_limits else "")
            + "</section>"
        )
    if verdict == "unable_to_grade" and not err_blocks and not sus_blocks:
        semantic_status = ((verification.get("semantic") or {}).get("status"))
        if semantic_status == "failed":
            lead_sections.append(
                "<p class='warn'>The semantic review did not complete. "
                "The extracted report remains available for one retry.</p>")
        elif raw and raw.get("intake_error"):
            lead_sections.append(
                "<p class='warn'>No report checks ran because no supported report was found.</p>")
        else:
            lead_sections.append(
                "<p class='warn'>No substantive report check completed. "
                "See the verification scope below.</p>")
    elif src_changed and not err_blocks and not sus_blocks:
        lead_sections.append(
            "<p class='ok'>No report error was proven by the current-source differences.</p>")
    elif decision or evidence_checks:
        pass
    elif not err_blocks and not sus_blocks:
        lead_sections.append("<p class='ok'>No errors found in what could be checked.</p>")

    if hollow:
        reasons = []
        for stage_info in (
                verification.get("document") or {},
                verification.get("semantic") or {},
                verification.get("live_source") or {}):
            detail = str(stage_info.get("detail") or "").strip()
            if detail:
                reasons.append(detail)
        reasons.extend(str(item) for item in art["limitations"])
        if not reasons:
            reasons.append("No stage produced a checkable result.")
        takeaways_html = ""
        lead_sections = [
            section for section in lead_sections
            if "source-failed" in section or "source-unavailable" in section]
        lead_sections.append(
            "<section class='takeaways caution' aria-labelledby='hollow-title'>"
            "<h2 id='hollow-title'>Why this assessment is incomplete</h2><ul>"
            + "".join(f"<li>{esc(reason)}</li>" for reason in reasons)
            + "</ul></section>"
        )
        ledger_sections = []

    checks = art["checks"]
    if unchecked_story:
        cov_html = (
            "<h3>What was verified</h3><ul>"
            + "".join(f"<li>{esc(x)}</li>" for x in checked_story)
            + "</ul><h3>What could not be checked, and why</h3><ul>"
            + "".join(f"<li>{esc(x)}</li>" for x in unchecked_story)
            + "</ul>"
        )
    else:
        cov_html = "<ul>" + "".join(f"<li>{esc(x)}</li>" for x in art["limitations"]) + "</ul>"
    src = art["source"]

    stage_labels = {
        "complete": "Complete",
        "partial": "Partially complete",
        "failed": "Did not complete",
        "not_available": "Not available",
        "not_requested": "Not checked",
        "not_run": "Not checked",
        "skipped": "Skipped",
    }
    def stage(name: str, title: str, complete_detail: str) -> str:
        info = verification.get(name) or {}
        status = str(info.get("status") or "not_run")
        detail = info.get("detail") or complete_detail
        return (
            "<div class='stage'>"
            f"<div><strong>{esc(title)}</strong><p>{esc(detail)}</p></div>"
            f"<span class='stage-status {esc(status)}'>{esc(stage_labels.get(status, status))}</span>"
            "</div>")

    scope_rows = (
        stage("document", "Document checks",
              "Rule-based checks ran on the report structure and numbers.")
        + stage("semantic", "Semantic review",
                "A fresh semantic review ran. Semantic findings appear only with exact report receipts.")
        + stage("live_source", "Direct live source",
                "Read-only source checks ran and produced query receipts.")
    )
    diagnostics_note = (f"{len(art['diagnostics'])} scanner note"
                        f"{'s were' if len(art['diagnostics']) != 1 else ' was'} "
                        "kept out of customer findings.")

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Report assessment: {esc(src.get('path'))}</title>
<style>
 :root{{color-scheme:light;--ink:#16202a;--muted:#596776;--line:#d9e0e7;--paper:#fff;--canvas:#eef2f5;--navy:#173f5f;--red:#a93a32;--red-soft:#fff5f3;--amber:#8a5a0b;--amber-soft:#fff8e8;--green:#276749;--green-soft:#edf8f2;--blue-soft:#edf4fa}}
 *{{box-sizing:border-box}}
 body{{margin:0;background:var(--canvas);color:var(--ink);font:15.5px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}
 main{{width:min(940px,calc(100% - 40px));margin:40px auto;background:var(--paper);border:1px solid var(--line);border-radius:14px;box-shadow:0 18px 55px rgba(23,63,95,.09);overflow:hidden}}
 .header{{padding:34px 42px 30px;border-bottom:1px solid var(--line)}}
 .kicker{{margin:0 0 8px;color:var(--navy);font-size:11px;font-weight:750;letter-spacing:.14em;text-transform:uppercase}}
 h1{{margin:0;max-width:760px;font-size:clamp(23px,3vw,34px);line-height:1.16;letter-spacing:-.025em;overflow-wrap:anywhere}}
 .verdict{{display:grid;grid-template-columns:minmax(190px,.8fr) 2fr;gap:24px;align-items:start;margin-top:28px;padding-top:24px;border-top:1px solid var(--line)}}
 .vt{{font-size:23px;line-height:1.2;font-weight:780;color:var(--red)}}
 .vl{{max-width:620px;margin:0;color:var(--muted);font-size:16px}}
 .body{{padding:10px 42px 40px}}
 h2{{margin:30px 0 12px;font-size:18px;line-height:1.25;letter-spacing:-.01em}}
 .takeaways{{margin:24px 0 4px;padding:18px 20px;border:1px solid #b9cddd;border-left:4px solid var(--navy);border-radius:9px;background:var(--blue-soft)}}
 .takeaways.urgent{{border-color:#e4c2be;border-left-color:var(--red);background:var(--red-soft)}}
 .takeaways.caution{{border-color:#e7c87d;border-left-color:var(--amber);background:var(--amber-soft)}}
 .takeaways.positive{{border-color:#cfe4d8;border-left-color:var(--green);background:var(--green-soft)}}
 .takeaways h2{{margin:0 0 7px;font-size:16px}} .takeaways ul{{margin:0;padding-left:19px}}
 .takeaways li{{margin-bottom:4px}} .takeaways li:last-child{{margin-bottom:0}}
 .decision-summary{{margin:28px 0 4px;padding:22px 24px;border:1px solid #b9cddd;border-radius:10px;background:var(--blue-soft)}}
 .decision-summary h2{{margin:0 0 8px}} .decision-text{{margin:0 0 8px;font-size:19px;font-weight:760;line-height:1.4;color:var(--navy)}}
 .decision-summary p:last-of-type{{margin-bottom:0;color:#40586b}}
 .confidence{{margin:24px 0 4px;padding:20px 22px;border:1px solid var(--line);border-radius:10px;background:#fafbfd}}
 .confidence h2{{margin:0 0 14px}} .confidence p{{margin:14px 0 0;color:var(--muted)}}
 .confidence-grid{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}}
 .confidence-grid div{{padding:12px;border:1px solid var(--line);border-radius:8px;background:#fff}}
 .confidence-grid strong{{display:block;font-size:20px;color:var(--navy)}} .confidence-grid span{{display:block;margin-top:3px;color:var(--muted);font-size:12.5px;line-height:1.35}}
 .actions,.limits{{margin-top:28px;padding:20px 22px;border:1px solid var(--line);border-radius:10px}}
 .actions h2,.limits h2{{margin:0 0 10px}} .actions li,.limits li{{margin-bottom:12px}}
 .source-failed{{display:grid;grid-template-columns:1.15fr .85fr;gap:22px;margin:24px 0 4px;padding:20px 22px;border:1px solid #e7c87d;border-radius:10px;background:var(--amber-soft)}}
 .source-failed h2{{margin:0 0 4px;color:#6f4808}}
 .source-failed p{{margin:0;color:#655536}}
 .source-detail{{padding-left:20px;border-left:1px solid #e3ca8b}}
 .source-detail span{{display:block;color:#806523;font-size:11px;font-weight:750;letter-spacing:.08em;text-transform:uppercase}}
 .source-detail strong{{display:block;margin:2px 0 5px}}
 .source-unavailable{{border-color:#b9cddd;background:var(--blue-soft)}}
 .source-unavailable h2{{color:var(--navy)}} .source-unavailable p{{color:#40586b}}
 .source-unavailable .source-detail{{border-color:#b9cddd}} .source-unavailable .source-detail span{{color:var(--navy)}}
 .findings{{margin-top:26px}}
 .f{{margin:12px 0;padding:18px 20px;border:1px solid #e4d9d7;border-left:4px solid var(--red);border-radius:9px;background:var(--red-soft)}}
 .review .f{{border-color:#eadfbe;border-left-color:var(--amber);background:var(--amber-soft)}}
 .confirmed .f{{border-color:#cfe4d8;border-left-color:var(--green);background:var(--green-soft)}}
 .t{{font-weight:760;font-size:16.5px}}
 .w{{color:var(--muted);font-size:13px;margin-top:2px}}
 .s{{margin-top:8px;max-width:78ch}}
 .n{{margin-top:10px;padding:8px 10px;border-radius:6px;background:#fff;color:var(--navy);font:13px/1.45 ui-monospace,SFMono-Regular,Menlo,monospace}}
 .comparison{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin-top:9px;padding:10px 12px;border-radius:6px;background:#fff;color:#344251;font-size:13px}}
 .comparison span{{border-left:1px solid var(--line);padding-left:10px}} .comparison b{{display:block;color:var(--navy);font:13px/1.4 ui-monospace,SFMono-Regular,Menlo,monospace}}
 .q{{margin-top:9px;padding:9px 12px;border-left:2px solid #aebdca;background:rgba(255,255,255,.72);color:#344251;font-size:14px}}
 details{{margin-top:18px}} summary{{cursor:pointer;color:#465566;font-weight:700}}
 details.receipt{{font-size:12px}} details.receipt code{{display:block;white-space:pre-wrap;margin-top:7px;color:var(--navy)}}
 .scope{{margin-top:34px;padding-top:4px;border-top:1px solid var(--line)}}
 .stage{{display:grid;grid-template-columns:1fr auto;gap:18px;align-items:center;padding:14px 0;border-bottom:1px solid var(--line)}}
 .stage strong{{font-size:14px}} .stage p{{margin:2px 0 0;color:var(--muted);font-size:13.5px}}
 .stage-status{{font-size:12px;font-weight:760;color:var(--muted)}}
 .stage-status.complete{{color:var(--green)}} .stage-status.partial{{color:var(--amber)}} .stage-status.failed{{color:var(--red)}}
 ul{{margin:8px 0;padding-left:20px}} li{{margin-bottom:6px}}
 .coverage{{margin-top:20px;color:#344251}} .coverage h3{{font-size:14px;margin:16px 0 5px}}
 .next{{margin-top:30px;padding:18px 20px;border-radius:9px;background:var(--blue-soft);color:#173b58;font-weight:700}}
 .technical{{margin-top:24px;padding-top:18px;border-top:1px solid var(--line);font-size:12.5px;color:var(--muted)}}
 .technical p{{overflow-wrap:anywhere}}
 .meta{{font:11.5px/1.55 ui-monospace,SFMono-Regular,Menlo,monospace;color:#718091}}
 @media(max-width:700px){{main{{width:100%;margin:0;border:0;border-radius:0;box-shadow:none}}.header,.body{{padding-left:22px;padding-right:22px}}.verdict,.source-failed,.comparison,.confidence-grid{{grid-template-columns:1fr}}.source-detail{{padding:14px 0 0;border-left:0;border-top:1px solid #e3ca8b}}.comparison span{{border-left:0;padding-left:0}}.stage{{align-items:start}}}}
 @media print{{body{{background:#fff}}main{{width:100%;margin:0;border:0;box-shadow:none}}.technical{{display:none}}}}
</style></head><body><main>
<header class="header">
  <p class="kicker">Summation report assessment</p>
  <h1>{esc(src.get('path'))}</h1>
  <div class="verdict"><div class="vt">{esc(v_title)}</div><p class="vl">{esc(v_line)}</p></div>
</header>
<div class="body">
{takeaways_html}
{''.join(lead_sections + ledger_sections)}
<section class="scope"><h2>Verification scope</h2>{scope_rows}</section>
<div class="coverage">{cov_html}</div>
<div class="next">{esc(art['offer']['text'])}</div>
<details class="technical"><summary>Technical details</summary>
  <p>{checks['registered']} checks ran. {checks['errored']} checks reported an error. {esc(diagnostics_note)}</p>
  <p class="meta">Run {esc(art['run_id'])} | {esc(art['generated_at'])} | {esc(src.get('sha256'))} | {esc(art['schema_version'])}</p>
</details>
</div></main></body></html>
"""


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
    args = p.parse_args()
    if not args.findings.is_file():
        print(f"render: missing {args.findings}", file=sys.stderr)
        return 2
    raw = json.loads(args.findings.read_text())
    layer2 = []
    guidance = {"decision": None, "actions": [], "limits": []}
    if args.layer2 and args.layer2.is_file():
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
            guidance = {
                "decision": l2raw.get("decision"),
                "actions": l2raw.get("actions") or [],
                "limits": l2raw.get("limits") or [],
            }
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
    run_id = args.run_id or args.findings.parent.parent.name
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    art = artifact_from_findings(raw, run_id=run_id, generated_at=generated_at,
                                 layer2=layer2, source=source, guidance=guidance)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "grade-artifact.json").write_text(json.dumps(art, indent=2) + "\n")
    (args.out_dir / "grade-artifact.html").write_text(html_of(art, raw, ledger_raw))
    print(args.out_dir / "grade-artifact.json")
    print(args.out_dir / "grade-artifact.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
