#!/usr/bin/env python3
"""Serialize accepted public receipts into grade-artifact/public-receipt-v1."""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
import receipt_math  # noqa: E402


SCHEMA_VERSION = "grade-artifact/public-receipt-v1"
DISPOSITIONS = frozenset({
    "confirmed", "contradicted", "not_checkable", "changed_since_report",
})
ROOT_VERDICTS = frozenset({
    "safe_to_share", "share_with_caveats", "fix_first", "unable_to_grade",
})
SOURCE_KINDS = frozenset({"supplied_file", "live_tool"})
ACTION_KINDS = frozenset({
    "correct_report", "reconcile_before_change", "review_before_share",
})
ROOT_STATIC_HEADLINES = {
    "safe_to_share": "Safe to share",
    "share_with_caveats": "Share with caveats",
    "unable_to_grade": "Unable to grade",
}
ROOT_CHIP_LABELS = {
    "safe_to_share": "SAFE TO SHARE",
    "share_with_caveats": "SHARE WITH CAVEATS",
    "fix_first": "FIX FIRST",
    "unable_to_grade": "UNABLE TO GRADE",
}
DISPOSITION_LABELS = {
    "confirmed": "Confirmed",
    "contradicted": "Contradicted",
    "not_checkable": "Not checkable",
    "changed_since_report": "Changed since the report",
}
SOURCE_KIND_LABELS = {
    "supplied_file": "Supplied file",
    "live_tool": "Live source",
}
ROOT_TONES = {
    "safe_to_share": "safe",
    "share_with_caveats": "warn",
    "fix_first": "fix",
    "unable_to_grade": "neutral",
}
REQUIRED = (
    "schema_version", "run_id", "generated_at", "source", "source_result",
    "verdict", "score", "findings", "evidence_checks", "evidence_findings",
    "evidence_coverage", "decision", "actions", "decision_limits",
    "diagnostics", "checks", "verification", "limitations", "offer",
    "claims", "sources",
)
CHECK_PUBLIC_KEYS = (
    "id", "type", "basis", "verdict", "importance", "severity",
    "claim_id", "public_receipt",
)
CLAIM_PUBLIC_KEYS = (
    "id", "quote", "public_label", "importance", "classification", "reason",
    "outcome", "check_id", "inventory_ids",
)
PRIVATE_NAMES = frozenset({
    "findings.json", "receipts.json", "checks.json", "claims.json",
    "grade-artifact.json", "report-visible.txt", "ledger.json",
    "source-findings.json", "provenance.json",
})
_ABS_PATH = re.compile(
    r"(?:/Users/|/home/|/var/folders/|/private/tmp/|/tmp/|[A-Z]:\\)[^\s\"'<]+",
    re.I,
)
_JSON_POINTER = re.compile(r"(?<![A-Za-z0-9:])(?:/[A-Za-z0-9_~.-]+)+")
_RAW_OFFICE_TOKEN = re.compile(r"\b(?:slide|shape)\d+\b", re.I)
_TENANT_IDENTIFIER = re.compile(
    r"\b(?:tenant|organization|org)[ _-]?id\b\s*[:=]\s*[\"']?[A-Za-z0-9_-]+",
    re.I,
)
_CREDENTIAL = re.compile(
    r"\b(?:api[ _-]?key|access[ _-]?token|refresh[ _-]?token|client[ _-]?secret|"
    r"password|credential)\b\s*[:=]\s*[^\s,;}]+",
    re.I,
)
_BEARER = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", re.I)
_VAGUE = re.compile(r"^(?:row|operand|item|value)(?:\s+\d+)?$", re.I)
_SOURCE_ID = re.compile(r"^[A-Za-z][A-Za-z0-9._-]*$")
_ISO_TIME = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)
_VERIFICATION_STATUSES = frozenset({
    "complete", "partial", "failed", "not_available", "not_requested",
    "not_run", "skipped",
})


def _fixed_label(mapping: dict[str, str], value: str, kind: str) -> str:
    try:
        return mapping[value]
    except KeyError as exc:
        raise SystemExit(f"render: unsupported {kind} {value!r}") from exc


def _root_headline(verdict: str, counts: dict) -> str:
    """Map the exact verdict plus mechanical contradiction count to the heading."""
    if verdict != "fix_first":
        return _fixed_label(ROOT_STATIC_HEADLINES, verdict, "root verdict")
    if not isinstance(counts, dict):
        raise SystemExit("render: evidence coverage is missing for root headline")
    errors = counts.get("contradicted")
    if isinstance(errors, bool) or not isinstance(errors, int) or errors < 1:
        raise SystemExit("render: fix_first headline requires contradicted count")
    noun = "error" if errors == 1 else "errors"
    return f"Fix {errors} {noun} before you share this report."


def _valid_iso_time(value) -> bool:
    text = str(value or "").strip()
    if not _ISO_TIME.fullmatch(text):
        return False
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def coverage(raw: dict) -> dict:
    value = raw.get("coverage") if isinstance(raw, dict) else None
    return value if isinstance(value, dict) else {}


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
        if isinstance(row, dict)
        and (
            row.get("classification") == "supporting_provenance"
            or row.get("importance") == "supporting"
        )
    ]


def _publishable_text(value, *, label: bool = False) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    if (
        _ABS_PATH.search(text)
        or _JSON_POINTER.search(text)
        or _RAW_OFFICE_TOKEN.search(text)
        or _TENANT_IDENTIFIER.search(text)
        or _CREDENTIAL.search(text)
        or _BEARER.search(text)
        or any(name.lower() in text.lower() for name in PRIVATE_NAMES)
    ):
        return False
    if label and _VAGUE.fullmatch(text):
        return False
    return True


def _substantive(value) -> bool:
    text = str(value or "").strip()
    return (
        _publishable_text(text)
        and bool(re.search(r"[.!?]$", text))
        and len(re.findall(r"[A-Za-z0-9%$]+", text)) >= 6
    )


def _operand_publishable(row) -> bool:
    if not isinstance(row, dict) or set(row) != {"label", "value", "location"}:
        return False
    value = row.get("value")
    return (
        _publishable_text(row.get("label"), label=True)
        and value not in (None, "")
        and not isinstance(value, (bool, dict, list))
        and (not isinstance(value, str) or _publishable_text(value))
        and _publishable_text(row.get("location"))
    )


def _publishable_receipt(receipt, *, verdict: str | None = None,
                         basis: str | None = None,
                         source_ids: set[str] | None = None) -> bool:
    if not isinstance(receipt, dict):
        return False
    allowed = {
        "report_operand", "decisive_operands", "explanation", "calculation",
        "source_id", "reconstruction_attempt",
    }
    if set(receipt) - allowed:
        return False
    if not _operand_publishable(receipt.get("report_operand")):
        return False
    decisive = receipt.get("decisive_operands")
    if not isinstance(decisive, list):
        return False
    if verdict == "not_checkable":
        if decisive or "calculation" in receipt:
            return False
    elif verdict in DISPOSITIONS:
        if not decisive:
            return False
    if any(not _operand_publishable(row) for row in decisive):
        return False
    if not _substantive(receipt.get("explanation")):
        return False
    calculation = receipt.get("calculation")
    if calculation is not None:
        if not isinstance(calculation, dict) or set(calculation) != {"expression", "result"}:
            return False
        if not _publishable_text(calculation.get("expression")):
            return False
        result = calculation.get("result")
        if result in (None, "") or isinstance(result, (bool, dict, list)):
            return False
        if isinstance(result, str) and not _publishable_text(result):
            return False
    reconstruction = receipt.get("reconstruction_attempt")
    if reconstruction is not None:
        if verdict != "changed_since_report" or not _substantive(reconstruction):
            return False
    elif verdict == "changed_since_report":
        return False
    source_id = str(receipt.get("source_id") or "")
    if basis == "evidence":
        if not source_id or source_id not in (source_ids or set()):
            return False
    elif basis == "report" and source_id:
        return False
    return True


