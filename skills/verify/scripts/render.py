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


SCHEMA_VERSION = "grade-artifact/public-receipt-v1"
DISPOSITIONS = frozenset({
    "confirmed", "contradicted", "not_checkable", "changed_since_report",
})
ROOT_VERDICTS = frozenset({
    "safe_to_share", "share_with_caveats", "fix_first", "unable_to_grade",
})
SOURCE_KINDS = frozenset({"supplied_file", "live_tool"})
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
    return not (label and _VAGUE.fullmatch(text))


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
        receipt = raw.get("public_receipt")
        if not _publishable_receipt(
            receipt, verdict=verdict, basis=basis, source_ids=source_ids
        ):
            raise SystemExit(f"render: check {check_id} public_receipt is not publishable")
        row = {key: raw.get(key) for key in CHECK_PUBLIC_KEYS}
        row["id"] = check_id
        row["verdict"] = verdict
        row["basis"] = basis
        row["severity"] = raw.get("severity") if verdict == "contradicted" else None
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


def _serialize_verification(raw: dict) -> dict:
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
        out[name] = {"status": row["status"], "detail": None}
    return out


def artifact_from_findings(raw: dict, *, run_id: str, generated_at: str,
                           layer2: list[dict] | None = None,
                           guidance: dict | None = None) -> dict:
    del guidance
    if not isinstance(raw, dict):
        raise SystemExit("render: input is not a JSON object")
    retained_sources = _public_sources(raw.get("sources") or [])
    public_checks = _public_layer2(layer2 or [], sources=retained_sources)
    material_claims = _material_claims(raw)
    chosen = {str(row.get("check_id") or "") for row in material_claims}
    material_public_checks = [
        row for row in public_checks if row.get("importance") == "material"]
    by_id = {row["id"]: row for row in material_public_checks}
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
    verification = _serialize_verification(raw)
    has_live_source = any(row["kind"] == "live_tool" for row in retained_sources)
    if has_live_source and verification["live_source"]["status"] != "complete":
        raise SystemExit("render: live_tool source requires exact complete live_source status")
    if not has_live_source and verification["live_source"]["status"] == "complete":
        raise SystemExit("render: static sources cannot declare complete live_source status")
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
        "actions": [],
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
        "claims": [_serialize_claim(row) for row in (raw.get("claims") or [])],
        "sources": retained_sources,
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
    except ImportError as exc:
        raise SystemExit("render: jsonschema is required") from exc
    jsonschema.validate(artifact, json.loads(schema_path.read_text()))


def _display(value) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def html_of(artifact: dict) -> str:
    """Render only accepted receipt fields, retained source labels, and enum tokens."""
    validate_artifact(artifact)
    sources = {str(row["id"]): row for row in artifact["sources"]}
    material_ids = {
        str(row.get("check_id") or "") for row in artifact["claims"]
        if row.get("classification") != "supporting_provenance"
        and row.get("importance") != "supporting"
    }
    cards = []
    for check in artifact["evidence_checks"]:
        if check["id"] not in material_ids:
            continue
        receipt = check["public_receipt"]
        report_operand = receipt["report_operand"]
        operands = [
            (
                '<div class="operand" data-operand-role="report">'
                f'<strong>{html.escape(report_operand["label"])}</strong>'
                f'<span class="value">{html.escape(_display(report_operand["value"]))}</span>'
                f'<span class="location">{html.escape(report_operand["location"])}</span>'
                "</div>"
            )
        ]
        for row in receipt.get("decisive_operands") or []:
            operands.append(
                '<div class="operand" data-operand-role="decisive">'
                f'<strong>{html.escape(row["label"])}</strong>'
                f'<span class="value">{html.escape(_display(row["value"]))}</span>'
                f'<span class="location">{html.escape(row["location"])}</span>'
                "</div>"
            )
        calculation = ""
        if receipt.get("calculation"):
            calculation = (
                '<p class="calculation">'
                f'{html.escape(receipt["calculation"]["expression"])} = '
                f'{html.escape(_display(receipt["calculation"]["result"]))}'
                "</p>"
            )
        reconstruction = ""
        if receipt.get("reconstruction_attempt"):
            reconstruction = (
                '<p class="reconstruction-attempt">'
                f'{html.escape(receipt["reconstruction_attempt"])}'
                "</p>"
            )
        source = ""
        source_id = str(receipt.get("source_id") or "")
        if source_id:
            row = sources[source_id]
            source = (
                f'<div class="source" data-source-id="{html.escape(source_id)}">'
                f'<span>{html.escape(row["label"])}</span>'
                f'<code>{html.escape(row["kind"])}</code>'
                "</div>"
            )
        cards.append(
            '<article class="material-card" '
            f'data-card-id="{html.escape(check["id"])}" '
            f'data-disposition="{html.escape(check["verdict"])}">'
            f'<h2>{html.escape(report_operand["label"])}</h2>'
            f'{"".join(operands)}'
            f'{calculation}'
            f'<p class="explanation">{html.escape(receipt["explanation"])}</p>'
            f'{reconstruction}{source}'
            "</article>"
        )
    counts = artifact["evidence_coverage"]
    count_nodes = "".join(
        f'<li data-count-for="{name}"><code>{name}</code><span>{counts[name]}</span></li>'
        for name in (
            "confirmed", "contradicted", "not_checkable", "changed_since_report"
        )
    )
    source_nodes = "".join(
        f'<li data-source-id="{html.escape(row["id"])}">'
        f'<span>{html.escape(row["label"])}</span><code>{html.escape(row["kind"])}</code></li>'
        for row in artifact["sources"]
    )
    return (
        "<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        "<title>grade-artifact</title><style>"
        "body{font-family:system-ui,sans-serif;max-width:70rem;margin:2rem auto;padding:0 1rem}"
        ".counts,.sources{display:flex;gap:1rem;flex-wrap:wrap;list-style:none;padding:0}"
        ".counts li,.sources li{display:flex;gap:.5rem}"
        ".material-card{border:1px solid #bbb;border-radius:.5rem;padding:1rem;margin:1rem 0}"
        ".operand{display:grid;grid-template-columns:minmax(12rem,1fr) 1fr 2fr;gap:1rem;padding:.35rem 0}"
        ".source{display:flex;gap:.5rem}.calculation{font-family:ui-monospace,monospace}"
        "</style></head>"
        f'<body><main data-schema-version="{SCHEMA_VERSION}" '
        f'data-verdict="{html.escape(artifact["verdict"])}">'
        f'<code class="verdict">{html.escape(artifact["verdict"])}</code>'
        f'<ul class="counts">{count_nodes}</ul>'
        f'<section class="material-cards">{"".join(cards)}</section>'
        f'<ul class="sources">{source_nodes}</ul>'
        "</main></body></html>\n"
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
    claimed_inventory_ids = [
        str(value) for claim in claims for value in claim.get("inventory_ids") or []
        if str(value)
    ]
    if (
        set(claimed_inventory_ids) != material_inventory_ids
        or len(claimed_inventory_ids) != len(set(claimed_inventory_ids))
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
            raw, run_id=run_id, generated_at=generated_at, layer2=checks)
        page = html_of(artifact)
        from artifact_audit import audit_public_artifact  # noqa: E402
        problems = audit_public_artifact(artifact, page)
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
