#!/usr/bin/env python3
"""Render grade-artifact/public-receipt-v1 from coldverify findings.json. Fail closed."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
from severity import normalize_severity  # noqa: E402

SCHEMA_VERSION = "grade-artifact/public-receipt-v1"
MIN_CLAIMS = 1
SHAREABLE_CHECK_KEYS = (
    "id", "type", "basis", "verdict", "importance", "severity",
    "claim_id", "public_receipt", "report_quote", "explanation", "location",
    "report_value", "current_as_of", "current_value",
    "reconstruction_attempt", "report_date",
)

CLAIM_PUBLIC_KEYS = (
    "id", "quote", "importance", "outcome", "check_id",
    "location", "classification", "verification_mode",
)
GROUNDED_OUTCOMES = frozenset({
    "confirmed", "contradicted", "not_checkable", "changed_since_report", "error",
    "used_for_internal_arithmetic",
})
ERROR_CLAIM_OUTCOMES = frozenset({"contradicted", "error"})
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
    "sources",
)
VERDICTS = frozenset(
    {"safe_to_share", "share_with_caveats", "fix_first", "unable_to_grade"}
)
PUBLIC_VERDICTS = VERDICTS
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
            items = inv.get("items") or []
            return bool(items) and all(
                item.get("importance") == "supporting" for item in items)
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
    name = Path(raw_path).name if raw_path else ""
    source_format = str(src.get("format") or "unknown")
    period_label = src.get("period_label")
    report_date = src.get("report_date")
    if not _publishable_text(name) or not _publishable_text(source_format):
        raise SystemExit("render: report source metadata is not publishable")
    for value in (period_label, report_date):
        if value not in (None, "") and not _publishable_text(value):
            raise SystemExit("render: report source metadata is not publishable")
    return {
        "path": name,
        "format": source_format,
        "sha256": src.get("sha256"),
        "period_label": period_label,
        "report_date": report_date,
    }


ABS_PATH = re.compile(
    r'(?:^|[\s"\'])((?:/Users|/home|/var|/tmp|/private)/[^\s"\']+)',
    re.I,
)
TENANT_IDENTIFIER = re.compile(
    r"\b(?:tenant|organization|org)[ _-]?id\b\s*[:=]\s*[\"']?[A-Za-z0-9_-]+",
    re.I,
)
CREDENTIAL = re.compile(
    r"\b(?:api[ _-]?key|access[ _-]?token|refresh[ _-]?token|client[ _-]?secret|"
    r"password|credential)\b\s*[:=]\s*[^\s,;}]+",
    re.I,
)
BEARER = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", re.I)
PRIVATE_NAMES = frozenset({
    "receipts.json", "findings.json", "checks.json", "claims.json",
    "grade-artifact.json", "report-visible.txt", "ledger.json",
    "source-findings.json", "provenance.json",
})

def public_explanation(check: dict) -> str:
    """Return only the explicit agent-authored explanation."""
    receipt = check.get("public_receipt")
    if isinstance(receipt, dict):
        return str(receipt.get("explanation") or "").strip()
    return str(check.get("explanation") or "").strip()


VAGUE_OPERAND = re.compile(r"^(?:row|operand|item|value)(?:\s+\d+)?$", re.I)
VAGUE_SOURCE = re.compile(
    r"^(?:source|evidence|supplied evidence|recorded evidence|live data)$", re.I)
SOURCE_ID = re.compile(r"^[A-Za-z][A-Za-z0-9._-]*$")
ISO_TIME = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)
RAW_OFFICE_TOKEN = re.compile(r"\b(?:slide|shape)\d+\b", re.I)


def _publishable_text(value, *, operand_label: bool = False) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    if (
        ABS_PATH.search(text)
        or re.fullmatch(r"(?:/[A-Za-z0-9_~.-]+)+", text)
        or RAW_OFFICE_TOKEN.search(text)
        or TENANT_IDENTIFIER.search(text)
        or CREDENTIAL.search(text)
        or BEARER.search(text)
        or any(name.lower() in text.lower() for name in PRIVATE_NAMES)
    ):
        return False
    if operand_label and VAGUE_OPERAND.fullmatch(text):
        return False
    return True


def _publishable_metadata(value) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            if re.search(
                r"(?:password|secret|credential|api[_-]?key|access[_-]?token|"
                r"refresh[_-]?token)", str(key), re.I
            ):
                return False
            if not _publishable_metadata(child):
                return False
        return True
    if isinstance(value, list):
        return all(_publishable_metadata(child) for child in value)
    if value is None or isinstance(value, (bool, int, float)):
        return True
    return _publishable_text(value)


def _publishable_operand(value) -> bool:
    if not isinstance(value, dict) or set(value) != {"label", "value", "location"}:
        return False
    if not _publishable_text(value.get("label"), operand_label=True):
        return False
    if not _publishable_text(value.get("location")):
        return False
    shown = value.get("value")
    if shown in (None, "") or isinstance(shown, bool):
        return False
    return not isinstance(shown, str) or _publishable_text(shown)


def _substantive_public(value) -> bool:
    text = str(value or "").strip()
    return bool(
        _publishable_text(text)
        and len(re.findall(r"[A-Za-z0-9%$]+", text)) >= 6
        and re.search(r"[.!?]$", text)
    )


def _publishable_receipt(receipt, *, basis: str,
                         source_ids: set[str]) -> bool:
    if not isinstance(receipt, dict):
        return False
    allowed = {
        "report_operand", "decisive_operands", "explanation",
        "calculation", "source_id",
    }
    if set(receipt) - allowed:
        return False
    if not _publishable_operand(receipt.get("report_operand")):
        return False
    operands = receipt.get("decisive_operands")
    if not isinstance(operands, list) or not operands:
        return False
    if not all(_publishable_operand(row) for row in operands):
        return False
    explanation = str(receipt.get("explanation") or "").strip()
    if not _substantive_public(explanation):
        return False
    calculation = receipt.get("calculation")
    if calculation is not None:
        if not isinstance(calculation, dict) or set(calculation) != {"expression", "result"}:
            return False
        if not _publishable_text(calculation.get("expression")):
            return False
        result = calculation.get("result")
        if result in (None, "") or isinstance(result, bool):
            return False
        if isinstance(result, str) and not _publishable_text(result):
            return False
    source_id = str(receipt.get("source_id") or "").strip()
    if basis == "evidence":
        return bool(source_id and source_id in source_ids)
    return not source_id


def _public_sources(sources: list[dict] | None) -> list[dict]:
    public = []
    seen = set()
    for source in sources or []:
        if not isinstance(source, dict):
            raise SystemExit("render: retained source metadata is not publishable")
        source_id = str(source.get("id") or "").strip()
        kind = str(source.get("kind") or "").strip()
        label = str(source.get("label") or "").strip()
        filename = str(source.get("evidence_file") or "").strip()
        digest = str(source.get("result_sha256") or "").strip()
        allowed = {"id", "kind", "label", "evidence_file", "result_sha256", "retrieval"}
        if (
            set(source) - allowed
            or not source_id
            or not SOURCE_ID.fullmatch(source_id)
            or source_id in seen
            or kind not in {"supplied_file", "live_tool"}
            or not _publishable_text(label)
            or VAGUE_SOURCE.fullmatch(label)
            or not filename
            or Path(filename).name != filename
            or filename in PRIVATE_NAMES
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
        ):
            raise SystemExit("render: retained source metadata is not publishable")
        retrieval = source.get("retrieval")
        if kind == "supplied_file" and retrieval is not None:
            raise SystemExit("render: supplied_file cannot carry live retrieval metadata")
        if kind == "live_tool" and not isinstance(retrieval, dict):
            raise SystemExit("render: live_tool retrieval metadata is missing")
        row = {
            "id": source_id,
            "kind": kind,
            "label": label,
            "evidence_file": filename,
            "result_sha256": digest,
        }
        if kind == "live_tool":
            if set(retrieval) != {"retrieved_at", "tool", "arguments"}:
                raise SystemExit("render: live_tool retrieval metadata is not publishable")
            row["retrieval"] = {
                "retrieved_at": retrieval.get("retrieved_at"),
                "tool": retrieval.get("tool"),
                "arguments": retrieval.get("arguments"),
            }
            if not ISO_TIME.fullmatch(str(row["retrieval"]["retrieved_at"] or "")):
                raise SystemExit("render: live_tool retrieval metadata is not publishable")
            if not _publishable_text(row["retrieval"]["tool"]):
                raise SystemExit("render: live_tool retrieval metadata is not publishable")
            if not isinstance(row["retrieval"]["arguments"], dict) or not _publishable_metadata(
                row["retrieval"]["arguments"]
            ):
                raise SystemExit("render: live_tool retrieval arguments are not publishable")
        seen.add(source_id)
        public.append(row)
    return public


def _public_layer2(layer2: list[dict] | None, *,
                   sources: list[dict] | None = None) -> list[dict]:
    """Serialize accepted checks without deriving any public semantics."""
    public_sources = _public_sources(sources)
    source_ids = {str(row["id"]) for row in public_sources}
    public = []
    decisive = {"confirmed", "contradicted", "changed_since_report"}
    for raw in layer2 or []:
        if not isinstance(raw, dict):
            raise SystemExit("render: accepted check is not an object")
        row = {
            "id": raw.get("id"),
            "type": raw.get("type"),
            "basis": raw.get("basis"),
            "verdict": raw.get("verdict"),
            "importance": raw.get("importance"),
            "severity": raw.get("severity"),
            "claim_id": raw.get("claim_id"),
        }
        verdict = str(row.get("verdict") or "").strip()
        if verdict and verdict not in {
            "confirmed", "contradicted", "not_checkable",
            "changed_since_report",
        }:
            raise SystemExit(f"render: unknown accepted verdict {verdict!r}")
        if (
            not all(str(row.get(key) or "").strip() for key in (
                "id", "type", "basis", "verdict", "importance", "claim_id"
            ))
            or not all(_publishable_text(row.get(key)) for key in (
                "id", "type", "claim_id"
            ))
            or not SOURCE_ID.fullmatch(str(row["id"]))
            or row["basis"] not in {"report", "evidence"}
            or row["importance"] not in {"material", "supporting"}
            or row["severity"] not in {None, "high", "medium", "low"}
        ):
            raise SystemExit("render: accepted check metadata is incomplete")
        if verdict in decisive:
            receipt = raw.get("public_receipt")
            if not _publishable_receipt(
                receipt, basis=str(row["basis"]), source_ids=source_ids
            ):
                raise SystemExit("render: public_receipt is not publishable")
            row["public_receipt"] = receipt
            if verdict == "changed_since_report":
                for key in (
                    "report_value", "current_value", "current_as_of",
                    "report_date", "reconstruction_attempt",
                ):
                    value = raw.get(key)
                    if value in (None, ""):
                        raise SystemExit(
                            "render: changed_since_report metadata is incomplete")
                    if isinstance(value, str) and not _publishable_text(value):
                        raise SystemExit(
                            "render: changed_since_report metadata is not publishable")
                    row[key] = value
        elif verdict == "not_checkable":
            quote = str(raw.get("report_quote") or "").strip()
            explanation = str(raw.get("explanation") or "").strip()
            location = str(raw.get("location") or "").strip()
            if not _publishable_text(quote) or not _substantive_public(explanation):
                raise SystemExit("render: not_checkable copy is not publishable")
            row.update({"report_quote": quote, "explanation": explanation})
            if location:
                if not _publishable_text(location):
                    raise SystemExit("render: not_checkable location is not publishable")
                row["location"] = location
        else:
            raise SystemExit(f"render: unknown accepted verdict {verdict!r}")
        public.append({
            key: row[key]
            for key in SHAREABLE_CHECK_KEYS
            if key in row and (
                key == "severity" or row[key] not in (None, [], {})
            )
        })
    return public


def _material_claims(raw: dict) -> list[dict]:
    return [
        row for row in (raw.get("claims") or [])
        if isinstance(row, dict)
        and row.get("classification") != "supporting_provenance"
        and row.get("importance") != "supporting"
    ]


def _supporting_claims(raw: dict) -> list[dict]:
    return [
        row for row in (raw.get("claims") or [])
        if isinstance(row, dict) and (
            row.get("classification") == "supporting_provenance"
            or row.get("importance") == "supporting"
        )
    ]


def _public_score(raw: dict, checks: list[dict], headline: dict) -> dict | None:
    material_claims = _material_claims(raw)
    if material_claims:
        n = len(material_claims)
        d = sum(row.get("outcome") in ERROR_CLAIM_OUTCOMES for row in material_claims)
    else:
        material_checks = [row for row in checks if row.get("importance") == "material"]
        n = len(material_checks)
        d = sum(
            row.get("verdict") in ERROR_CLAIM_OUTCOMES for row in material_checks)
    if n:
        return {"kind": "tier_d_per_100_claims", "value": 100.0 * d / n}
    if "tier_d_per_100_claims" in headline:
        return {
            "kind": "tier_d_per_100_claims",
            "value": headline["tier_d_per_100_claims"],
        }
    return None


def _evidence_coverage(raw: dict, checks: list[dict],
                       sources: list[dict]) -> dict:
    by_id = {str(row.get("id") or ""): row for row in sources}
    cited_ids = set()
    for check in checks:
        if check.get("basis") != "evidence":
            continue
        if check.get("verdict") not in {
                "confirmed", "contradicted", "changed_since_report"}:
            continue
        receipt = check.get("public_receipt") or {}
        source_id = str(receipt.get("source_id") or "")
        if source_id:
            cited_ids.add(source_id)
    material_checks = [
        check for check in checks if check.get("importance") == "material"]
    external = [check for check in material_checks if check.get("basis") == "evidence"]
    internal = [check for check in material_checks if check.get("basis") == "report"]
    review = raw.get("evidence_review") or {}
    material_claims = _material_claims(raw)
    supporting = _supporting_claims(raw)
    if material_claims:
        total = len(material_claims)
        reached = sum(
            row.get("outcome") not in (None, "not_reached", "supporting")
            for row in material_claims)
        confirmed_n = sum(row.get("outcome") == "confirmed" for row in material_claims)
        contradicted_n = sum(
            row.get("outcome") in ERROR_CLAIM_OUTCOMES for row in material_claims)
        not_checkable_n = sum(
            row.get("outcome") in {
                None, "not_reached", "not_checkable", "used_for_internal_arithmetic"}
            for row in material_claims)
    else:
        total = claim_count(raw) or len(material_checks)
        reached = int(coverage(raw).get("claims_reached_by_a_check") or len(material_checks))
        confirmed_n = sum(check.get("verdict") == "confirmed" for check in material_checks)
        contradicted_n = sum(
            check.get("verdict") in ERROR_CLAIM_OUTCOMES for check in material_checks)
        not_checkable_n = sum(
            check.get("verdict") == "not_checkable" for check in material_checks)
    cited_safe = [
        str(by_id[source_id].get("label") or source_id)
        for source_id in sorted(cited_ids)
        if source_id in by_id
    ]
    return {
        "document_claims_total": total,
        "document_claims_reached": reached,
        "claim_outcomes_proposed": total,
        "material_claims_reviewed": len(material_claims) if material_claims else len(material_checks),
        "supporting_claims_reviewed": len(supporting),
        "confirmed": confirmed_n,
        "contradicted": contradicted_n,
        "not_checkable": not_checkable_n,
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
        "validated_outcomes": reached,
        "receipt_failures": int(review.get("receipt_failures") or 0),
        "evidence_files_supplied": len(sources),
        "evidence_files_cited": cited_safe,
        "provenance_groups": [
            {"source_id": row["id"], "kind": row["kind"], "label": row["label"]}
            for row in sources
        ],
        "source_independence": "grouped_by_declared_provenance" if sources else "not_assessed",
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


def _public_claim(row: dict) -> dict:
    out = {}
    for key in CLAIM_PUBLIC_KEYS:
        if key not in row:
            continue
        value = row[key]
        if key in {"quote", "location"}:
            if value not in (None, "") and not _publishable_text(value):
                raise SystemExit(f"render: claim {key} is not publishable")
            value = str(value).strip() if value not in (None, "") else None
        if value not in (None, "", [], {}):
            out[key] = value
    mode = row.get("verification_mode")
    if not mode:
        if row.get("found_by") == "arithmetic" or row.get("outcome") == "used_for_internal_arithmetic":
            mode = "internal_arithmetic"
        elif row.get("classification") == "supporting_provenance":
            mode = None
        else:
            mode = "not_externally_verified"
        if mode:
            out["verification_mode"] = mode
    return out


def _verification_public(raw: dict, sources: list[dict]) -> dict:
    supplied = raw.get("verification") or {}
    document = supplied.get("document") or {
        "status": "not_available" if raw.get("agentic_only") else "complete",
        "detail": None,
    }
    semantic = supplied.get("semantic") or {
        "status": "not_run",
        "detail": "No semantic review status was recorded.",
    }
    live_sources = [row for row in sources if row.get("kind") == "live_tool"]
    supplied_sources = [row for row in sources if row.get("kind") == "supplied_file"]
    if live_sources:
        live = {
            "status": "complete",
            "detail": (
                f"{len(live_sources)} retained source result"
                f"{'s came' if len(live_sources) != 1 else ' came'} from actual live tool calls."
            ),
        }
    elif supplied_sources:
        live = {
            "status": "not_run",
            "detail": (
                "The retained evidence came from supplied recorded files. "
                "No live tool call is claimed."
            ),
        }
    else:
        live = {
            "status": "not_run",
            "detail": "No retained evidence source was used.",
        }
    return {"document": document, "semantic": semantic, "live_source": live}


def _internally_complete(raw: dict | None, layer2: list[dict]) -> bool:
    """True when extract and material outcomes are complete with no report error."""
    if not isinstance(raw, dict):
        return False
    inv = raw.get("inventory") or {}
    if not inv.get("complete"):
        return False
    if not coverage_ok(raw):
        return False
    if any(check.get("verdict") == "contradicted" for check in layer2):
        return False
    if any(
        check.get("verdict") == "not_checkable"
        and check.get("importance") == "material"
        for check in layer2
    ):
        return False
    return True


def _combined_verdict(base: str, layer2: list[dict],
                      raw: dict | None = None) -> str:
    contradicted = [
        check for check in layer2
        if check.get("verdict") == "contradicted"
        and check.get("importance") != "supporting"
    ]
    for check in contradicted:
        check["severity"] = normalize_severity(
            check.get("severity"), contradicted=True,
            importance=str(check.get("importance") or "material"))
    if any(
        check.get("importance") == "material" for check in contradicted
    ) or any(
        check.get("severity") in {"high", "medium"} for check in contradicted
    ):
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
        any(
            check.get("verdict") == "changed_since_report"
            and check.get("importance") != "supporting"
            for check in layer2
        )
    ) and base in {"safe_to_share", "share_with_caveats"}:
        return "needs_review"
    return base


def _offer(findings: list[dict], layer2: list[dict],
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
                           guidance: dict | None = None) -> dict:
    if not isinstance(raw, dict):
        raise SystemExit("render: input is not JSON object")
    findings_in = raw.get("findings") if isinstance(raw.get("findings"), list) else []
    headline = raw.get("headline") or {}
    cov = coverage(raw)
    findings = []
    diagnostics = []
    material_rows = _material_claims(raw)
    for f in findings_in:
        if _is_diagnostic_record(f):
            statement = str(f.get("statement") or "").strip()
            diagnostic_location = str(
                f.get("coordinate") or f.get("location") or ""
            ).strip()
            if not _publishable_text(statement):
                raise SystemExit("render: diagnostic statement is not publishable")
            if diagnostic_location and not _publishable_text(diagnostic_location):
                raise SystemExit("render: diagnostic location is not publishable")
            diagnostics.append({
                "check_id": str(f.get("check_id") or "diagnostic"),
                "statement": statement,
                "location": (
                    diagnostic_location if diagnostic_location else None
                ),
                "severity": f.get("severity"),
            })
    src_public = source_public(raw)
    retained_sources = _public_sources(raw.get("sources"))
    chosen_ids = {
        str(row.get("check_id") or "") for row in material_rows
        if row.get("check_id")
    }
    selected_layer2 = (
        [
            row for row in (layer2 or [])
            if str(row.get("id") or "") in chosen_ids
        ]
        if material_rows else list(layer2 or [])
    )
    evidence_checks = _public_layer2(
        selected_layer2, sources=retained_sources)
    evidence_findings = [
        check for check in evidence_checks
        if check.get("verdict") == "contradicted"
    ]
    evidence_coverage = _evidence_coverage(raw, evidence_checks, retained_sources)
    score = _public_score(raw, evidence_checks, headline)
    layer2_list = list(selected_layer2)
    verdict = _combined_verdict(verdict_of(raw), layer2_list, raw)
    semantic_status = (((raw.get("verification") or {}).get("semantic") or {})
                       .get("status"))
    if semantic_status in {"failed", "not_run", "skipped"} and verdict in {
        "safe_to_share", "share_with_caveats"
    }:
        if not _internally_complete(raw, layer2_list):
            verdict = "needs_review"
    verdict = public_verdict(verdict)
    art = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "generated_at": generated_at,
        "source": src_public,
        "source_result": None,
        "sources": retained_sources,
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
                "Outcome counts come from coverage. "
                "Individual check rows are not copied."
            ),
        },
        "verification": _verification_public(raw, retained_sources),
        "limitations": limitations_of(raw),
        "offer": {"text": _offer(findings, evidence_checks, verdict, raw),
                  "accepted": None},
        "claims": [_public_claim(row) for row in (raw.get("claims") or [])
                   if isinstance(row, dict)],
    }
    by_check = {str(row.get("id") or ""): row for row in evidence_checks}
    for claim in art["claims"]:
        check = by_check.get(str(claim.get("check_id") or ""))
        if claim.get("classification") == "supporting_provenance":
            claim.pop("verification_mode", None)
            continue
        if check and check.get("basis") == "report":
            claim["verification_mode"] = "internal_arithmetic"
        elif check and check.get("basis") == "evidence":
            claim["verification_mode"] = "external_evidence"
        elif claim.get("found_by") == "arithmetic":
            claim["verification_mode"] = "internal_arithmetic"
        elif claim.get("outcome") in {None, "not_reached", "not_checkable"}:
            claim["verification_mode"] = "not_externally_verified"
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
    provenance = [
        row for row in claims
        if row.get("classification") == "supporting_provenance"
        and row.get("importance") == "supporting"]
    if layer2_named:
        if semantic in UNFINISHED_SEMANTIC:
            return "semantic review did not complete"
        if payload.get("discarded") or payload.get("discarded_sources"):
            return "receipt failures remain"
        if payload.get("discarded_claims"):
            return "claims were discarded"
        if "claims" in payload and not grounded and not provenance:
            return "no grounded material claims"
        checks = payload.get("checks") or payload.get("validated") or []
        if isinstance(receipts, list):
            checks = receipts
        if not checks and not grounded and not provenance:
            return "no grounded material claims"
        if inv.get("complete"):
            unfinished = [
                row for row in material
                if row.get("outcome") not in GROUNDED_OUTCOMES
            ]
            if unfinished:
                return "material claims are not complete"
    if (raw.get("agentic_only") and not raw.get("agentic_scan_completed")
            and not inv.get("complete")):
        if semantic not in {"complete", "partial"}:
            return "host review did not complete"
    return None


def document_errors_unaccounted(raw: dict) -> bool:
    """Require an exact inventory-id link to an agent-authored contradiction."""
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
        finding_ids = {
            str(value or "").strip() for value in finding.get("inventory_ids") or []
            if str(value or "").strip()
        }
        if not finding_ids:
            return True
        accounted = any(
            claim.get("outcome") == "contradicted"
            and claim.get("check_id")
            and finding_ids & {
                str(value or "").strip()
                for value in claim.get("inventory_ids") or []
                if str(value or "").strip()
            }
            for claim in claims
            if isinstance(claim, dict)
        )
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


def curly(text: str) -> str:
    return f"&ldquo;{html.escape(text)}&rdquo;"


def _source_for_check(check: dict, sources: list[dict]) -> dict | None:
    receipt = check.get("public_receipt") or {}
    source_id = str(receipt.get("source_id") or "")
    return next(
        (row for row in sources if str(row.get("id") or "") == source_id), None)


def evidence_heading(check: dict, sources: list[dict] | None = None) -> str:
    if check.get("basis") == "report":
        return "Report calculation"
    source = _source_for_check(check, list(sources or []))
    if source is None:
        raise SystemExit("render: evidence check has no retained source")
    prefix = "Actual live query" if source.get("kind") == "live_tool" else "Supplied recorded evidence"
    return f"{prefix}: {source['label']}"


def _operand_html(operand: dict) -> str:
    return (
        f"<strong>{html.escape(str(operand['label']))}</strong>: "
        f"{html.escape(str(operand['value']))} "
        f'<span class="where">({html.escape(str(operand["location"]))})</span>'
    )


def report_operand_line(check: dict) -> str:
    return _operand_html(check["public_receipt"]["report_operand"])


def evidence_value_line(check: dict) -> str:
    receipt = check.get("public_receipt") or {}
    lines = [_operand_html(row) for row in receipt.get("decisive_operands") or []]
    calculation = receipt.get("calculation")
    if isinstance(calculation, dict):
        lines.append(
            f"<strong>Calculation</strong>: "
            f"{html.escape(str(calculation['expression']))} = "
            f"{html.escape(str(calculation['result']))}"
        )
    return "<br>".join(lines)


def material_card_attributes(check: dict) -> str:
    """Copy the accepted check identity onto a material card without aliases."""
    check_id = str(check.get("id") or "").strip()
    disposition = str(check.get("verdict") or "").strip()
    if (
        not SOURCE_ID.fullmatch(check_id)
        or not _publishable_text(disposition)
    ):
        raise SystemExit("render: material card identity is not publishable")
    return (
        f'data-card-id="{html.escape(check_id, quote=True)}" '
        f'data-disposition="{html.escape(disposition, quote=True)}"'
    )


def receipt_block(report_says: str, evidence_html: str, report_label: str = "Report says",
                  evidence_label: str = "Evidence says") -> str:
    return (
        '<div class="receipt">'
        f'<div class="k">{report_label}</div><div class="q">{report_says}</div>'
        f'<div class="k">{evidence_label}</div><div class="q">{evidence_html}</div>'
        "</div>"
    )
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
    del kind
    receipt = check.get("public_receipt") or {}
    operand = receipt.get("report_operand") or {}
    return html.escape(str(operand.get("label") or ""))


def location_line(check_or_finding: dict) -> str:
    receipt = check_or_finding.get("public_receipt") or {}
    operand = receipt.get("report_operand") or {}
    where = str(operand.get("location") or check_or_finding.get("location") or "").strip()
    if not where:
        return ""
    return f'<div class="where">{html.escape(where)}</div>'


def live_source_ran(art: dict) -> bool:
    return any(
        isinstance(source, dict) and source.get("kind") == "live_tool"
        for source in (art.get("sources") or [])
    )


def html_of(art: dict) -> str:
    findings = []
    checks = list(art.get("evidence_checks") or [])
    sources = list(art.get("sources") or [])
    claims = list(art.get("claims") or [])
    supporting_claims = [
        row for row in claims
        if (row.get("classification") == "supporting_provenance"
            or row.get("importance") == "supporting")
    ]
    counted = [
        row for row in claims
        if row.get("classification") != "supporting_provenance"
        and row.get("importance") != "supporting"
    ]
    if claims:
        n_err = sum(1 for row in counted if claim_bucket(row.get("outcome")) == "errors")
        n_ok = sum(1 for row in counted if claim_bucket(row.get("outcome")) == "confirmed")
        n_csr = sum(1 for row in counted if claim_bucket(row.get("outcome")) == "today-differs")
        n_nc = sum(
            1 for row in counted
            if claim_bucket(row.get("outcome")) == "not-checkable"
        )
        ledger = len(counted)
        chosen_check_ids = {
            str(row.get("check_id") or "") for row in counted if row.get("check_id")}
        contradicted = [
            c for c in checks
            if c.get("verdict") == "contradicted" and c.get("id") in chosen_check_ids]
        confirmed = [
            c for c in checks
            if c.get("verdict") == "confirmed" and c.get("id") in chosen_check_ids]
        confirmed.sort(key=lambda row: 0 if row.get("basis") == "evidence" else 1)
        csr = [
            c for c in checks
            if c.get("verdict") == "changed_since_report" and c.get("id") in chosen_check_ids]
        not_checkable = [
            c for c in checks
            if c.get("verdict") == "not_checkable" and c.get("id") in chosen_check_ids]
        unreached = [
            row for row in counted
            if row.get("outcome") in (None, "not_reached", "used_for_internal_arithmetic")]
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
    page_v = customer_verdict(str(art.get("verdict") or "unable_to_grade"))

    src = art.get("source") or {}
    filename = src.get("path") or "report"
    period = src.get("period_label") or ""
    iso_date = src.get("report_date") or ""
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
        noun = "material claim" if ledger == 1 else "material claims"
        if n_nc or unreached:
            h1 = (
                f"No errors found. {spell_count(n_ok).capitalize()} "
                f"{'material claim was' if n_ok == 1 else 'material claims were'} checked."
            )
        elif ledger == 1:
            h1 = "No errors found. The one material claim was checked."
        else:
            h1 = f"No errors found. All {spell_count(ledger)} {noun} were checked."
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
                "No errors found. A later value differs for "
                f"{spell_count(n_csr)} {'claim' if n_csr == 1 else 'claims'}."
            )
        else:
            h1 = "No errors found. Part of the assessment did not complete."
        next_text = ""

    claim_word = "material claim" if ledger == 1 else "material claims"
    clauses = [f"The report makes {spell_count(ledger)} {claim_word}."]
    if supporting_claims:
        n_sup = len(supporting_claims)
        clauses.append(
            f"{spell_count(n_sup).capitalize()} supporting source "
            f"{'line is' if n_sup == 1 else 'lines are'} provenance, not a material claim."
        )
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
            f"For {spell_count(n_csr)}, a later value differs and the "
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
    nc_sub = (
        "no accepted outcome for these"
        if n_nc else "all material outcomes accounted for"
    )

    stats = (
        '<div class="stats" role="group" aria-label="Verification results" '
        f'data-ledger="{ledger}">'
        + stat_tile(n_err, True, "red" if n_err else "gray", "Errors found", err_sub, "errors")
        + stat_tile(n_ok, True, "green" if n_ok else "gray", "Confirmed", ok_sub, "confirmed")
        + stat_tile(
            n_csr, csr_ran,
            "amber" if n_csr else "gray",
            "Later value differs", csr_sub, "today-differs")
        + stat_tile(
            n_nc, True,
            "amber" if n_nc else "gray",
            "Not checkable", nc_sub, "not-checkable")
        + "</div>"
    )

    sections = []

    error_cards = []
    for check in contradicted:
        expl = public_explanation(check)
        receipt = receipt_block(
            report_operand_line(check),
            evidence_value_line(check),
            report_label="Report operand",
            evidence_label=evidence_heading(check, sources),
        )
        error_cards.append(
            '<div class="card err" data-kind="error" '
            f'{material_card_attributes(check)}>'
            '<span class="tag">ERROR</span>'
            f"<h3>{card_title(check, 'error')}</h3>"
            f"{location_line(check)}"
            + receipt
            + (f"<p>{html.escape(expl)}</p>" if expl else "")
            + '<div class="machine">Checked by a program: exact receipt values were grounded; the host agent supplied the labels, explanation, and verdict.</div>'
            + "</div>"
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
        title = card_title(check, "confirmed")
        machine = (
            "Checked by a program: exact receipt values were grounded; "
            "the host agent supplied the labels, explanation, and verdict."
        )
        expl = public_explanation(check)
        receipt_html = evidence_value_line(check)
        show_why = expl and expl not in html.unescape(
            re.sub(r"<[^>]+>", " ", receipt_html))
        confirm_cards.append(
            '<div class="card ok" data-kind="confirmed" '
            f'{material_card_attributes(check)}>'
            '<span class="tag">CONFIRMED</span>'
            f"<h3>{title}</h3>"
            f"{location_line(check)}"
            + receipt_block(
                report_operand_line(check),
                receipt_html,
                report_label="Report operand",
                evidence_label=evidence_heading(check, sources),
            )
            + (f"<p>{html.escape(expl)}</p>" if show_why else "")
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
            source_record = _source_for_check(check, sources)
            if source_record is None:
                raise SystemExit("render: temporal check has no retained source")
            live_ran = source_record.get("kind") == "live_tool"
            report_raw = check["public_receipt"]["report_operand"]["value"]
            report_val = str(report_raw)
            current_raw = check.get("current_value")
            current_val = str(current_raw)
            as_of = pretty_date(check.get("current_as_of"))
            source_label = str(source_record["label"])
            if live_ran:
                current_label = (
                    f"Actual live query: {html.escape(source_label)}, {html.escape(as_of)}"
                )
            else:
                current_label = (
                    f"Supplied recorded evidence: {html.escape(str(source_label))}, "
                    f"{html.escape(as_of)}"
                )
            check_report_date = pretty_date(check.get("report_date"))
            report_label = f"Report, {html.escape(check_report_date)}"
            recon = str(check.get("reconstruction_attempt") or "")
            csr_cards.append(
                '<div class="card chg" data-kind="today-differs" '
                f'{material_card_attributes(check)}>'
                '<span class="tag">LATER VALUE DIFFERS</span>'
                f"<h3>{card_title(check, 'csr')}</h3>"
                f"{location_line(check)}"
                '<div class="compare">'
                f'<div class="box"><div class="bl">{report_label}</div>'
                f'<div class="bv">{html.escape(report_val)}</div></div>'
                + f'<div class="box"><div class="bl">{current_label}</div>'
                f'<div class="bv">{html.escape(current_val)}</div></div>'
                + "</div>"
                + receipt_block(
                    report_operand_line(check),
                    evidence_value_line(check),
                    report_label="Report operand",
                    evidence_label=evidence_heading(check, sources),
                )
                + f"<p>{html.escape(public_explanation(check))}</p>"
                + (f"<p>{html.escape(recon)}</p>" if recon else "")
                + (
                    '<div class="machine">Checked by a program: the report value was compared with an actual live-query result.</div>'
                    if live_ran else
                    '<div class="machine">Checked by a program: the report value was compared with supplied recorded evidence; no live query ran.</div>'
                )
                + "</div>"
            )
        sections.append(
            '<section data-section="today-differs">'
            "<h2>A later value differs</h2>"
            + "".join(csr_cards)
            + "</section>"
        )

    nc_items = []
    for check in not_checkable:
        why = public_explanation(check)
        where = str(check.get("location") or "").strip()
        where_html = (
            f' <span class="where">({html.escape(where)})</span>'
            if where else ""
        )
        nc_items.append(
            "<li><span class=\"w\"><strong>"
            f"{curly(check.get('report_quote') or 'Claim')}</strong>{where_html} "
            f"{html.escape(why)}</span></li>"
        )
    for row in unreached:
        where = str(row.get("location") or "").strip()
        where_html = (
            f' <span class="where">({html.escape(where)})</span>'
            if where else ""
        )
        nc_items.append(
            "<li><span class=\"w\"><strong>"
            f"{curly(row.get('quote') or 'Claim')}</strong>{where_html} "
            + (
                "Used as an internal arithmetic operand; no semantic verdict was authored."
                if row.get("outcome") == "used_for_internal_arithmetic"
                else "Not externally verified."
            )
            + "</span></li>"
        )
    if n_nc and not nc_items:
        nc_items.append(
            "<li><span class=\"w\"><strong>"
            f"{spell_count(n_nc).capitalize()} "
            f"{'claim' if n_nc == 1 else 'claims'} had no accepted check."
            "</strong></span></li>"
        )
    if not n_nc:
        nc_list = '<ul class="plain"><li><span class="w"><strong>Every material claim had an accepted outcome.</strong></span></li></ul>'
        lede = ""
        nc_items = []
    else:
        shown = nc_items[:n_nc] if nc_items else nc_items
        lede = (
            f'<p class="sectionlede">Read '
            f"{'this' if n_nc == 1 else 'these ' + spell_count(n_nc)} as unverified.</p>"
        )
        nc_list = f'<ul class="plain">{"".join(shown)}</ul>'
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
        arith_text = "Deterministic extraction and arithmetic candidate generation ran on the report."
    elif arith_status in {"not_available", "not_run", "skipped"}:
        arith_text = "Did not run."
    else:
        arith_text = html.escape(str(doc.get("detail") or arith_status))
    live_sources = [row for row in sources if row.get("kind") == "live_tool"]
    supplied_sources = [row for row in sources if row.get("kind") == "supplied_file"]
    if live_source_ran(art):
        live_text = (
            f"{spell_count(len(live_sources)).capitalize()} retained source result"
            f"{'s came' if len(live_sources) != 1 else ' came'} from an actual live tool call."
        )
    elif supplied_sources:
        live_text = "Supplied recorded evidence was used; no live query ran."
    else:
        live_text = "Did not run."
    cov = art.get("evidence_coverage") or {}
    supplied_n = int(cov.get("evidence_files_supplied") or 0)
    cited = [str(name) for name in (cov.get("evidence_files_cited") or [])]
    has_evidence = any(
        c.get("basis") == "evidence"
        and c.get("verdict") in {"confirmed", "contradicted", "changed_since_report"}
        for c in checks
    )
    has_report = any(
        c.get("basis") == "report"
        and c.get("verdict") in {"confirmed", "contradicted"}
        for c in checks
    )
    if supplied_n or cited or has_evidence:
        names = ", ".join(f"<code>{html.escape(name)}</code>" for name in cited[:4])
        ev_text = (
            f"Checked against {spell_count(supplied_n or len(cited))} retained source "
            f"{'result' if (supplied_n or len(cited)) == 1 else 'results'}"
            + (f" ({names})" if names else "")
            + "."
        )
        if has_report:
            ev_text = "Computed from the report. " + ev_text
    elif has_report:
        ev_text = "Computed from the report."
    else:
        ev_text = "No evidence files were supplied."
    checked_n = n_err + n_ok + n_csr
    claims_text = (
        f"Every headline figure, table total, and named metric counts as a material claim; "
        f"{spell_count(ledger)} found. {spell_count(checked_n).capitalize()} "
        f"{'was' if checked_n == 1 else 'were'} checked"
        + (f"; {spell_count(n_nc)} could not be checked" if n_nc else "")
        + "."
    )
    if supporting_claims:
        n_sup = len(supporting_claims)
        claims_text += (
            f" {spell_count(n_sup).capitalize()} supporting source "
            f"{'line is' if n_sup == 1 else 'lines are'} provenance."
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
            f"{report_operand_line(check)} "
            f"{evidence_value_line(check)} "
            f"{html.escape(public_explanation(check))}"
        )
        tech_bits.append(f"<li>{line}</li>")
    tech_list = (
        "<p>The other confirmed claims:</p><ul>" + "".join(tech_bits) + "</ul>"
        if hidden_confirmed else ""
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
    review["receipt_failures"] = (
        len(receipts.get("discarded") or [])
        + len(receipts.get("discarded_sources") or [])
    )
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
    raw["sources"] = list(receipts.get("sources") or [])


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--findings", required=True, type=Path)
    p.add_argument("--out-dir", required=True, type=Path)
    p.add_argument("--run-id", default=None)
    p.add_argument("--layer2", type=Path, default=None,
                   help="validated Layer 2 findings JSON (list or {findings:[...]}); HTML only")
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
    digest = str((raw.get("source") or {}).get("sha256") or "")
    if len(digest) < 6:
        digest = hashlib.sha256(args.findings.read_bytes()).hexdigest()
    run_id = args.run_id or f"sf-{digest[:6]}"
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    art = artifact_from_findings(raw, run_id=run_id, generated_at=generated_at,
                                 layer2=layer2, guidance=guidance)
    if art.get("verdict") == "unable_to_grade":
        print(
            "render: report could not be graded. No shareable artifact written.",
            file=sys.stderr,
        )
        return 2
    page = html_of(art)
    from artifact_audit import audit_public_artifact  # noqa: E402
    problems = audit_public_artifact(art, page)
    if problems:
        print("render: public artifact failed invariant audit:", file=sys.stderr)
        for item in problems[:12]:
            print(f"  - {item}", file=sys.stderr)
        return 2
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "grade-artifact.json").write_text(json.dumps(art, indent=2) + "\n")
    (args.out_dir / "grade-artifact.html").write_text(page)
    print(args.out_dir / "grade-artifact.json")
    print(args.out_dir / "grade-artifact.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