def _safe_metadata(value) -> bool:
    if isinstance(value, dict):
        return all(
            bool(str(key).strip())
            and not re.search(
                r"password|secret|credential|api[_-]?key|access[_-]?token|refresh[_-]?token",
                str(key), re.I,
            )
            and _safe_metadata(child)
            for key, child in value.items()
        )
    if isinstance(value, list):
        return all(_safe_metadata(child) for child in value)
    if value is None or isinstance(value, (bool, int, float)):
        return True
    return _publishable_text(value)


def _public_sources(rows) -> list[dict]:
    if not isinstance(rows, list):
        raise SystemExit("render: sources are not a list")
    out: list[dict] = []
    seen: set[str] = set()
    for raw in rows:
        if not isinstance(raw, dict):
            raise SystemExit("render: retained source is not an object")
        allowed = {"id", "kind", "label", "evidence_file", "result_sha256", "retrieval"}
        if set(raw) - allowed:
            raise SystemExit("render: retained source has unknown fields")
        source_id = str(raw.get("id") or "")
        kind = str(raw.get("kind") or "")
        label = str(raw.get("label") or "")
        filename = str(raw.get("evidence_file") or "")
        digest = str(raw.get("result_sha256") or "")
        if not _SOURCE_ID.fullmatch(source_id) or source_id in seen:
            raise SystemExit("render: retained source id is invalid or duplicated")
        if kind not in SOURCE_KINDS:
            raise SystemExit("render: retained source kind is invalid")
        if not _publishable_text(label, label=True):
            raise SystemExit("render: retained source label is not publishable")
        if not filename or Path(filename).name != filename or filename in PRIVATE_NAMES:
            raise SystemExit("render: retained evidence filename is not publishable")
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise SystemExit("render: retained source digest is invalid")
        retrieval = raw.get("retrieval")
        if kind == "supplied_file" and "retrieval" in raw:
            raise SystemExit("render: supplied_file cannot have live retrieval metadata")
        canonical = {
            "id": source_id, "kind": kind, "label": label,
            "evidence_file": filename, "result_sha256": digest,
        }
        if kind == "live_tool":
            if not isinstance(retrieval, dict) or set(retrieval) != {
                "retrieved_at", "tool", "arguments",
            }:
                raise SystemExit("render: live_tool retrieval metadata is incomplete")
            if not _valid_iso_time(retrieval.get("retrieved_at")):
                raise SystemExit("render: live_tool retrieval time is invalid")
            if not _publishable_text(retrieval.get("tool")):
                raise SystemExit("render: live_tool name is not publishable")
            if not isinstance(retrieval.get("arguments"), dict) or not _safe_metadata(
                retrieval["arguments"]
            ):
                raise SystemExit("render: live_tool arguments are not publishable")
            canonical["retrieval"] = {
                "retrieved_at": str(retrieval["retrieved_at"]),
                "tool": str(retrieval["tool"]),
                "arguments": retrieval["arguments"],
            }
        seen.add(source_id)
        out.append(canonical)
    return out


def _public_layer2(rows, *, sources: list[dict] | None = None) -> list[dict]:
    if not isinstance(rows, list):
        raise SystemExit("render: accepted checks are not a list")
    source_ids = {str(row.get("id") or "") for row in (sources or [])}
    out: list[dict] = []
    seen: set[str] = set()
    for raw in rows:
        if not isinstance(raw, dict):
            raise SystemExit("render: accepted check is not an object")
        check_id = str(raw.get("id") or "")
        verdict = str(raw.get("verdict") or "")
        basis = str(raw.get("basis") or "")
        if not _SOURCE_ID.fullmatch(check_id) or check_id in seen:
            raise SystemExit("render: accepted check id is invalid or duplicated")
        if verdict not in DISPOSITIONS:
            raise SystemExit(f"render: unsupported disposition {verdict!r}")
        if basis not in {"report", "evidence"}:
            raise SystemExit("render: accepted check basis is invalid")
        severity = raw.get("severity")
        if severity not in {None, "high", "medium", "low"}:
            raise SystemExit("render: accepted check severity is invalid")
        receipt = raw.get("public_receipt")
        if not _publishable_receipt(
            receipt, verdict=verdict, basis=basis, source_ids=source_ids
        ):
            raise SystemExit(f"render: check {check_id} public_receipt is not publishable")
        row = {key: raw.get(key) for key in CHECK_PUBLIC_KEYS}
        row["id"] = check_id
        row["verdict"] = verdict
        row["basis"] = basis
        row["severity"] = severity
        row["public_receipt"] = json.loads(json.dumps(receipt))
        seen.add(check_id)
        out.append(row)
    return out


def _serialize_claim(row: dict) -> dict:
    out = {key: row.get(key) for key in CLAIM_PUBLIC_KEYS if key in row}
    required = {"id", "quote", "public_label", "importance", "classification"}
    if not required <= set(out):
        raise SystemExit("render: claim is missing public contract fields")
    if not _publishable_text(out["quote"]) or not _publishable_text(
        out["public_label"], label=True
    ):
        raise SystemExit("render: claim text is not publishable")
    if out.get("reason") not in (None, "") and not _publishable_text(out["reason"]):
        raise SystemExit("render: claim reason is not publishable")
    supporting = (
        out.get("classification") == "supporting_provenance"
        or out.get("importance") == "supporting"
    )
    if supporting and out.get("outcome") == "not_reached":
        out["outcome"] = None
        out["check_id"] = None
    if not supporting and out.get("outcome") not in DISPOSITIONS:
        raise SystemExit("render: material claim has no accepted disposition")
    return out


def _public_actions(guidance: dict | None, *, check_ids: set[str]) -> list[dict]:
    """Copy accepted host actions without authoring or rewriting their meaning."""
    if not isinstance(guidance, dict):
        raise SystemExit("render: accepted presentation is required")
    proposed = guidance.get("actions")
    if not isinstance(proposed, list) or not proposed:
        raise SystemExit("render: accepted presentation needs at least one action")
    out = []
    seen: set[str] = set()
    for raw in proposed:
        if not isinstance(raw, dict):
            raise SystemExit("render: accepted presentation action is not an object")
        action_id = str(raw.get("id") or "")
        kind = str(raw.get("kind") or "")
        text = str(raw.get("text") or "")
        report_quote = str(raw.get("report_quote") or "")
        cited = raw.get("check_ids")
        if not re.fullmatch(r"A[0-9]+", action_id) or action_id in seen:
            raise SystemExit("render: accepted presentation action id is invalid or duplicated")
        if kind not in ACTION_KINDS:
            raise SystemExit("render: accepted presentation action kind is invalid")
        if not _substantive(text) or not _publishable_text(report_quote):
            raise SystemExit("render: accepted presentation action text is not publishable")
        if (
            not isinstance(cited, list)
            or not cited
            or any(str(value) not in check_ids for value in cited)
        ):
            raise SystemExit("render: accepted presentation action check ids are invalid")
        out.append({"id": action_id, "text": text, "report_quote": report_quote})
        seen.add(action_id)
    return out


def _public_presentation(guidance: dict | None, *, checks: dict[str, dict]
                         ) -> tuple[dict, list[dict]]:
    """Copy the host summary and its exact accepted-check grounding."""
    if not isinstance(guidance, dict):
        raise SystemExit("render: accepted presentation is required")
    summary = str(guidance.get("summary") or "").strip()
    if not _substantive(summary):
        raise SystemExit("render: accepted presentation summary is not publishable")
    raw_ids = guidance.get("check_ids")
    if not isinstance(raw_ids, list) or not raw_ids:
        raise SystemExit("render: accepted presentation summary has no check ids")
    selected = [str(value or "").strip() for value in raw_ids]
    if (
        any(not value or value not in checks for value in selected)
        or len(selected) != len(set(selected))
    ):
        raise SystemExit("render: accepted presentation check ids are invalid")
    confirmed = {
        check_id for check_id, row in checks.items()
        if row.get("verdict") == "confirmed"
    }
    if confirmed and not (confirmed & set(selected)):
        raise SystemExit(
            "render: accepted presentation has no visible confirmed check ids")
    actions = _public_actions(guidance, check_ids=set(checks))
    limits = guidance.get("limits")
    if not isinstance(limits, list):
        raise SystemExit("render: accepted presentation limits are not a list")
    return {
        "summary": summary,
        "check_ids": selected,
        "actions": [],
        "limits": [],
    }, actions


def source_public(raw: dict) -> dict:
    source = raw.get("source") if isinstance(raw, dict) else None
    if not isinstance(source, dict):
        raise SystemExit("render: source metadata is missing")
    path = str(source.get("path") or "").strip()
    if (
        not path
        or Path(path).is_absolute()
        or Path(path).name != path
        or not _publishable_text(path)
    ):
        raise SystemExit("render: source filename is not publishable")
    source_format = str(source.get("format") or "").strip()
    digest = str(source.get("sha256") or "").strip().lower()
    if not source_format or not _publishable_text(source_format):
        raise SystemExit("render: source format is missing or not publishable")
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise SystemExit("render: source sha256 is missing or invalid")
    out = {
        "path": path,
        "format": source_format,
        "sha256": digest,
        "period_label": source.get("period_label"),
        "report_date": source.get("report_date"),
    }
    for key in ("format", "period_label", "report_date"):
        if out[key] not in (None, "") and not _publishable_text(out[key]):
            raise SystemExit(f"render: source {key} is not publishable")
    return out


def _public_score(raw: dict, checks: list[dict], headline: dict | None = None) -> dict | None:
    del headline
    material = _material_claims(raw)
    if not material:
        return None
    errors = sum(row.get("outcome") == "contradicted" for row in material)
    return {
        "kind": "tier_d_per_100_claims",
        "value": 100.0 * errors / len(material),
    }


def _evidence_coverage(raw: dict, checks: list[dict], sources: list[dict]) -> dict:
    material_claims = _material_claims(raw)
    supporting = _supporting_claims(raw)
    material_checks = [row for row in checks if row.get("importance") == "material"]
    by_id = {str(row["id"]): row for row in sources}
    cited_ids = {
        str((row.get("public_receipt") or {}).get("source_id") or "")
        for row in material_checks if row.get("basis") == "evidence"
    } - {""}

    def count(verdict: str, basis: str | None = None) -> int:
        return sum(
            row.get("verdict") == verdict
            and (basis is None or row.get("basis") == basis)
            for row in material_checks
        )

    return {
        "document_claims_total": len(material_claims),
        "document_claims_reached": len(material_checks),
        "claim_outcomes_proposed": len(material_claims),
        "material_claims_reviewed": len(material_claims),
        "supporting_claims_reviewed": len(supporting),
        "confirmed": count("confirmed"),
        "contradicted": count("contradicted"),
        "not_checkable": count("not_checkable"),
        "changed_since_report": count("changed_since_report"),
        "evidence_confirmed": count("confirmed", "evidence"),
        "evidence_contradicted": count("contradicted", "evidence"),
        "evidence_not_checkable": count("not_checkable", "evidence"),
        "evidence_changed_since_report": count("changed_since_report", "evidence"),
        "report_confirmed": count("confirmed", "report"),
        "report_contradicted": count("contradicted", "report"),
        "report_not_checkable": count("not_checkable", "report"),
        "report_changed_since_report": count("changed_since_report", "report"),
        "validated_outcomes": len(material_checks),
        "receipt_failures": 0,
        "evidence_files_supplied": len(sources),
        "evidence_files_cited": [
            by_id[source_id]["label"] for source_id in sorted(cited_ids)
            if source_id in by_id
        ],
        "provenance_groups": [
            {"source_id": row["id"], "kind": row["kind"], "label": row["label"]}
            for row in sources
        ],
        "source_independence": (
            "grouped_by_declared_provenance" if sources else "not_assessed"
        ),
    }


def ledger_verdict(raw: dict) -> str:
    material = _material_claims(raw)
    outcomes = [row.get("outcome") for row in material]
    if not outcomes or any(value not in DISPOSITIONS for value in outcomes):
        return "unable_to_grade"
    if "contradicted" in outcomes:
        return "fix_first"
    if any(value in {"not_checkable", "changed_since_report"} for value in outcomes):
        return "share_with_caveats"
    return "safe_to_share"


def _serialize_verification(raw: dict, *, sources: list[dict]) -> dict:
    supplied = raw.get("verification")
    if not isinstance(supplied, dict) or set(supplied) != {
        "document", "semantic", "live_source",
    }:
        raise SystemExit("render: verification metadata is incomplete")
    out = {}
    for name in ("document", "semantic", "live_source"):
        row = supplied.get(name)
        if not isinstance(row, dict) or set(row) != {"status", "detail"}:
            raise SystemExit(f"render: verification.{name} is incomplete")
        if row.get("status") not in _VERIFICATION_STATUSES:
            raise SystemExit(f"render: verification.{name}.status is invalid")
        detail = row.get("detail")
        if detail is not None:
            raise SystemExit(
                f"render: verification.{name}.detail cannot enter public output")
        if name != "live_source":
            out[name] = {"status": row["status"], "detail": None}
    out["live_source"] = {
        "status": (
            "complete" if any(row["kind"] == "live_tool" for row in sources)
            else "not_run"
        ),
        "detail": None,
    }
    return out


def artifact_from_findings(raw: dict, *, run_id: str, generated_at: str,
                           layer2: list[dict] | None = None,
                           guidance: dict | None = None) -> dict:
    if not isinstance(raw, dict):
        raise SystemExit("render: input is not a JSON object")
    retained_sources = _public_sources(raw.get("sources") or [])
    public_checks = _public_layer2(layer2 or [], sources=retained_sources)
    material_claims = _material_claims(raw)
    chosen = {str(row.get("check_id") or "") for row in material_claims}
    material_public_checks = [
        row for row in public_checks if row.get("importance") == "material"]
    by_id = {row["id"]: row for row in material_public_checks}
    presentation, actions = _public_presentation(guidance, checks=by_id)
    if chosen != set(by_id):
        raise SystemExit("render: material claim and accepted check ids do not reconcile")
    for claim in material_claims:
        check = by_id.get(str(claim.get("check_id") or ""))
        if (
            check is None
            or check.get("claim_id") != claim.get("id")
            or check.get("verdict") != claim.get("outcome")
            or check.get("importance") != "material"
        ):
            raise SystemExit("render: material claim ledger does not match accepted checks")
        receipt_label = ((check.get("public_receipt") or {}).get("report_operand") or {}).get("label")
        if receipt_label != claim.get("public_label"):
            raise SystemExit("render: claim public_label does not match its receipt")
    verdict = ledger_verdict(raw)
    if verdict not in ROOT_VERDICTS:
        raise SystemExit("render: material ledger produced an invalid verdict")
    cov = coverage(raw)
    verification = _serialize_verification(raw, sources=retained_sources)
    artifact = {
        "schema_version": SCHEMA_VERSION,
        "run_id": str(run_id),
        "generated_at": str(generated_at),
        "source": source_public(raw),
        "source_result": None,
        "verdict": verdict,
        "score": _public_score(raw, public_checks),
        "findings": [],
        "evidence_checks": public_checks,
        "evidence_findings": [
            row for row in material_public_checks
            if row.get("verdict") == "contradicted"
        ],
        "evidence_coverage": _evidence_coverage(raw, public_checks, retained_sources),
        "decision": None,
        "actions": actions,
        "decision_limits": [],
        "diagnostics": [],
        "checks": {
            "registered": int(cov.get("checks_registered") or 0),
            "with_findings": int(cov.get("checks_with_findings") or 0),
            "found_nothing": int(cov.get("checks_found_nothing") or 0),
            "errored": int(cov.get("checks_errored") or 0),
            "skipped_note": "",
        },
        "verification": verification,
        "limitations": [],
        "offer": {"text": "", "accepted": None},
        "claims": [
            _serialize_claim(row) for row in (raw.get("claims") or [])
            if row.get("classification") != "structural_context"
        ],
        "sources": retained_sources,
        "presentation": presentation,
    }
    validate_artifact(artifact)
    return artifact


def validate_artifact(artifact: dict) -> None:
    missing = [key for key in REQUIRED if key not in artifact]
    if missing:
        raise SystemExit(f"render: artifact missing {missing}")
    if artifact.get("schema_version") != SCHEMA_VERSION:
        raise SystemExit("render: bad schema_version")
    if artifact.get("verdict") not in ROOT_VERDICTS:
        raise SystemExit("render: bad verdict")
    schema_path = Path(__file__).resolve().parent.parent / "schema.v1.json"
    if not schema_path.is_file():
        raise SystemExit(f"render: missing schema {schema_path}")
    try:
        import jsonschema
    except ImportError:
        return
    jsonschema.validate(artifact, json.loads(schema_path.read_text()))


_DAY_MONTH = re.compile(
    r"\b([0-3]?\d)\s+"
    r"(January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+(\d{4})\b",
    re.I,
)
_ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})(?!T)\b")


def _customer_english(text: str) -> str:
    """Rewrite day-month English and ISO calendar dates to month-day order."""

    def day_month(match: re.Match[str]) -> str:
        day = int(match.group(1))
        if day < 1 or day > 31:
            return match.group(0)
        return f"{match.group(2).title()} {day}, {match.group(3)}"

    def iso(match: re.Match[str]) -> str:
        try:
            parsed = datetime(
                int(match.group(1)), int(match.group(2)), int(match.group(3)),
            )
        except ValueError:
            return match.group(0)
        return f"{parsed.strftime('%B')} {parsed.day}, {parsed.year}"

    return _ISO_DATE.sub(iso, _DAY_MONTH.sub(day_month, text))


def _display(value, *, places: int | None = None) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    formatted = receipt_math.public_display(value, places=places)
    if formatted is not None:
        return formatted
    return _customer_english(str(value))


def _display_date(value: str, *, field: str) -> str:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise SystemExit(f"render: {field} is not an ISO date or timestamp") from exc
    return f"{parsed.strftime('%B')} {parsed.day}, {parsed.year}"


def _accepted_render_context(artifact: dict, render_context: dict | None
                             ) -> tuple[dict[str, dict], list[dict]]:
    """Accept private mechanics only when they match the public accepted ledger."""
    if render_context is None:
        return {}, []
    if not isinstance(render_context, dict):
        raise SystemExit("render: accepted render context is not an object")
    if render_context.get("source_consideration_problems"):
        raise SystemExit("render: source consideration did not validate")
    public_checks = {
        str(row.get("id") or ""): row for row in artifact["evidence_checks"]
    }
    comparisons: dict[str, dict] = {}
    checks = render_context.get("checks") or render_context.get("validated") or []
    if not isinstance(checks, list):
        raise SystemExit("render: accepted context checks are not an array")
    for raw in checks:
        if not isinstance(raw, dict) or raw.get("numeric_comparison") is None:
            continue
        check_id = str(raw.get("id") or "")
        public = public_checks.get(check_id)
        if public is None or raw.get("public_receipt") != public.get("public_receipt"):
            raise SystemExit(
                "render: private numeric comparison does not match an accepted check")
        comparison = raw.get("numeric_comparison")
        if not isinstance(comparison, dict):
            raise SystemExit("render: private numeric comparison is invalid")
        mode = comparison.get("mode")
        if mode == "rounded":
            if set(comparison) != {
                "mode", "rounding", "decimal_places", "customer_result", "matches",
            } or not _publishable_text(comparison.get("customer_result")):
                raise SystemExit("render: accepted rounded comparison is incomplete")
        elif mode == "absolute_tolerance":
            if set(comparison) != {"mode", "tolerance", "matches"}:
                raise SystemExit("render: accepted tolerance comparison is incomplete")
        else:
            raise SystemExit("render: accepted numeric comparison mode is invalid")
        if comparison.get("matches") is not (
            public.get("verdict") == "confirmed"
        ):
            raise SystemExit(
                "render: accepted numeric comparison does not match the disposition")
        comparisons[check_id] = comparison

    source_rows = {
        str(row.get("id") or ""): row for row in artifact["sources"]
    }
    exclusions = render_context.get("whole_source_exclusions")
    if exclusions is None:
        exclusions = []
    if not isinstance(exclusions, list):
        raise SystemExit("render: whole_source_exclusions is not an array")
    clean_considerations: list[dict] = []
    seen: set[str] = set()
    citations: dict[str, set[str]] = {}
    for check in artifact["evidence_checks"]:
        source_id = str(
            ((check.get("public_receipt") or {}).get("source_id") or "")
        )
        if source_id:
            citations.setdefault(source_id, set()).add(str(check.get("claim_id") or ""))
    for row in exclusions:
        if not isinstance(row, dict):
            raise SystemExit("render: whole_source_exclusions row is not an object")
        source_id = str(row.get("source_id") or "")
        if source_id not in source_rows or source_id in seen:
            raise SystemExit("render: whole-source exclusion is invalid or duplicated")
        seen.add(source_id)
        reason = str(row.get("exclusion_reason") or "").strip()
        if set(row) != {"source_id", "exclusion_reason"} \
                or citations.get(source_id) or not _publishable_text(reason):
            raise SystemExit("render: whole-source exclusion is invalid")
        clean_considerations.append({
            "source_id": source_id, "exclusion_reason": reason,
        })
    return comparisons, clean_considerations


def _card_html(check: dict, claim: dict, sources: dict[str, dict], *,
               prominence: str, numeric_comparison: dict | None = None) -> str:
    receipt = check["public_receipt"]
    report_operand = receipt["report_operand"]
    report_places = receipt_math.decimal_places(report_operand["value"])
    disposition = _fixed_label(
        DISPOSITION_LABELS, str(check["verdict"]), "disposition")
    decisive = receipt.get("decisive_operands") or []
    operands: list[str] = []
    calculation = ""
    if receipt.get("calculation"):
        expression = html.escape(receipt["calculation"]["expression"])
        result = html.escape(
            _display(receipt["calculation"]["result"], places=report_places))
        math_rows = "".join(
            '<tr data-operand-role="decisive"><td>'
            f'<strong>{html.escape(row["label"])}</strong>'
            f'<span class="math-location">{html.escape(_customer_english(row["location"]))}</span>'
            f'</td><td class="v">{html.escape(_display(row["value"]))}</td></tr>'
            for row in decisive
        )
        calculation = (
            '<div class="calculation">'
            '<table class="receipt-math num"><tbody>'
            f'{math_rows}'
            '<tr class="sum"><td>Calculated result</td>'
            f'<td class="v">{result}</td></tr>'
            + (
                '<tr class="customer-rounded"><td>Customer-rounded result</td>'
                f'<td class="v">{html.escape(_display(numeric_comparison["customer_result"]))}</td></tr>'
                if isinstance(numeric_comparison, dict)
                and numeric_comparison.get("mode") == "rounded"
                else ""
            )
            + (
            '<tr class="report"><td>Report shows'
            f'<span class="math-location">{html.escape(report_operand["label"])} · '
            f'{html.escape(_customer_english(report_operand["location"]))}</span></td>'
            f'<td class="v">{html.escape(_display(report_operand["value"]))}</td></tr>'
            '</tbody></table>'
            '<span class="receipt-key expression-key">Calculation expression</span>'
            f'<span class="calculation-line">{expression} = {result}</span></div>'
            )
        )
    else:
        operands.append(
            '<div class="operand receipt-row" data-operand-role="report">'
            f'<strong class="operand-label">{html.escape(report_operand["label"])}</strong>'
            f'<span class="value">{html.escape(_display(report_operand["value"]))}</span>'
            f'<span class="location">{html.escape(_customer_english(report_operand["location"]))}</span>'
            "</div>"
        )
        for row in decisive:
            operands.append(
                '<div class="operand receipt-row" data-operand-role="decisive">'
                f'<strong class="operand-label">{html.escape(row["label"])}</strong>'
                f'<span class="value">{html.escape(_display(row["value"]))}</span>'
                f'<span class="location">{html.escape(_customer_english(row["location"]))}</span>'
                "</div>"
            )
    reconstruction = ""
    if receipt.get("reconstruction_attempt"):
        reconstruction = (
            '<div class="reconstruction-attempt">'
            '<span class="receipt-key">Reconstruction attempt</span>'
            f'<p>{html.escape(_customer_english(receipt["reconstruction_attempt"]))}</p></div>'
        )
    source_html = ""
    source_id = str(receipt.get("source_id") or "")
    if source_id:
        source = sources.get(source_id)
        if source is None:
            raise SystemExit(f"render: card source {source_id!r} is not retained")
        source_kind = _fixed_label(
            SOURCE_KIND_LABELS, str(source["kind"]), "source kind")
        retrieval = ""
        if source["kind"] == "live_tool":
            retrieval = (
                '<span class="source-time">Retrieved '
                f'{html.escape(source["retrieval"]["retrieved_at"])}</span>'
            )
        source_html = (
            '<div class="card-source">'
            '<span class="receipt-key">Source</span>'
            f'<strong>{html.escape(source["label"])}</strong>'
            f'<code>{html.escape(source["evidence_file"])}</code>'
            f'<span>{html.escape(source_kind)}</span>{retrieval}</div>'
        )
    return (
        '<article class="material-card" '
        f'data-card-id="{html.escape(check["id"])}" '
        f'data-disposition="{html.escape(check["verdict"])}" '
        f'data-prominence="{html.escape(prominence)}">'
        f'<span class="tag">{html.escape(disposition)}</span>'
        f'<h3>{html.escape(report_operand["label"])}</h3>'
        f'<div class="where">{html.escape(_customer_english(report_operand["location"]))}</div>'
        f'<blockquote class="claim-quote">{html.escape(claim["quote"])}</blockquote>'
        '<div class="receipt"><h4>Receipt</h4>'
        f'{"".join(operands)}{calculation}'
        '<div class="receipt-explanation"><span class="receipt-key">Explanation</span>'
        f'<p>{html.escape(_customer_english(receipt["explanation"]))}</p></div>'
        f'{reconstruction}{source_html}</div>'
        "</article>"
    )


def _outcome_section(verdict: str, cards: list[str], *,
                     technical_confirmed: int = 0) -> str:
    if not cards:
        return ""
    label = _fixed_label(DISPOSITION_LABELS, verdict, "disposition")
    count = len(cards)
    noun = "outcome" if count == 1 else "outcomes"
    technical = ""
    if verdict == "confirmed" and technical_confirmed:
        technical_noun = "outcome" if technical_confirmed == 1 else "outcomes"
        verb = "is" if technical_confirmed == 1 else "are"
        technical = (
            '<p class="sectionlede technical-note">'
            f'{technical_confirmed} lower-priority confirmed {technical_noun} '
            f'{verb} available under Technical detail.</p>'
        )
    return (
        f'<section class="outcome-section" data-outcome-section="{html.escape(verdict)}">'
        f'<h2>{html.escape(label)}</h2>'
        f'<p class="sectionlede">{count} {html.escape(label.lower())} {noun}.</p>'
        f'{"".join(cards)}{technical}</section>'
    )


def _not_checkable_section(rows: list[tuple[dict, dict]]) -> str:
    if not rows:
        return ""
    items = "".join(
        '<li class="not-checkable-item"><span class="compact-claim">'
        f'<strong>{html.escape(claim["quote"])}</strong>'
        f'<span>{html.escape(_customer_english(check["public_receipt"]["explanation"]))}</span>'
        '</span></li>'
        for check, claim in rows
    )
    count = len(rows)
    noun = "outcome" if count == 1 else "outcomes"
    label = _fixed_label(DISPOSITION_LABELS, "not_checkable", "disposition")
    return (
        '<section class="outcome-section compact-outcomes" '
        'data-outcome-section="not_checkable">'
        f'<h2>{html.escape(label)}</h2>'
        f'<p class="sectionlede">{count} {html.escape(label.lower())} {noun}; complete receipts '
        'are available under Technical detail.</p>'
        f'<ul class="plain">{items}</ul></section>'
    )


def html_of(artifact: dict, *, render_context: dict | None = None) -> str:
    """Lay accepted public fields into the locked customer hierarchy."""
    validate_artifact(artifact)
    comparisons, source_consideration = _accepted_render_context(
        artifact, render_context)
    sources = {str(row["id"]): row for row in artifact["sources"]}
    claims_by_check = {
        str(row.get("check_id") or ""): row for row in artifact["claims"]
        if row.get("classification") != "supporting_provenance"
        and row.get("importance") != "supporting"
    }
    prominent: dict[str, list[str]] = {key: [] for key in DISPOSITIONS}
    technical_confirmed: list[str] = []
    technical_not_checkable: list[str] = []
    compact_not_checkable: list[tuple[dict, dict]] = []
    presentation = artifact.get("presentation")
    if not isinstance(presentation, dict):
        raise SystemExit("render: accepted presentation is missing")
    summary_ids = presentation.get("check_ids")
    if not isinstance(summary_ids, list):
        raise SystemExit("render: accepted presentation check ids are missing")
    visible_confirmed = {str(value) for value in summary_ids}
    for check in artifact["evidence_checks"]:
        claim = claims_by_check.get(str(check["id"]))
        if claim is None:
            continue
        is_technical = (
            check["verdict"] == "confirmed" and check["id"] not in visible_confirmed
        ) or check["verdict"] == "not_checkable"
        placement = "technical" if is_technical else "prominent"
        card = _card_html(
            check, claim, sources, prominence=placement,
            numeric_comparison=comparisons.get(str(check["id"])),
        )
        if check["verdict"] == "not_checkable":
            technical_not_checkable.append(card)
            compact_not_checkable.append((check, claim))
        elif is_technical:
            technical_confirmed.append(card)
        else:
            prominent[check["verdict"]].append(card)

    counts = artifact["evidence_coverage"]
    stat_order = (
        ("contradicted", "red"),
        ("confirmed", "green"),
        ("changed_since_report", "amber"),
        ("not_checkable", "gray"),
    )
    stats = "".join(
        f'<div class="stat {tone}" data-count-for="{html.escape(verdict)}">'
        f'<div class="n num">{counts[verdict]}</div>'
        f'<div class="l">{html.escape(_fixed_label(DISPOSITION_LABELS, verdict, "disposition"))}</div>'
        '<div class="s">material outcomes</div></div>'
        for verdict, tone in stat_order
    )
    sections = "".join(
        _outcome_section(
            verdict,
            prominent[verdict],
            technical_confirmed=len(technical_confirmed),
        )
        for verdict in (
            "contradicted", "confirmed", "changed_since_report"
        )
    ) + _not_checkable_section(compact_not_checkable)
    source = artifact["source"]
    filename = str(source["path"])
    generated = _display_date(artifact["generated_at"], field="generated_at")
    period = _customer_english(str(source.get("period_label") or "Not stated"))
    report_date = (
        _display_date(str(source["report_date"]), field="source.report_date")
        if source.get("report_date") else "Not stated"
    )
    root_verdict = str(artifact["verdict"])
    root_label = _root_headline(root_verdict, counts)
    root_chip_label = _fixed_label(
        ROOT_CHIP_LABELS, root_verdict, "root verdict chip")
    root_tone = _fixed_label(ROOT_TONES, root_verdict, "root tone")
    material_total = int(counts["validated_outcomes"])
    material_noun = "outcome" if material_total == 1 else "outcomes"
    count_sentence = (
        f'This review covers {material_total} material {material_noun}: '
        f'{counts["confirmed"]} confirmed, {counts["contradicted"]} contradicted, '
        f'{counts["not_checkable"]} not checkable, and '
        f'{counts["changed_since_report"]} changed since the report.'
    )
    live_ran = artifact["verification"]["live_source"]["status"] == "complete"
    live_text = "Ran" if live_ran else "Did not run"
    deferred_cards = [*technical_confirmed, *technical_not_checkable]
    technical_cards = (
        '<div class="technical-cards">' + "".join(deferred_cards) + "</div>"
        if deferred_cards else '<div class="technical-cards"></div>'
    )
    cited = len({
        str((row.get("public_receipt") or {}).get("source_id") or "")
        for row in artifact["evidence_checks"]
        if (row.get("public_receipt") or {}).get("source_id")
    })
    excluded_sources = []
    for row in source_consideration:
        if "exclusion_reason" not in row:
            continue
        source_row = sources[row["source_id"]]
        excluded_sources.append(
            '<li><div class="excluded-source-meta">'
            f'<strong>{html.escape(source_row["label"])}</strong>'
            f'<code>{html.escape(source_row["evidence_file"])}</code>'
            f'<span>{html.escape(_fixed_label(SOURCE_KIND_LABELS, source_row["kind"], "source kind"))}</span>'
            '</div>'
            f'<p>{html.escape(row["exclusion_reason"])}</p></li>'
        )
    source_exclusions = (
        '<div class="source-exclusions"><h3>Excluded retained sources</h3><ul>'
        + "".join(excluded_sources) + '</ul></div>'
        if excluded_sources else ""
    )
    actions = artifact.get("actions") or []
    if not actions:
        raise SystemExit("render: accepted customer action is missing")
    if len(actions) == 1:
        next_content = html.escape(_customer_english(actions[0]["text"]))
    else:
        next_content = "<ul>" + "".join(
            f'<li>{html.escape(_customer_english(row["text"]))}</li>'
            for row in actions
        ) + "</ul>"
    receipt_noun = "receipt" if material_total == 1 else "receipts"
    css = """
:root{--ink:#191b1e;--ink-2:#4b5158;--ink-3:#787f87;--paper:#fdfdfc;--panel:#f4f4f1;--line:#e3e3de;--red:#b42318;--red-soft:#fdf0ee;--green:#1a7f4b;--green-soft:#eef7f1;--amber:#9a5b0b;--amber-soft:#fbf4e8;--gray:#5d646c;--gray-soft:#f0f1f2}
*{box-sizing:border-box;margin:0;padding:0;min-width:0}
html{-webkit-text-size-adjust:100%;overflow-x:hidden}
body{font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;color:var(--ink);background:var(--paper);padding:0 24px 64px;overflow-x:hidden}
.page{width:100%;max-width:730px;margin:0 auto}.num{font-variant-numeric:tabular-nums}
header{display:flex;justify-content:space-between;align-items:baseline;gap:16px;flex-wrap:wrap;padding:24px 0 14px;border-bottom:1px solid var(--line)}
.wordmark{font-weight:700;font-size:15px}.wordmark span{color:var(--ink-3);font-weight:500}.runmeta{font-size:13px;color:var(--ink-3)}
.verdict{padding:40px 0 8px}.chip{display:inline-block;font-size:12px;font-weight:700;letter-spacing:.06em;padding:4px 10px;border-radius:4px;margin-bottom:14px}
.chip.fix{background:var(--red-soft);color:var(--red);border:1px solid #ecc8c3}.chip.safe{background:var(--green-soft);color:var(--green);border:1px solid #c6e2d2}.chip.warn{background:var(--amber-soft);color:var(--amber);border:1px solid #ecd9b8}.chip.neutral{background:var(--gray-soft);color:var(--gray);border:1px solid var(--line)}
h1{font-size:31px;line-height:1.15;letter-spacing:-.015em;font-weight:700;max-width:30ch;text-wrap:balance}.verdict p{margin-top:12px;font-size:16px;color:var(--ink-2);max-width:62ch;text-wrap:pretty}
.verdict .verdict-summary{color:var(--ink);font-weight:500}.verdict .count-summary{font-size:14px}
.file{font-size:13px;color:var(--ink-3);margin-top:16px;display:flex;gap:6px 14px;flex-wrap:wrap}.file code{font:12.5px ui-monospace,SFMono-Regular,Menlo,monospace;background:var(--panel);padding:2px 6px;border-radius:4px;color:var(--ink-2);overflow-wrap:anywhere}
.stats{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));border:1px solid var(--line);border-radius:8px;overflow:hidden;margin:30px 0 0;background:#fff}
.stat{padding:16px 18px 14px;border-left:1px solid var(--line)}.stat:first-child{border-left:none}.stat .n{font-size:26px;font-weight:700;letter-spacing:-.02em}.stat .l{font-size:13px;font-weight:600;margin-top:2px}.stat .s{font-size:12px;color:var(--ink-3);margin-top:2px;text-wrap:balance}.stat.red .l{color:var(--red)}.stat.green .l{color:var(--green)}.stat.amber .l{color:var(--amber)}.stat.gray .l{color:var(--gray)}
section{margin-top:44px}h2{font-size:18px;letter-spacing:-.01em;margin-bottom:6px}.sectionlede{font-size:14px;color:var(--ink-2);margin-bottom:16px;max-width:62ch}.technical-note{margin:12px 0 0}
.material-card{width:100%;border:1px solid var(--line);border-left:3px solid var(--gray);border-radius:8px;background:#fff;padding:20px 22px;overflow-wrap:anywhere;break-inside:avoid;page-break-inside:avoid}.material-card+.material-card{margin-top:12px}
.material-card[data-disposition="contradicted"]{border-left-color:var(--red)}.material-card[data-disposition="confirmed"]{border-left-color:var(--green)}.material-card[data-disposition="changed_since_report"]{border-left-color:var(--amber)}
.tag{font-size:11.5px;font-weight:700;letter-spacing:.06em;border-radius:4px;display:inline-block;padding:3px 8px;margin-bottom:10px;background:var(--gray-soft);color:var(--gray)}
.material-card[data-disposition="contradicted"] .tag{background:var(--red-soft);color:var(--red)}.material-card[data-disposition="confirmed"] .tag{background:var(--green-soft);color:var(--green)}.material-card[data-disposition="changed_since_report"] .tag{background:var(--amber-soft);color:var(--amber)}
.material-card h3{font-size:16px;text-wrap:balance}.where{font-size:13px;color:var(--ink-3);margin-top:2px;overflow-wrap:anywhere;word-break:break-word}.claim-quote{font-size:14px;color:var(--ink-2);margin-top:12px;padding-left:12px;border-left:2px solid var(--line);white-space:normal;overflow-wrap:anywhere}
.receipt{margin-top:16px;border-top:1px dashed var(--line);padding-top:12px}.receipt h4{font-size:13px;margin-bottom:8px}.operand{display:grid;grid-template-columns:minmax(0,1.1fr) minmax(0,.65fr) minmax(0,1.5fr);gap:8px 14px;padding:7px 0;font-size:13px;align-items:start}.operand+.operand{border-top:1px solid var(--line)}.operand-label{font-weight:600}.value{font-variant-numeric:tabular-nums;font-weight:600}.location{color:var(--ink-3);overflow-wrap:anywhere;word-break:break-word;white-space:normal}
.receipt-key{display:block;color:var(--ink-3);font-size:12px;font-weight:600}.calculation,.receipt-explanation,.reconstruction-attempt,.card-source{margin-top:12px;font-size:13px}.calculation-line{display:block;margin-top:3px;font:12.5px ui-monospace,SFMono-Regular,Menlo,monospace;overflow-wrap:anywhere}.receipt-explanation p,.reconstruction-attempt p{margin-top:3px;color:var(--ink-2);max-width:62ch}.card-source{display:flex;gap:5px 10px;align-items:baseline;flex-wrap:wrap;border-top:1px solid var(--line);padding-top:10px}.card-source .receipt-key{width:100%}.card-source code{font:12px ui-monospace,SFMono-Regular,Menlo,monospace;background:var(--panel);padding:1px 5px;border-radius:3px;overflow-wrap:anywhere}.source-time{color:var(--ink-3)}
.receipt-math{width:100%;max-width:460px;table-layout:fixed;border-collapse:collapse;font-size:13px}.receipt-math td{padding:7px 0;vertical-align:top;overflow-wrap:break-word;word-break:normal;hyphens:manual}.receipt-math td.v{text-align:right;padding-left:12px;font-weight:600;white-space:normal;overflow-wrap:break-word;word-break:normal;width:34%}.receipt-math tr+tr td{border-top:1px solid var(--line)}.receipt-math tr.sum td{font-weight:700}.receipt-math tr.report td{color:var(--red);font-weight:700}.material-card[data-disposition="confirmed"] .receipt-math tr.report td{color:var(--green)}.math-location{display:block;color:var(--ink-3);font-size:12px;font-weight:400;overflow-wrap:anywhere}.expression-key{margin-top:10px}.plain{list-style:none}.not-checkable-item{padding:12px 0;border-bottom:1px solid var(--line);font-size:14px}.not-checkable-item:last-child{border-bottom:none}.compact-claim{display:block;max-width:66ch}.compact-claim strong{display:block;color:var(--ink)}.compact-claim span{display:block;margin-top:3px;color:var(--ink-2)}
.scope{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px 26px;margin-top:8px;font-size:13px}.scope div{color:var(--ink-3);text-wrap:pretty}.scope b{display:block;color:var(--ink);font-weight:600;font-size:13.5px}
.source-exclusions{margin-top:18px;border-top:1px solid var(--line);padding-top:14px}.source-exclusions h3{font-size:14px}.source-exclusions ul{list-style:none;margin-top:8px}.source-exclusions li{padding:8px 0}.source-exclusions li+li{border-top:1px solid var(--line)}.excluded-source-meta{display:flex;gap:5px 10px;align-items:baseline;flex-wrap:wrap;font-size:12.5px}.excluded-source-meta code{font:12px ui-monospace,SFMono-Regular,Menlo,monospace;background:var(--panel);padding:1px 5px;border-radius:3px;overflow-wrap:anywhere}.excluded-source-meta span{color:var(--ink-3)}.source-exclusions p{font-size:13px;color:var(--ink-2);margin-top:3px;max-width:62ch}
.next{margin-top:34px;background:var(--panel);border-radius:8px;padding:16px 20px;font-size:14px;color:var(--ink-2)}.next b{color:var(--ink)}
details{margin-top:26px;font-size:13px;color:var(--ink-3)}details summary{cursor:pointer;font-weight:600;color:var(--ink-2)}.technical-cards{margin-top:14px}.technical-cards:empty{display:none}
footer{margin-top:52px;border-top:1px solid var(--line);padding-top:18px;display:flex;justify-content:space-between;gap:16px;flex-wrap:wrap;font-size:13px;color:var(--ink-3)}
@media(max-width:40rem){body{padding:0 16px 48px}.verdict{padding-top:30px}h1{font-size:27px}.stats{grid-template-columns:repeat(2,minmax(0,1fr))}.stat{border-top:1px solid var(--line)}.stat:nth-child(-n+2){border-top:none}.stat:nth-child(3){border-left:none}.material-card{padding:18px 16px}.operand{grid-template-columns:minmax(0,1fr);gap:2px}.operand .value{margin-top:2px}.operand .location{margin-top:2px}.scope{grid-template-columns:minmax(0,1fr)}.receipt-math td.v{white-space:normal;width:36%}}
@media print{body{padding:0;background:#fff}.material-card,.stats{break-inside:avoid;page-break-inside:avoid}.technical-scope,.scope,.source-exclusions,.source-exclusions li,.operand,.receipt-row,.receipt-math tr,.calculation,.receipt-explanation,.card-source{break-inside:avoid;page-break-inside:avoid}.next{border:1px solid var(--line)}details.technical-detail>summary{display:block;list-style:none;font-size:18px;color:var(--ink);margin-bottom:12px}details.technical-detail>summary::-webkit-details-marker{display:none}details.technical-detail:not([open])>.technical-cards{display:block!important}footer{margin-top:28px}}
"""
    return (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>Verification: {html.escape(filename)}</title><style>{css}</style></head>'
        f'<body><main class="page" data-schema-version="{SCHEMA_VERSION}" '
        f'data-verdict="{html.escape(root_verdict)}">'
        '<header><div class="wordmark">Summation <span>/ Verify</span></div>'
        f'<div class="runmeta num">Generated {html.escape(generated)}</div></header>'
        '<div class="verdict">'
        f'<span class="chip {html.escape(root_tone)}">'
        f'{html.escape(root_chip_label)}</span>'
        f'<h1>{html.escape(root_label)}</h1>'
        f'<p class="verdict-summary">{html.escape(_customer_english(presentation["summary"]))}</p>'
        f'<p class="count-summary">{html.escape(count_sentence)}</p>'
        '<div class="file">'
        f'<span>Report examined: <code>{html.escape(filename)}</code></span>'
        f'<span>Period: {html.escape(period)}</span>'
        f'<span>Report date: {html.escape(report_date)}</span></div></div>'
        f'<div class="stats" role="group" aria-label="Verification results">{stats}</div>'
        f'{sections}'
        '<section class="technical-scope"><h2>Technical scope</h2><div class="scope">'
        f'<div><b>Material outcomes</b>{material_total} accepted {receipt_noun}</div>'
        f'<div><b>Retained sources</b>{len(artifact["sources"])} retained; {cited} cited</div>'
        f'<div><b>Live source</b>{html.escape(live_text)}</div>'
        f'<div><b>Report format</b>{html.escape(source["format"])}</div>'
        f'</div>{source_exclusions}</section>'
        f'<div class="next"><b>Next:</b> {next_content}</div>'
        '<details class="technical-detail"><summary>Technical detail</summary>'
        f'{technical_cards}</details>'
        '<footer><div>Checked by Summation Verify</div>'
        f'<div class="num">Run {html.escape(artifact["run_id"])} · {html.escape(generated)}</div>'
        '</footer></main></body></html>\n'
    )


def document_errors_unaccounted(raw: dict) -> bool:
    """Require every machine error id to be owned by an agent contradiction."""
    errors = [
        row for row in (raw.get("findings") or [])
        if isinstance(row, dict) and row.get("tier") == "D"
    ]
    if not errors:
        return False
    contradicted_ids = set()
    for claim in _material_claims(raw):
        if claim.get("outcome") == "contradicted":
            contradicted_ids.update(str(value) for value in claim.get("inventory_ids") or [])
    for finding in errors:
        ids = {str(value) for value in finding.get("inventory_ids") or []}
        if not ids or not ids <= contradicted_ids:
            return True
    return False


def ungraded_reason(raw: dict, has_receipts: bool,
                    receipts: dict | None = None) -> str | None:
    if not isinstance(raw, dict):
        return "findings input is not an object"
    if not has_receipts or not isinstance(receipts, dict):
        return "accepted receipts are required"
    if receipts.get("discarded") or receipts.get("discarded_claims"):
        return "accepted receipt ledger contains discarded rows"
    if receipts.get("discarded_sources"):
        return "retained source metadata did not validate"
    if receipts.get("source_consideration_problems"):
        return "approved source consideration did not validate"
    if not isinstance(receipts.get("source_consideration"), list):
        return "approved source consideration is missing"
    if receipts.get("status") != "complete":
        return "accepted private workflow is not complete"
    if receipts.get("contract_version") != "verify-role-handoff/coordinator-v6":
        return "accepted private workflow version is invalid"
    if not isinstance(receipts.get("assessments"), list) \
            or not isinstance(receipts.get("resolutions"), list):
        return "accepted private assessment or resolution ledger is missing"
    if not isinstance(receipts.get("whole_source_exclusions"), list):
        return "accepted whole-source exclusion ledger is missing"
    if receipts.get("presentation_problems"):
        return "accepted customer presentation did not validate"
    presentation = receipts.get("presentation")
    if not isinstance(presentation, dict) or not presentation.get("actions"):
        return "accepted customer presentation is missing an action"
    inventory = raw.get("inventory") or {}
    if not inventory.get("complete"):
        return "report inventory is incomplete"
    if raw.get("inventory_missing"):
        return "material inventory is not fully accounted for"
    claims = _material_claims(raw)
    if not claims:
        return "material claim ledger is empty"
    if any(
        row.get("outcome") not in DISPOSITIONS or not row.get("check_id")
        for row in claims
    ):
        return "every material claim needs an accepted disposition"
    material_inventory_ids = {
        str(row.get("id") or "") for row in inventory.get("items") or []
        if isinstance(row, dict) and row.get("importance") == "material"
    } - {""}
    claim_ids_by_inventory: dict[str, list[str]] = {}
    for claim in claims:
        claim_id = str(claim.get("id") or "")
        for value in claim.get("inventory_ids") or []:
            inventory_id = str(value or "")
            if inventory_id:
                claim_ids_by_inventory.setdefault(inventory_id, []).append(claim_id)
    coordinator = raw.get("coordinator")
    expected_by_inventory = (
        coordinator.get("material_inventory_claim_ids")
        if isinstance(coordinator, dict) else None
    )
    if isinstance(expected_by_inventory, dict) and expected_by_inventory:
        expected = {
            str(inventory_id): [str(claim_id) for claim_id in claim_ids]
            for inventory_id, claim_ids in expected_by_inventory.items()
            if isinstance(claim_ids, list)
        }
        if set(expected) != material_inventory_ids or any(
            len(actual) != len(set(actual))
            or set(actual) != set(expected.get(inventory_id) or [])
            for inventory_id, actual in claim_ids_by_inventory.items()
        ) or set(claim_ids_by_inventory) != set(expected):
            return "material inventory clause membership does not reconcile with claims"
    else:
        if (
            set(claim_ids_by_inventory) != material_inventory_ids
            or any(len(values) != 1 for values in claim_ids_by_inventory.values())
            or not claim_ids_by_inventory
        ):
            return "material inventory ids do not reconcile with claims"
    cov = coverage(raw)
    if material_inventory_ids and (
        cov.get("extractor_checkable_fraction") != 1
        or cov.get("engine_checkable_fraction") != 1
    ):
        return "material inventory coverage is incomplete"
    checks = receipts.get("checks") or receipts.get("validated")
    if not isinstance(checks, list):
        return "accepted checks are missing"
    if len({str(row.get("id") or "") for row in checks}) != len(checks):
        return "accepted check ids are duplicated"
    chosen = {str(row.get("check_id") or "") for row in claims}
    if chosen != {str(row.get("id") or "") for row in checks if row.get("importance") == "material"}:
        return "material claim and check ledgers do not reconcile"
    if document_errors_unaccounted(raw):
        return "machine errors are not owned by agent-authored contradictions"
    if receipts.get("semantic_status") != "complete":
        return "semantic ledger is incomplete"
    return None


def attach_receipts_ledger(raw: dict, receipts: dict) -> None:
    claims = receipts.get("claims")
    if isinstance(claims, list):
        raw["claims"] = claims
    if isinstance(receipts.get("inventory"), dict):
        raw["inventory"] = receipts["inventory"]
    if isinstance(receipts.get("coordinator"), dict):
        raw["coordinator"] = receipts["coordinator"]
    raw["inventory_missing"] = list(receipts.get("inventory_missing") or [])
    cov = raw.setdefault("coverage", {})
    cov["claims_in_ledger"] = int(receipts.get("claims_in_ledger") or 0)
    cov["claims_reached_by_a_check"] = int(
        receipts.get("claims_reached_by_a_check") or 0)
    if receipts.get("extractor_checkable_fraction") is not None:
        cov["extractor_checkable_fraction"] = receipts["extractor_checkable_fraction"]
    if receipts.get("engine_checkable_fraction") is not None:
        cov["engine_checkable_fraction"] = receipts["engine_checkable_fraction"]
    cov["inventory_material"] = sum(
        row.get("importance") == "material"
        for row in (raw.get("inventory") or {}).get("items") or []
    )
    verification = raw.setdefault("verification", {})
    semantic = verification.get("semantic")
    if not isinstance(semantic, dict):
        semantic = {"status": "not_run", "detail": None}
    semantic["status"] = str(receipts.get("semantic_status") or semantic.get("status"))
    semantic["detail"] = None
    verification["semantic"] = semantic
    source = raw.setdefault("source", {})
    if receipts.get("report_period"):
        source["period_label"] = receipts["report_period"]
    if receipts.get("report_date"):
        source["report_date"] = receipts["report_date"]
    raw["sources"] = list(receipts.get("sources") or [])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--findings", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--layer2", required=True, type=Path)
    args = parser.parse_args()
    if not args.findings.is_file():
        print(f"render: missing findings {args.findings}", file=sys.stderr)
        return 2
    if not args.layer2.is_file():
        print(f"render: missing layer2 {args.layer2}", file=sys.stderr)
        return 2
    try:
        raw = json.loads(args.findings.read_text())
        receipts = json.loads(args.layer2.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"render: invalid input: {exc}", file=sys.stderr)
        return 2
    if not isinstance(receipts, dict):
        print("render: layer2 must be the accepted receipts object", file=sys.stderr)
        return 2
    attach_receipts_ledger(raw, receipts)
    reason = ungraded_reason(raw, True, receipts)
    if reason:
        print(f"render: {reason}. No artifact written.", file=sys.stderr)
        return 2
    checks = receipts.get("checks") or receipts.get("validated") or []
    digest = str((raw.get("source") or {}).get("sha256") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        print("render: source sha256 is missing or invalid. No artifact written.", file=sys.stderr)
        return 2
    run_id = args.run_id or f"sf-{digest[:6]}"
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        artifact = artifact_from_findings(
            raw, run_id=run_id, generated_at=generated_at, layer2=checks,
            guidance=receipts.get("presentation"))
        page = html_of(artifact, render_context=receipts)
        from artifact_audit import audit_public_artifact  # noqa: E402
        problems = audit_public_artifact(
            artifact, page, render_context=receipts)
    except (SystemExit, ValueError) as exc:
        print(f"render: {exc}", file=sys.stderr)
        return 2
    if problems:
        print("render: public artifact failed invariant audit:", file=sys.stderr)
        for problem in problems[:12]:
            print(f"  - {problem}", file=sys.stderr)
        return 2
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "grade-artifact.json").write_text(
        json.dumps(artifact, indent=2) + "\n")
    (args.out_dir / "grade-artifact.html").write_text(page)
    print(args.out_dir / "grade-artifact.json")
    print(args.out_dir / "grade-artifact.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
