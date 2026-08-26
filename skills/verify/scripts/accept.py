#!/usr/bin/env python3
"""Keep or drop proposed checks by grounding them in the report and evidence.

A check survives when its quotes and pointers resolve. A bad row is discarded.
Semantic-plan preflight, full preflight, and acceptance use one pure validator.

Usage:
    accept.py --report <file> --checks checks.json --claims claims.json
              --out receipts.json [--evidence-dir DIR] [--report-text visible.txt]
"""
from __future__ import annotations

import argparse
import copy
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN, ROUND_HALF_UP
import hashlib
import html as html_lib
import json
import pathlib
import re
import sys

_SCRIPTS = pathlib.Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
from inventory import claim_inventory_ids, cover, inventory_for  # noqa: E402
from receipt_math import calculation_problem, public_number  # noqa: E402

CLAIM_CLASSIFICATIONS = frozenset({
    "material_claim", "supporting_provenance", "structural_context",
})
WORKFLOW_VERSION = "verify-role-handoff/coordinator-v6"
ASSESSMENT_EFFECTS = frozenset({
    "supports", "contradicts", "unreconciled", "changed_since_report",
})
RESOLUTION_STATES = frozenset({
    "supported", "contradicted", "unreconciled", "not_assessed",
    "dependency_unresolved", "changed_since_report",
})
ROLE_STAGES = (
    "mechanical_intake",
    "claim_taking",
    "coordinator_semantic_plan",
    "semantic_plan_preflight",
    "dependency_ordered_verification",
    "coordinator_global_resolution",
    "full_preflight",
    "single_repair_if_required",
    "final_acceptance_render_audit",
)
ROLE_STAGE_OWNERS = {
    "claim_taking": "claim_taker",
    "coordinator_semantic_plan": "coordinator",
    "dependency_ordered_verification": "evidence_verifier",
    "coordinator_global_resolution": "coordinator",
}
ROLE_INPUT_FIELDS = {
    "claim_taking": {
        "partition_id", "visible_text", "inventory", "report_metadata",
    },
    "coordinator_semantic_plan": {
        "partition_results", "inventory", "report_metadata",
        "internal_candidates", "approved_source_manifest",
    },
    "dependency_ordered_verification": {
        "canonical_claims", "relevant_report_text", "assigned_sources",
        "source_consideration_plan", "accepted_upstream_assessment_results",
    },
    "coordinator_global_resolution": {
        "canonical_claims", "assessments", "source_consideration_results",
        "claim_dependencies",
    },
}
ROLE_OUTPUT_FIELDS = {
    "claim_taking": {"partition_id", "occurrence_decisions", "clauses"},
    "coordinator_semantic_plan": {
        "classification_reviews", "canonical_claims",
        "source_consideration_plan", "claim_dependencies",
        "verifier_assignments",
    },
    "dependency_ordered_verification": {
        "assessments", "source_consideration_results",
        "proposed_resolutions", "checks",
    },
    "coordinator_global_resolution": {
        "sources", "source_consideration", "whole_source_exclusions",
        "assessments", "resolutions", "checks", "presentation",
    },
}
CANONICAL_CLAIM_CLASSIFICATIONS = frozenset({
    "material_claim", "supporting_provenance",
})


def load_known_verdicts(schema_path: pathlib.Path | None = None) -> frozenset:
    path = schema_path or (
        pathlib.Path(__file__).resolve().parent.parent / "schema.v1.json"
    )
    try:
        schema = json.loads(path.read_text())
        enum = schema["properties"]["evidence_checks"]["items"]["properties"]["verdict"]["enum"]
        if not isinstance(enum, list) or not enum:
            raise ValueError("empty verdict enum")
        return frozenset(enum)
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot load verdict enum from schema {path}: {exc}") from exc


KNOWN_VERDICTS = load_known_verdicts()
EVIDENCE_RECEIPT_VERDICTS = frozenset({
    "confirmed", "contradicted", "changed_since_report",
}) & KNOWN_VERDICTS


_SUFFIX = {
    "K": Decimal("1000"),
    "M": Decimal("1000000"),
    "B": Decimal("1000000000"),
}
_VISIBLE_NUMBER = re.compile(
    r"\((?:\$)?\d[\d,]*\.?\d*[KMB]?%?\)"
    r"|(?:\$)?-?\d[\d,]*\.?\d*[KMB]?%?",
    re.I,
)
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}
_MONTH_ALT = "|".join(sorted(_MONTHS, key=len, reverse=True))
_NAMED_DATE = re.compile(
    rf"(?i)\b({_MONTH_ALT})\s+(\d{{1,2}})(?:,)?\s+(\d{{4}})\b"
)
_DAY_MONTH_DATE = re.compile(
    rf"(?i)\b(\d{{1,2}})\s+({_MONTH_ALT})\s+(\d{{4}})\b"
)
VISIBLE_REPORT_SUFFIXES = frozenset({".html", ".md", ".txt", ".csv"})
SOURCE_KINDS = frozenset({"supplied_file", "live_tool"})
ACTION_KINDS = frozenset({
    "correct_report", "reconcile_before_change", "review_before_share",
})
POPULATION_DIMENSIONS = frozenset({
    "report_period", "as_of_date", "scope", "population_key",
})
ROUNDING_MODES = {
    "half_up": ROUND_HALF_UP,
    "half_even": ROUND_HALF_EVEN,
}
PRIVATE_NAMES = frozenset({
    "findings.json", "receipts.json", "checks.json", "claims.json",
    "grade-artifact.json", "report-visible.txt", "ledger.json",
    "source-findings.json", "provenance.json",
})
_ABS_PATH = re.compile(
    r"(?:/Users/|/home/|/var/folders/|/private/tmp/|/tmp/|[A-Z]:\\)[^\s\"'<]+",
    re.I,
)
_JSON_POINTER_EXACT = re.compile(
    r"(?<![A-Za-z0-9:])(?:/[A-Za-z0-9_~.-]+)+")
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
_VAGUE_OPERAND = re.compile(r"^(?:row|operand|item|value)(?:\s+\d+)?$", re.I)
_VAGUE_SOURCE = re.compile(
    r"^(?:source|evidence|supplied evidence|recorded evidence|live data)$", re.I)
_SOURCE_ID = re.compile(r"^[A-Za-z][A-Za-z0-9._-]*$")
_ISO_TIME = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)


def _valid_iso_time(value) -> bool:
    text = str(value or "").strip()
    if not _ISO_TIME.fullmatch(text):
        return False
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def parse_quantity(value) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float, Decimal)):
        try:
            return Decimal(str(value))
        except InvalidOperation:
            return None
    text = str(value).strip()
    if not text:
        return None
    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative = True
        text = text[1:-1].strip()
    text = text.replace(",", "")
    text = re.sub(r"^[\$€£¥]", "", text).strip()
    if text.endswith("%"):
        text = text[:-1].strip()
    mult = Decimal(1)
    if text and text[-1].upper() in _SUFFIX and re.search(r"\d", text[:-1]):
        body = text[:-1]
        if re.fullmatch(r"-?\d+(?:\.\d+)?", body):
            mult = _SUFFIX[text[-1].upper()]
            text = body
    try:
        number = Decimal(text) * mult
    except InvalidOperation:
        return None
    if negative:
        number = -abs(number)
    return number


def quantities_equal(left, right) -> bool:
    a = parse_quantity(left)
    b = parse_quantity(right)
    return a is not None and b is not None and a == b


def values_equal(left, right) -> bool:
    return left == right or quantities_equal(left, right)


def quote_in_text(quote: str, text: str) -> bool:
    """Locate a literal visible quote without numeric or semantic equivalence."""
    needle = normalize_visible(quote)
    haystack = normalize_visible(text)
    if not needle:
        return False
    start = 0
    while True:
        index = haystack.find(needle, start)
        if index < 0:
            return False
        before = haystack[index - 1] if index else ""
        after_index = index + len(needle)
        after = haystack[after_index] if after_index < len(haystack) else ""
        # These are literal token boundaries, not quantity parsing.  They stop
        # a short supplied quote from locating a substring inside a longer
        # visible token (for example, ``94`` inside ``94%``).
        left_ok = not needle[0].isalnum() or not (
            bool(before) and (before.isalnum() or before in "$€£¥.,")
        )
        right_ok = not needle[-1].isalnum() or not (
            bool(after) and (after.isalnum() or after in "%,")
        )
        if left_ok and right_ok:
            return True
        start = index + 1


def strip_tags(html: str) -> str:
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    return re.sub(r"<[^>]+>", " ", html)


def normalize_visible(text: str) -> str:
    visible = html_lib.unescape(strip_tags(str(text or "")))
    visible = normalize(visible)
    visible = re.sub(r"\s+([.,;:!?%])", r"\1", visible)
    visible = re.sub(r"([$€£¥])\s+", r"\1", visible)
    return visible


def explicit_value_in_quote(value, quote: str) -> bool:
    """Compare an already-selected operand only within its explicit quote."""
    if quote_in_text(str(value), quote):
        return True
    target = parse_quantity(value)
    if target is None:
        return False
    return any(
        quantities_equal(value, token)
        for token in _VISIBLE_NUMBER.findall(normalize_visible(quote))
    )


def load_text(path: pathlib.Path) -> str:
    raw = path.read_text(errors="replace")
    suffix = path.suffix.lower()
    if suffix == ".html":
        return normalize_visible(raw)
    return normalize(raw)


def _json_pointer(payload, pointer: str):
    if pointer == "":
        return payload
    if not pointer.startswith("/"):
        raise KeyError(pointer)
    current = payload
    for raw in pointer[1:].split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            current = current[int(token)]
        elif isinstance(current, dict):
            current = current[token]
        else:
            raise KeyError(pointer)
    return current


def json_pointer_receipt(evidence: pathlib.Path, receipts: list) -> tuple[bool, list | None]:
    if evidence.suffix.lower() != ".json" or not receipts:
        return False, None
    try:
        payload = json.loads(evidence.read_text())
    except (json.JSONDecodeError, OSError):
        return False, None
    canonical = []
    for receipt in receipts:
        if not isinstance(receipt, dict):
            return False, None
        pointer = str(receipt.get("pointer") or "")
        try:
            actual = _json_pointer(payload, pointer)
        except (KeyError, IndexError, ValueError, TypeError):
            return False, None
        if not values_equal(actual, receipt.get("value")):
            return False, None
        canonical.append({"pointer": pointer, "value": actual})
    return True, canonical


def needs_sidecar(report: pathlib.Path) -> bool:
    return report.suffix.lower() not in VISIBLE_REPORT_SUFFIXES


def evidence_path(
        sandbox: pathlib.Path, name: str, report_path: pathlib.Path | None
        ) -> tuple[pathlib.Path | None, str | None]:
    raw = str(name or "").strip()
    if not raw:
        return None, "evidence_file is missing"
    path = pathlib.Path(raw)
    if path.is_absolute() or raw.startswith("~"):
        return None, "evidence_file is an absolute path"
    sandbox_res = sandbox.resolve()
    candidate = (sandbox / raw).resolve()
    try:
        candidate.relative_to(sandbox_res)
    except ValueError:
        return None, "evidence_file is outside the evidence directory"
    if report_path is not None and candidate == report_path.resolve():
        return None, "report file is not valid evidence"
    if not candidate.is_file():
        return None, f"evidence_file {raw!r} missing"
    return candidate, None


def _public_text_problem(value, *, operand_label: bool = False,
                         source_label: bool = False) -> str | None:
    text = str(value or "").strip()
    if not text:
        return "is missing"
    if (
        _ABS_PATH.search(text)
        or _JSON_POINTER_EXACT.search(text)
        or _RAW_OFFICE_TOKEN.search(text)
        or _TENANT_IDENTIFIER.search(text)
        or _CREDENTIAL.search(text)
        or _BEARER.search(text)
        or any(name.lower() in text.lower() for name in PRIVATE_NAMES)
    ):
        return "is private or internal"
    if operand_label and _VAGUE_OPERAND.fullmatch(text):
        return "is vague"
    if source_label and _VAGUE_SOURCE.fullmatch(text):
        return "is vague"
    return None


def _metadata_problem(value, prefix: str) -> str | None:
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key or "").strip()
            if not key_text:
                return f"{prefix} has an empty argument name"
            if re.search(
                r"(?:password|secret|credential|api[_-]?key|access[_-]?token|"
                r"refresh[_-]?token)", key_text, re.I
            ):
                return f"{prefix}.{key_text} is credential metadata"
            problem = _metadata_problem(child, f"{prefix}.{key_text}")
            if problem:
                return problem
        return None
    if isinstance(value, list):
        for index, child in enumerate(value):
            problem = _metadata_problem(child, f"{prefix}[{index}]")
            if problem:
                return problem
        return None
    if value is None or isinstance(value, (bool, int, float)):
        return None
    problem = _public_text_problem(value)
    return f"{prefix} {problem}" if problem else None


def validate_sources(sandbox: pathlib.Path, proposed: list,
                     report_path: pathlib.Path | None = None) -> tuple[list, list]:
    """Validate retained evidence metadata without inferring source mode."""
    accepted: list[dict] = []
    discarded: list[dict] = []
    if not isinstance(proposed, list):
        return [], [{"id": "", "problems": ["sources is not a list"]}]
    identity_ids: dict[tuple[str, str, str], list[str]] = {}
    for raw in proposed:
        source = raw if isinstance(raw, dict) else {}
        identity = (
            str(source.get("kind") or "").strip(),
            str(source.get("evidence_file") or "").strip(),
            str(source.get("result_sha256") or "").strip().lower(),
        )
        if all(identity):
            identity_ids.setdefault(identity, []).append(
                str(source.get("id") or "").strip())
    duplicate_identities = {
        identity: ids for identity, ids in identity_ids.items() if len(ids) > 1
    }
    seen: set[str] = set()
    for raw in proposed:
        source = dict(raw) if isinstance(raw, dict) else {}
        problems: list[str] = []
        source_id = str(source.get("id") or "").strip()
        kind = str(source.get("kind") or "").strip()
        label = str(source.get("label") or "").strip()
        filename = str(source.get("evidence_file") or "").strip()
        digest = str(source.get("result_sha256") or "").strip().lower()
        if not source_id:
            problems.append("source id is missing")
        elif not _SOURCE_ID.fullmatch(source_id):
            problems.append("source id is not stable or public-safe")
        elif source_id in seen:
            problems.append(f"source id {source_id!r} is duplicated")
        if source_id:
            seen.add(source_id)
        if kind not in SOURCE_KINDS:
            problems.append("source kind is missing or unknown")
        label_problem = _public_text_problem(label, source_label=True)
        if label_problem:
            problems.append(f"source label {label_problem}")
        if not filename:
            problems.append("source evidence_file is missing")
            evidence = None
        elif pathlib.Path(filename).name != filename or pathlib.Path(filename).is_absolute():
            problems.append("source evidence_file must be a filename, not a path")
            evidence = None
        elif filename in PRIVATE_NAMES:
            problems.append("source evidence_file is a private sidecar name")
            evidence = None
        else:
            evidence, path_problem = evidence_path(sandbox, filename, report_path)
            if path_problem:
                problems.append(path_problem.replace("evidence_file", "source evidence_file", 1))
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            problems.append("source result_sha256 is missing or invalid")
        elif evidence is not None:
            actual = hashlib.sha256(evidence.read_bytes()).hexdigest()
            if actual != digest:
                problems.append("source result_sha256 does not match evidence file")
        retrieval = source.get("retrieval")
        if kind == "supplied_file" and "retrieval" in source:
            problems.append("supplied_file source must not declare live retrieval metadata")
        if kind == "live_tool":
            if not isinstance(retrieval, dict):
                problems.append("live_tool source retrieval metadata is missing")
            else:
                retrieved_at = str(retrieval.get("retrieved_at") or "").strip()
                tool = str(retrieval.get("tool") or "").strip()
                arguments = retrieval.get("arguments")
                if not _valid_iso_time(retrieved_at):
                    problems.append("live_tool source retrieval.retrieved_at is missing or invalid")
                tool_problem = _public_text_problem(tool)
                if tool_problem:
                    problems.append(f"live_tool source retrieval.tool {tool_problem}")
                if not isinstance(arguments, dict):
                    problems.append("live_tool source retrieval.arguments is not an object")
                else:
                    metadata_problem = _metadata_problem(arguments, "retrieval.arguments")
                    if metadata_problem:
                        problems.append(metadata_problem)
        allowed = {"id", "kind", "label", "evidence_file", "result_sha256", "retrieval"}
        unknown = sorted(set(source) - allowed)
        if unknown:
            problems.append(f"source has unknown field {unknown[0]!r}")
        canonical = {
            "id": source_id,
            "kind": kind,
            "label": label,
            "evidence_file": filename,
            "result_sha256": digest,
        }
        if kind == "live_tool" and isinstance(retrieval, dict):
            canonical["retrieval"] = {
                "retrieved_at": str(retrieval.get("retrieved_at") or "").strip(),
                "tool": str(retrieval.get("tool") or "").strip(),
                "arguments": retrieval.get("arguments"),
            }
        identity = (kind, filename, digest)
        if problems:
            discarded.append({**canonical, "problems": problems})
        elif identity not in duplicate_identities:
            accepted.append(canonical)
    for (kind, filename, digest), ids in duplicate_identities.items():
        quoted_ids = ", ".join(repr(source_id) for source_id in ids)
        discarded.append({
            "id": "",
            "group_problem": True,
            "problems": [
                "duplicate retained source identity for "
                f"kind {kind!r}, evidence_file {filename!r}, and "
                f"result_sha256 {digest!r} across ids [{quoted_ids}]"
            ],
        })
    return accepted, discarded


def report_text(report: pathlib.Path, sidecar: pathlib.Path | None) -> str:
    if sidecar is not None and sidecar.is_file():
        return load_text(sidecar)
    suffix = report.suffix.lower()
    if suffix in {".html", ".md", ".txt", ".csv"}:
        return load_text(report)
    try:
        return load_text(report)
    except (OSError, UnicodeError):
        return ""


def _json_values_from_receipts(finding: dict, receipt_updates: dict) -> list:
    values = []
    if "evidence_json" in receipt_updates:
        for item in receipt_updates.get("evidence_json") or []:
            if isinstance(item, dict) and "value" in item:
                values.append(item["value"])
    return values


def _resolved_receipt_values(finding: dict, receipt_updates: dict) -> list:
    return list(_json_values_from_receipts(finding, receipt_updates))


def validate_date_receipt(evidence: pathlib.Path | None, raw,
                          declared: str) -> tuple[dict | None, list[str]]:
    """Resolve only the date pointer or quote supplied by the agent."""
    if evidence is None or not isinstance(raw, dict) or not raw:
        return None, ["changed_since_report date_receipt is missing or invalid"]
    unknown = sorted(set(raw) - {"pointer", "value", "quote"})
    if unknown:
        return None, [f"date_receipt has unknown field {unknown[0]!r}"]
    pointer = str(raw.get("pointer") or "").strip()
    quote = str(raw.get("quote") or "").strip()
    if bool(pointer) == bool(quote):
        return None, ["date_receipt must contain exactly one pointer or quote"]
    if pointer:
        if "value" not in raw or quote:
            return None, ["date_receipt pointer requires an explicit value"]
        matched, canonical = json_pointer_receipt(
            evidence, [{"pointer": pointer, "value": raw.get("value")}])
        if not matched or not canonical:
            return None, ["date_receipt pointer did not match the retained source"]
        actual = canonical[0]["value"]
        if normalize(str(actual)) != normalize(declared):
            return None, ["current_as_of does not match date_receipt value"]
        return canonical[0], []
    if "value" in raw:
        return None, ["date_receipt quote must not declare a separate value"]
    if not quote_in_text(quote, load_text(evidence)):
        return None, ["date_receipt quote was not found in the retained source"]
    if not explicit_value_in_quote(declared, quote):
        return None, ["current_as_of does not match evidence date"]
    return {"quote": quote}, []


def validate_exact_source_receipt(evidence: pathlib.Path | None, raw,
                                  label: str) -> tuple[dict | None, list[str]]:
    """Resolve one host-selected source pointer or exact normalized quote."""
    if evidence is None:
        return None, [f"{label} has no retained source file"]
    if not isinstance(raw, dict) or not raw:
        return None, [f"{label} is missing or invalid"]
    unknown = sorted(set(raw) - {"pointer", "value", "quote"})
    if unknown:
        return None, [f"{label} has unknown field {unknown[0]!r}"]
    pointer = str(raw.get("pointer") or "").strip()
    quote = str(raw.get("quote") or "").strip()
    if bool(pointer) == bool(quote):
        return None, [f"{label} must contain exactly one pointer or quote"]
    if pointer:
        if "value" not in raw:
            return None, [f"{label} pointer requires an explicit value"]
        matched, canonical = json_pointer_receipt(
            evidence, [{"pointer": pointer, "value": raw.get("value")}])
        if not matched or not canonical:
            return None, [f"{label} did not match the retained source"]
        return canonical[0], []
    if "value" in raw:
        return None, [f"{label} quote must not declare a separate value"]
    if not quote_in_text(quote, load_text(evidence)):
        return None, [f"{label} did not match the retained source"]
    return {"quote": quote}, []


def _substantive_explanation(value) -> bool:
    text = str(value or "").strip()
    if _public_text_problem(text):
        return False
    if not re.search(r"[.!?]$", text):
        return False
    words = re.findall(r"[A-Za-z0-9%$]+", text)
    if len(words) < 6:
        return False
    if re.fullmatch(
        r"(?:confirmed|contradicted|matches?(?: the report)?|"
        r"the evidence supports the claim|the evidence does not match)\.?",
        text,
        re.I,
    ):
        return False
    return True


def validate_source_consideration(raw, sources: list[dict], claims: list[dict],
                                  checks: list[dict], *,
                                  assessments: list[dict] | None = None,
                                  coordinator_plan: list[dict] | None = None,
                                  ) -> tuple[list[dict], list[str]]:
    """Validate the complete host-authored source/material-claim pair matrix."""
    if not isinstance(raw, list):
        return [], ["source_consideration is missing or not an array"]
    source_ids = {
        str(row.get("id") or "").strip() for row in sources
        if isinstance(row, dict) and str(row.get("id") or "").strip()
    }
    material_claim_ids = {
        str(row.get("id") or "").strip() for row in claims
        if isinstance(row, dict)
        and row.get("classification") == "material_claim"
        and str(row.get("id") or "").strip()
    }
    assessment_by_id = {
        str(row.get("id") or "").strip(): row for row in (assessments or [])
        if isinstance(row, dict) and str(row.get("id") or "").strip()
    }
    check_by_claim = {
        str(row.get("claim_id") or "").strip(): row for row in checks
        if isinstance(row, dict) and str(row.get("claim_id") or "").strip()
    }

    plan_by_pair: dict[tuple[str, str], dict] = {}
    for row in coordinator_plan or []:
        if not isinstance(row, dict):
            continue
        pair = (
            str(row.get("source_id") or "").strip(),
            str(row.get("claim_id") or "").strip(),
        )
        if pair[0] and pair[1]:
            plan_by_pair[pair] = row

    accepted: list[dict] = []
    problems: list[str] = []
    seen: set[tuple[str, str]] = set()
    for index, row in enumerate(raw):
        label = f"source_consideration[{index}]"
        if not isinstance(row, dict):
            problems.append(f"{label} is not an object")
            continue
        unknown = sorted(set(row) - {
            "source_id", "claim_id", "coordinator_decision",
            "coordinator_reason", "verifier_decision", "verifier_reason",
            "assessment_ids",
        })
        if unknown:
            problems.append(f"{label} has unknown field {unknown[0]!r}")
        source_id = str(row.get("source_id") or "").strip()
        claim_id = str(row.get("claim_id") or "").strip()
        pair = (source_id, claim_id)
        if not source_id:
            problems.append(f"{label}.source_id is missing")
        elif source_id not in source_ids:
            problems.append(f"{label}.source_id {source_id!r} is not retained")
        if not claim_id:
            problems.append(f"{label}.claim_id is missing")
        elif claim_id not in material_claim_ids:
            problems.append(
                f"{label}.claim_id {claim_id!r} is not a material canonical claim")
        if pair in seen:
            problems.append(
                f"source/claim pair {source_id!r}/{claim_id!r} is duplicated")
        seen.add(pair)
        coordinator_decision = str(row.get("coordinator_decision") or "").strip()
        verifier_decision = str(row.get("verifier_decision") or "").strip()
        coordinator_reason = str(row.get("coordinator_reason") or "").strip()
        verifier_reason = str(row.get("verifier_reason") or "").strip()
        if coordinator_decision not in {"consider", "exclude"}:
            problems.append(f"{label}.coordinator_decision is missing or unknown")
        if verifier_decision not in {"used", "unreconciled", "exclude"}:
            problems.append(f"{label}.verifier_decision is missing or unknown")
        if not _substantive_explanation(coordinator_reason):
            problems.append(
                f"{label}.coordinator_reason is missing or not substantive")
        if not _substantive_explanation(verifier_reason):
            problems.append(f"{label}.verifier_reason is missing or not substantive")
        planned = plan_by_pair.get(pair)
        if planned is not None and (
            coordinator_decision != planned.get("decision")
            or coordinator_reason != planned.get("reason")
        ):
            problems.append(
                f"source/claim pair {source_id!r}/{claim_id!r} does not preserve "
                "the coordinator source plan")
        assessment_ids = _listed_ids(
            row.get("assessment_ids"), f"{label}.assessment_ids", problems,
            allow_empty=coordinator_decision == "exclude")
        if coordinator_decision == "exclude":
            if verifier_decision != "exclude":
                problems.append(
                    f"source/claim pair {source_id!r}/{claim_id!r} has unresolved "
                    "coordinator/verifier disagreement")
            if assessment_ids:
                problems.append(f"{label}.assessment_ids must be empty when excluded")
        else:
            if verifier_decision == "exclude":
                problems.append(
                    f"source/claim pair {source_id!r}/{claim_id!r} has unresolved "
                    "coordinator/verifier disagreement")
            if not assessment_ids:
                problems.append(
                    f"considered source/claim pair {source_id!r}/{claim_id!r} has no assessment")
        for assessment_id in assessment_ids:
            assessment = assessment_by_id.get(assessment_id)
            if assessment is None:
                problems.append(
                    f"{label}.assessment_ids references unknown assessment {assessment_id!r}")
                continue
            if str(assessment.get("claim_id") or "") != claim_id:
                problems.append(
                    f"assessment {assessment_id!r} does not belong to claim {claim_id!r}")
            if str(assessment.get("source_id") or "") != source_id:
                problems.append(
                    f"assessment {assessment_id!r} does not cite source {source_id!r}")
            effect = str(assessment.get("effect") or "")
            if verifier_decision == "unreconciled" and effect != "unreconciled":
                problems.append(
                    f"source/claim pair {source_id!r}/{claim_id!r} verifier decision "
                    "unreconciled does not match its assessment effect")
            if verifier_decision == "used" and effect == "unreconciled":
                problems.append(
                    f"source/claim pair {source_id!r}/{claim_id!r} verifier decision "
                    "used does not match its assessment effect")
        check = check_by_claim.get(claim_id) or {}
        receipt = check.get("public_receipt") if isinstance(check, dict) else {}
        cited_source = str(
            (receipt or {}).get("source_id") if isinstance(receipt, dict) else ""
        ).strip()
        check_assessment_ids = {
            str(value or "").strip() for value in check.get("assessment_ids") or []
        } if isinstance(check, dict) else set()
        if cited_source == source_id and verifier_decision != "used":
            problems.append(
                f"accepted check for claim {claim_id!r} cites source {source_id!r} "
                "without a used source/claim pair")
        if cited_source == source_id and not set(assessment_ids) <= check_assessment_ids:
            problems.append(
                f"accepted check for claim {claim_id!r} omits cited source assessment ids")
        accepted.append({
            "source_id": source_id,
            "claim_id": claim_id,
            "coordinator_decision": coordinator_decision,
            "coordinator_reason": coordinator_reason,
            "verifier_decision": verifier_decision,
            "verifier_reason": verifier_reason,
            "assessment_ids": assessment_ids,
        })
    expected_pairs = {
        (source_id, claim_id)
        for source_id in source_ids for claim_id in material_claim_ids
    }
    problems.extend(validate_source_plan_coverage(
        list(plan_by_pair.values()), sources, claims))
    for source_id, claim_id in sorted(expected_pairs - seen):
        problems.append(f"source/claim pair {source_id!r}/{claim_id!r} is missing")
    return accepted, list(dict.fromkeys(problems))


def validate_source_plan_coverage(raw, sources: list[dict], claims: list[dict]
                                  ) -> list[str]:
    """Validate the coordinator's declared source/material-claim pair coverage."""
    source_ids = {
        str(row.get("id") or "").strip() for row in sources
        if isinstance(row, dict) and str(row.get("id") or "").strip()
    }
    material_claim_ids = {
        str(row.get("id") or "").strip() for row in claims
        if isinstance(row, dict)
        and row.get("classification") == "material_claim"
        and str(row.get("id") or "").strip()
    }
    expected_pairs = {
        (source_id, claim_id)
        for source_id in source_ids for claim_id in material_claim_ids
    }
    declared_pairs = {
        (
            str(row.get("source_id") or "").strip(),
            str(row.get("claim_id") or "").strip(),
        )
        for row in raw or [] if isinstance(row, dict)
    }
    problems: list[str] = []
    for source_id, claim_id in sorted(expected_pairs - declared_pairs):
        problems.append(
            f"coordinator source/claim plan {source_id!r}/{claim_id!r} is missing")
    for source_id, claim_id in sorted(declared_pairs - expected_pairs):
        problems.append(
            f"coordinator source/claim plan {source_id!r}/{claim_id!r} does not "
            "name a retained source and material canonical claim")
    return problems


def _operand_problem(raw, prefix: str) -> tuple[dict | None, list[str]]:
    problems: list[str] = []
    if not isinstance(raw, dict):
        return None, [f"{prefix} is not an object"]
    unknown = sorted(set(raw) - {"label", "value", "location"})
    if unknown:
        problems.append(f"{prefix} has unknown field {unknown[0]!r}")
    label = str(raw.get("label") or "").strip()
    location = str(raw.get("location") or "").strip()
    value = raw.get("value")
    label_problem = _public_text_problem(label, operand_label=True)
    if label_problem:
        problems.append(f"{prefix}.label {label_problem}")
    location_problem = _public_text_problem(location)
    if location_problem:
        problems.append(f"{prefix}.location {location_problem}")
    if value in (None, "") or isinstance(value, (bool, dict, list)):
        problems.append(f"{prefix}.value is missing")
    elif isinstance(value, str):
        value_problem = _public_text_problem(value)
        if value_problem:
            problems.append(f"{prefix}.value {value_problem}")
    return {"label": label, "value": value, "location": location}, problems


def _value_in(value, candidates: list) -> bool:
    for candidate in candidates:
        if values_equal(value, candidate):
            return True
        if isinstance(value, str) and isinstance(candidate, str):
            if normalize(value) == normalize(candidate):
                return True
    return False


def _rounded_public_value(value, decimal_places: int,
                          rounding: str) -> tuple[Decimal | None, str | None]:
    """Apply only the host-declared numeric display rule and preserve public units."""
    number = public_number(value)
    if number is None:
        return None, None
    quantum = Decimal(1).scaleb(-decimal_places)
    try:
        rounded = number.quantize(quantum, rounding=ROUNDING_MODES[rounding])
    except InvalidOperation:
        return None, None
    original = str(value).strip()
    prefix = "$" if original.startswith("$") else ""
    suffix_match = re.search(
        r"(%|percent(?:age)?(?:\s+points?)?|points?|bps|basis\s+points?)\s*$",
        original,
        re.I,
    )
    suffix = suffix_match.group(1) if suffix_match else ""
    grouped = "," in original or bool(prefix)
    number_text = (
        f"{rounded:,.{decimal_places}f}"
        if grouped else f"{rounded:.{decimal_places}f}"
    )
    spacer = "" if suffix == "%" or not suffix else " "
    return rounded, f"{prefix}{number_text}{spacer}{suffix}"


def validate_numeric_comparison(finding: dict, report_operand: dict | None,
                                calculation: dict | None
                                ) -> tuple[dict | None, list[str]]:
    """Validate a host-selected comparison rule without selecting precision."""
    applicable = (
        finding.get("basis") == "report"
        and finding.get("type") == "arithmetic"
        and finding.get("verdict") in {"confirmed", "contradicted"}
    )
    raw = finding.get("numeric_comparison")
    if not applicable:
        if raw is not None:
            return None, [
                "numeric_comparison is allowed only for confirmed or contradicted "
                "report-basis arithmetic"
            ]
        return None, []
    if not isinstance(raw, dict):
        return None, [
            "numeric_comparison is required for numeric report-basis arithmetic"
        ]
    mode = str(raw.get("mode") or "").strip()
    problems: list[str] = []
    canonical: dict = {"mode": mode}
    if mode == "rounded":
        unknown = sorted(set(raw) - {"mode", "rounding", "decimal_places"})
        if unknown:
            problems.append(
                f"numeric_comparison has unknown field {unknown[0]!r}")
        rounding = str(raw.get("rounding") or "").strip()
        decimal_places = raw.get("decimal_places")
        if rounding not in ROUNDING_MODES:
            problems.append("numeric_comparison.rounding is missing or unknown")
        if (
            isinstance(decimal_places, bool)
            or not isinstance(decimal_places, int)
            or not 0 <= decimal_places <= 12
        ):
            problems.append(
                "numeric_comparison.decimal_places must be an integer from 0 through 12")
        canonical.update({
            "rounding": rounding,
            "decimal_places": decimal_places,
        })
    elif mode == "absolute_tolerance":
        unknown = sorted(set(raw) - {"mode", "tolerance"})
        if unknown:
            problems.append(
                f"numeric_comparison has unknown field {unknown[0]!r}")
        tolerance = public_number(raw.get("tolerance"))
        if tolerance is None or tolerance < 0:
            problems.append(
                "numeric_comparison.tolerance must be a non-negative public numeric value")
        canonical["tolerance"] = raw.get("tolerance")
    else:
        problems.append("numeric_comparison.mode is missing or unknown")

    report_value = public_number(
        report_operand.get("value") if isinstance(report_operand, dict) else None)
    result_value = public_number(
        calculation.get("result") if isinstance(calculation, dict) else None)
    if report_value is None or result_value is None:
        problems.append(
            "numeric_comparison requires a numeric report operand and calculation result")
    if problems:
        return None, problems

    if mode == "rounded":
        report_compared, _report_display = _rounded_public_value(
            report_operand["value"], canonical["decimal_places"], canonical["rounding"])
        result_compared, customer_result = _rounded_public_value(
            calculation["result"], canonical["decimal_places"], canonical["rounding"])
        if report_compared is None or result_compared is None or customer_result is None:
            return None, [
                "numeric_comparison rounded values cannot be represented at the "
                "declared decimal_places"
            ]
        matches = report_compared == result_compared
        canonical["customer_result"] = customer_result
    else:
        matches = abs(report_value - result_value) <= public_number(
            canonical["tolerance"])
    canonical["matches"] = matches
    verdict = finding.get("verdict")
    if verdict == "confirmed" and not matches:
        problems.append(
            "confirmed report-basis arithmetic values differ under the declared "
            "numeric comparison")
    if verdict == "contradicted" and matches:
        problems.append(
            "contradicted report-basis arithmetic values match under the declared "
            "numeric comparison")
    return (None if problems else canonical), problems


def _validate_public_receipt(finding: dict, report: str,
                             receipt_updates: dict,
                             sources: dict[str, dict],
                             claim_label: str, *,
                             explicit_operand_values: list | None = None
                             ) -> tuple[dict | None, list[str]]:
    raw = finding.get("public_receipt")
    if not isinstance(raw, dict):
        return None, ["public_receipt is missing or not an object"]
    problems: list[str] = []
    allowed = {
        "report_operand", "decisive_operands", "explanation",
        "calculation", "source_id", "reconstruction_attempt",
    }
    unknown = sorted(set(raw) - allowed)
    if unknown:
        problems.append(f"public_receipt has unknown field {unknown[0]!r}")
    report_operand, report_problems = _operand_problem(
        raw.get("report_operand"), "public_receipt.report_operand")
    problems.extend(report_problems)
    if report_operand is not None and report_operand.get("label") != claim_label:
        problems.append(
            "public_receipt.report_operand.label does not match claim public_label")
    decisive_raw = raw.get("decisive_operands")
    decisive: list[dict] = []
    verdict = str(finding.get("verdict") or "")
    if decisive_raw is None and verdict == "not_checkable":
        decisive_raw = []
    if not isinstance(decisive_raw, list):
        problems.append("public_receipt.decisive_operands is not an array")
    elif verdict == "not_checkable" and decisive_raw:
        problems.append("public_receipt.decisive_operands must be empty for not_checkable")
    elif verdict != "not_checkable" and not decisive_raw:
        problems.append("public_receipt.decisive_operands is missing or empty")
    if isinstance(decisive_raw, list):
        for index, operand in enumerate(decisive_raw):
            canonical, operand_problems = _operand_problem(
                operand, f"public_receipt.decisive_operands[{index}]")
            problems.extend(operand_problems)
            if canonical is not None:
                decisive.append(canonical)
    explanation = str(raw.get("explanation") or "").strip()
    if not _substantive_explanation(explanation):
        problems.append("public_receipt.explanation is missing or not substantive")
    reconstruction = str(raw.get("reconstruction_attempt") or "").strip()
    if verdict == "changed_since_report":
        if not _substantive_explanation(reconstruction):
            problems.append(
                "public_receipt.reconstruction_attempt is missing or not substantive")
        elif reconstruction != str(finding.get("reconstruction_attempt") or "").strip():
            problems.append(
                "public_receipt.reconstruction_attempt does not match the check")
    elif reconstruction:
        problems.append(
            "public_receipt.reconstruction_attempt is only allowed for changed_since_report")
    basis = str(finding.get("basis") or "")
    source_id = str(raw.get("source_id") or "").strip()
    source = sources.get(source_id)
    if basis == "evidence":
        if not source_id:
            problems.append("public_receipt.source_id is required for evidence basis")
        elif source is None:
            problems.append(f"public_receipt.source_id {source_id!r} is not retained")
    elif basis == "report" and source_id:
        problems.append("public_receipt.source_id is not allowed for report basis")
    report_quote = str(finding.get("report_quote") or "")
    if report_operand is not None and report_operand.get("value") not in (None, ""):
        if not explicit_value_in_quote(report_operand["value"], report_quote):
            problems.append(
                "public_receipt.report_operand.value is not visible in report_quote")
    resolved = _resolved_receipt_values(finding, receipt_updates)
    evidence_quote = str(
        receipt_updates.get("evidence_quote")
        or finding.get("evidence_quote")
        or ""
    )
    for index, operand in enumerate(decisive):
        value = operand.get("value")
        grounded = False
        if basis == "evidence":
            grounded = _value_in(value, resolved)
            if not grounded and evidence_quote:
                grounded = explicit_value_in_quote(value, evidence_quote)
            if verdict == "changed_since_report" and not grounded:
                report_day = str(finding.get("report_date") or "")
                current_day = str(finding.get("current_as_of") or "")
                date_receipt = receipt_updates.get("date_receipt") or {}
                if values_equal(value, report_day):
                    grounded = explicit_value_in_quote(value, report_quote)
                elif values_equal(value, current_day):
                    grounded = bool(date_receipt)
        else:
            grounded = explicit_value_in_quote(value, report_quote) or _value_in(
                value, list(explicit_operand_values or []))
        if not grounded:
            problems.append(
                f"public_receipt.decisive_operands[{index}].value is not grounded"
            )
    calculation = raw.get("calculation")
    canonical_calculation = None
    if verdict == "not_checkable" and calculation is not None:
        problems.append("public_receipt.calculation is not allowed for not_checkable")
    if calculation is not None:
        if not isinstance(calculation, dict):
            problems.append("public_receipt.calculation is not an object")
        else:
            unknown_calc = sorted(set(calculation) - {"expression", "result"})
            if unknown_calc:
                problems.append(
                    f"public_receipt.calculation has unknown field {unknown_calc[0]!r}")
            expression = str(calculation.get("expression") or "").strip()
            result = calculation.get("result")
            expression_problem = _public_text_problem(expression)
            if expression_problem:
                problems.append(f"public_receipt.calculation.expression {expression_problem}")
            numeric_result = public_number(result)
            if result in (None, "") or isinstance(result, bool):
                problems.append("public_receipt.calculation.result is missing")
            elif isinstance(result, str):
                result_problem = _public_text_problem(result)
                if result_problem:
                    problems.append(f"public_receipt.calculation.result {result_problem}")
            if result not in (None, "") and numeric_result is None:
                problems.append(
                    "public_receipt.calculation.result is not a public numeric value")
            math_problem = None
            if (
                not expression_problem
                and result not in (None, "")
                and numeric_result is not None
            ):
                math_problem = calculation_problem(expression, result, decisive)
                if math_problem:
                    problems.append(f"public_receipt.{math_problem}")
            canonical_calculation = {"expression": expression, "result": result}
    numeric_comparison, comparison_problems = validate_numeric_comparison(
        finding, report_operand, canonical_calculation)
    problems.extend(comparison_problems)
    if numeric_comparison is not None:
        finding["numeric_comparison"] = numeric_comparison
    if (
        verdict != "not_checkable"
        and basis == "report"
        and canonical_calculation is None
        and report_operand is not None
        and decisive
        and all(values_equal(
            operand.get("value"), report_operand.get("value")
        ) for operand in decisive)
    ):
        problems.append(
            "public_receipt repeats the report operand without a decisive calculation or distinct operand"
        )
    canonical = {
        "report_operand": report_operand,
        "decisive_operands": decisive,
        "explanation": explanation,
    }
    if canonical_calculation is not None:
        canonical["calculation"] = canonical_calculation
    if source_id:
        canonical["source_id"] = source_id
    if reconstruction:
        canonical["reconstruction_attempt"] = reconstruction
    return (None if problems else canonical), problems


def validate_claims(report: str, proposed: list) -> tuple[list, list]:
    grounded, discarded = [], []
    seen = set()
    if not isinstance(proposed, list):
        return [], [{"id": "", "problems": ["claims is not a list"]}]
    for raw in proposed:
        if not isinstance(raw, dict):
            discarded.append({
                "id": "",
                "quote": "",
                "public_label": "",
                "importance": "material",
                "classification": "material_claim",
                "problems": ["claim is not an object"],
            })
            continue
        claim = raw
        problems = []
        cid = str(claim.get("id") or "").strip()
        quote = claim.get("quote", "")
        public_label = str(claim.get("public_label") or "").strip()
        importance = claim.get("importance")
        classification = str(claim.get("classification") or "").strip()
        reason = str(claim.get("reason") or "").strip()
        if not cid:
            problems.append("claim has no id")
        elif cid in seen:
            problems.append(f"claim id {cid!r} is duplicated")
        if classification not in CANONICAL_CLAIM_CLASSIFICATIONS:
            problems.append("claim classification is missing or unknown")
        if classification == "supporting_provenance":
            if importance not in {None, "supporting"}:
                problems.append("supporting_provenance requires importance supporting")
            importance = "supporting"
            if not _substantive_explanation(reason):
                problems.append(
                    "supporting_provenance reason is missing or not substantive")
        elif classification == "material_claim":
            if importance != "material":
                problems.append("material_claim requires importance material")
            importance = "material"
        if not quote_in_text(str(quote), report):
            problems.append("claim quote not found in visible report text")
        quote_problem = _public_text_problem(quote)
        if quote_problem:
            problems.append(f"claim quote {quote_problem}")
        label_problem = _public_text_problem(public_label, operand_label=True)
        if label_problem:
            problems.append(f"claim public_label {label_problem}")
        row = {
            "id": cid,
            "quote": quote,
            "public_label": public_label,
            "importance": importance if importance in {"material", "supporting"} else "material",
            "classification": (
                classification if classification in CANONICAL_CLAIM_CLASSIFICATIONS
                else "material_claim"),
        }
        if reason:
            row["reason"] = reason
        ids = claim_inventory_ids(claim)
        if ids:
            row["inventory_ids"] = ids
        elif "inventory_ids" in claim and claim.get("inventory_ids") not in (None, [], ""):
            problems.append("claim inventory_ids is not a list of ids")
        if classification == "supporting_provenance" and len(ids) != 1:
            problems.append("supporting_provenance requires exactly one inventory id")
        if problems:
            discarded.append({**row, "problems": problems})
        else:
            seen.add(cid)
            grounded.append(row)
    return grounded, discarded


def _listed_ids(raw, label: str, problems: list[str], *,
                allow_empty: bool = False) -> list[str]:
    if not isinstance(raw, list) or (not raw and not allow_empty):
        qualifier = "an array" if allow_empty else "a non-empty array"
        problems.append(f"{label} is missing or not {qualifier}")
        return []
    out = [str(value or "").strip() for value in raw]
    if any(not value for value in out):
        problems.append(f"{label} contains an empty id")
    if len(out) != len(set(out)):
        problems.append(f"{label} contains a duplicate id")
    return [value for value in out if value]


def _public_literal_in(value, text) -> bool:
    literal = normalize(str(value or ""))
    return bool(literal) and literal in normalize(str(text or ""))


def validate_coordinator_handoff(canonical_claims, coordinator,
                                 inventory: dict) -> tuple[dict, list[str]]:
    """Validate coordinator-v6 declarations by opaque IDs and exact spans only."""
    handoff = {
        "classification_reviews": [],
        "structural_context": [],
        "material_claim_ids": [],
        "material_claim_clause_ids": {},
        "material_claim_inventory_ids": {},
        "material_inventory_claim_ids": {},
        "verifier_assignments": [],
        "claim_dependencies": [],
        "claim_ancestors": {},
        "topological_claim_ids": [],
        "population_requirements": {},
        "source_consideration_plan": [],
    }
    problems: list[str] = []
    if not isinstance(canonical_claims, list):
        return handoff, ["canonical claims are not an array"]
    if not isinstance(coordinator, dict):
        return handoff, ["coordinator handoff is missing or not an object"]
    partitions = coordinator.get("partition_results")
    reviews = coordinator.get("classification_reviews")
    verifier_assignments = coordinator.get("verifier_assignments")
    dependencies = coordinator.get("claim_dependencies")
    source_plan = coordinator.get("source_consideration_plan")
    if not isinstance(partitions, list):
        problems.append("coordinator.partition_results is not an array")
        partitions = []
    if not isinstance(reviews, list):
        problems.append("coordinator.classification_reviews is not an array")
        reviews = []
    if not isinstance(verifier_assignments, list):
        problems.append("coordinator.verifier_assignments is not an array")
        verifier_assignments = []
    if not isinstance(dependencies, list):
        problems.append("coordinator.claim_dependencies is not an array")
        dependencies = []
    if not isinstance(source_plan, list):
        problems.append("coordinator.source_consideration_plan is not an array")
        source_plan = []

    inventory_rows = [
        row for row in (inventory.get("items") or [])
        if isinstance(row, dict) and row.get("id")
    ] if isinstance(inventory, dict) else []
    inventory_by_id = {str(row["id"]): row for row in inventory_rows}
    if len(inventory_by_id) != len(inventory_rows):
        problems.append("inventory ids are duplicated")

    decisions: dict[str, dict] = {}
    clauses: dict[str, dict] = {}
    partition_ids: set[str] = set()
    for partition_index, partition in enumerate(partitions):
        label = f"coordinator.partition_results[{partition_index}]"
        if not isinstance(partition, dict):
            problems.append(f"{label} is not an object")
            continue
        partition_id = str(partition.get("partition_id") or "").strip()
        if not partition_id:
            problems.append(f"{label}.partition_id is missing")
            continue
        if partition_id in partition_ids:
            problems.append(f"partition id {partition_id!r} is duplicated")
        partition_ids.add(partition_id)
        raw_decisions = partition.get("occurrence_decisions")
        raw_clauses = partition.get("clauses")
        if not isinstance(raw_decisions, list):
            problems.append(f"{label}.occurrence_decisions is not an array")
            raw_decisions = []
        if not isinstance(raw_clauses, list):
            problems.append(f"{label}.clauses is not an array")
            raw_clauses = []
        partition_decisions: dict[str, dict] = {}
        for decision_index, decision in enumerate(raw_decisions):
            decision_label = f"{label}.occurrence_decisions[{decision_index}]"
            if not isinstance(decision, dict):
                problems.append(f"{decision_label} is not an object")
                continue
            unknown = sorted(set(decision) - {
                "occurrence_id", "classification", "reason", "clause_ids",
            })
            if unknown:
                problems.append(
                    f"{decision_label} has unknown field {unknown[0]!r}")
            occurrence_id = str(decision.get("occurrence_id") or "").strip()
            if not occurrence_id:
                problems.append(f"{decision_label}.occurrence_id is missing")
                continue
            if occurrence_id not in inventory_by_id:
                problems.append(
                    f"{decision_label}.occurrence_id {occurrence_id!r} is not in the inventory")
            if occurrence_id in decisions:
                problems.append(
                    f"inventory occurrence {occurrence_id!r} has more than one claim-taker decision")
            classification = str(decision.get("classification") or "").strip()
            if classification not in CLAIM_CLASSIFICATIONS:
                problems.append(
                    f"claim-taker decision for occurrence {occurrence_id!r} "
                    "classification is missing or unknown")
            reason = str(decision.get("reason") or "").strip()
            if not _substantive_explanation(reason):
                problems.append(
                    f"claim-taker decision for occurrence {occurrence_id!r} "
                    "reason is missing or not substantive")
            clause_ids = _listed_ids(
                decision.get("clause_ids"),
                f"claim-taker decision for occurrence {occurrence_id!r} clause_ids",
                problems,
                allow_empty=classification != "material_claim",
            )
            if classification != "material_claim" and clause_ids:
                problems.append(
                    f"nonmaterial claim-taker decision for occurrence {occurrence_id!r} "
                    "must not declare clauses")
            clean = {
                "occurrence_id": occurrence_id,
                "classification": classification,
                "reason": reason,
                "clause_ids": clause_ids,
                "partition_id": partition_id,
            }
            decisions[occurrence_id] = clean
            partition_decisions[occurrence_id] = clean

        partition_clause_ids: set[str] = set()
        for clause_index, clause in enumerate(raw_clauses):
            clause_label = f"{label}.clauses[{clause_index}]"
            if not isinstance(clause, dict):
                problems.append(f"{clause_label} is not an object")
                continue
            unknown = sorted(set(clause) - {
                "id", "occurrence_id", "span", "quote", "public_label",
                "context_occurrence_ids",
            })
            if unknown:
                problems.append(f"{clause_label} has unknown field {unknown[0]!r}")
            clause_id = str(clause.get("id") or "").strip()
            occurrence_id = str(clause.get("occurrence_id") or "").strip()
            if not clause_id:
                problems.append(f"{clause_label}.id is missing")
                continue
            if clause_id in clauses or clause_id in partition_clause_ids:
                problems.append(f"material clause id {clause_id!r} is duplicated")
            partition_clause_ids.add(clause_id)
            decision = partition_decisions.get(occurrence_id)
            if decision is None:
                problems.append(
                    f"material clause {clause_id!r} references occurrence "
                    f"{occurrence_id!r} without a decision in partition {partition_id!r}")
            elif decision.get("classification") != "material_claim":
                problems.append(
                    f"material clause {clause_id!r} belongs to nonmaterial occurrence "
                    f"{occurrence_id!r}")
            span = clause.get("span")
            start = span.get("start") if isinstance(span, dict) else None
            end = span.get("end") if isinstance(span, dict) else None
            shown = normalize_visible(
                str((inventory_by_id.get(occurrence_id) or {}).get("displayed") or ""))
            quote = str(clause.get("quote") or "")
            if (
                isinstance(start, bool) or isinstance(end, bool)
                or not isinstance(start, int) or not isinstance(end, int)
                or start < 0 or end <= start or end > len(shown)
            ):
                problems.append(f"material clause {clause_id!r} span is invalid")
            elif shown[start:end] != quote:
                problems.append(
                    f"material clause {clause_id!r} quote does not equal its exact span")
            quote_problem = _public_text_problem(quote)
            if quote_problem:
                problems.append(f"material clause {clause_id!r} quote {quote_problem}")
            public_label = str(clause.get("public_label") or "").strip()
            label_problem = _public_text_problem(public_label, operand_label=True)
            if label_problem:
                problems.append(
                    f"material clause {clause_id!r} public_label {label_problem}")
            context_ids = _listed_ids(
                clause.get("context_occurrence_ids"),
                f"material clause {clause_id!r} context_occurrence_ids",
                problems, allow_empty=True)
            for context_id in context_ids:
                if context_id not in inventory_by_id:
                    problems.append(
                        f"material clause {clause_id!r} references unknown context "
                        f"occurrence {context_id!r}")
            clauses[clause_id] = {
                "id": clause_id,
                "occurrence_id": occurrence_id,
                "span": {"start": start, "end": end},
                "quote": quote,
                "public_label": public_label,
                "context_occurrence_ids": context_ids,
                "partition_id": partition_id,
            }
        for occurrence_id, decision in partition_decisions.items():
            actual = {
                clause_id for clause_id, clause in clauses.items()
                if clause.get("partition_id") == partition_id
                and clause.get("occurrence_id") == occurrence_id
            }
            if set(decision["clause_ids"]) != actual:
                problems.append(
                    f"claim-taker decision for occurrence {occurrence_id!r} clause_ids "
                    "do not match its material clauses")

    for occurrence_id in inventory_by_id:
        if occurrence_id not in decisions:
            problems.append(
                f"inventory occurrence {occurrence_id!r} has no claim-taker decision")

    final_classification: dict[str, str] = {}
    accepted_clause_ids: set[str] = set()
    seen_reviews: set[str] = set()
    for index, review in enumerate(reviews):
        label = f"coordinator.classification_reviews[{index}]"
        if not isinstance(review, dict):
            problems.append(f"{label} is not an object")
            continue
        unknown = sorted(set(review) - {
            "occurrence_id", "claim_taker_partition_id", "proposed_classification",
            "final_classification", "decision", "reason", "accepted_clause_ids",
        })
        if unknown:
            problems.append(f"{label} has unknown field {unknown[0]!r}")
        occurrence_id = str(review.get("occurrence_id") or "").strip()
        if not occurrence_id:
            problems.append(f"{label}.occurrence_id is missing")
            continue
        if occurrence_id in seen_reviews:
            problems.append(
                f"inventory occurrence {occurrence_id!r} has more than one coordinator classification review")
        seen_reviews.add(occurrence_id)
        proposal = decisions.get(occurrence_id)
        if proposal is None:
            problems.append(
                f"coordinator classification review references unknown occurrence {occurrence_id!r}")
            continue
        partition_id = str(review.get("claim_taker_partition_id") or "").strip()
        proposed = str(review.get("proposed_classification") or "").strip()
        final = str(review.get("final_classification") or "").strip()
        decision = str(review.get("decision") or "").strip()
        if partition_id != proposal.get("partition_id"):
            problems.append(
                f"coordinator classification review for occurrence {occurrence_id!r} "
                "does not name its claim-taker partition")
        if proposed != proposal.get("classification"):
            problems.append(
                f"coordinator classification review for occurrence {occurrence_id!r} "
                "does not preserve the claim-taker proposal")
        if final not in CLAIM_CLASSIFICATIONS:
            problems.append(
                f"coordinator classification review for occurrence {occurrence_id!r} "
                "final_classification is missing or unknown")
        reason = str(review.get("reason") or "").strip()
        if not _substantive_explanation(reason):
            problems.append(
                f"coordinator classification review for occurrence {occurrence_id!r} "
                "reason is missing or not substantive")
        review_clause_ids = _listed_ids(
            review.get("accepted_clause_ids"),
            f"coordinator classification review for occurrence {occurrence_id!r} "
            "accepted_clause_ids",
            problems, allow_empty=final != "material_claim")
        if decision == "challenge":
            problems.append(
                f"coordinator classification review for occurrence {occurrence_id!r} "
                "is an unresolved challenge")
        elif decision == "accept":
            if proposed != final:
                if proposed != "material_claim" and final == "material_claim":
                    problems.append(
                        f"coordinator classification review for occurrence {occurrence_id!r} "
                        "cannot promote a nonmaterial proposal without a claim-taker clause")
                else:
                    problems.append(
                        f"coordinator classification review for occurrence {occurrence_id!r} "
                        "accept must preserve the proposed classification")
        elif decision == "demote":
            if proposed != "material_claim" or final == "material_claim":
                problems.append(
                    f"coordinator classification review for occurrence {occurrence_id!r} "
                    "demote must change a material proposal to a nonmaterial class")
        else:
            problems.append(
                f"coordinator classification review for occurrence {occurrence_id!r} "
                "decision is missing or unknown")
        expected_clauses = set(proposal.get("clause_ids") or [])
        if final == "material_claim" and set(review_clause_ids) != expected_clauses:
            problems.append(
                f"coordinator classification review for occurrence {occurrence_id!r} "
                "accepted_clause_ids do not match the claim-taker material clauses")
        if final != "material_claim" and review_clause_ids:
            problems.append(
                f"coordinator classification review for occurrence {occurrence_id!r} "
                "nonmaterial classification must not accept material clauses")
        final_classification[occurrence_id] = final
        if final == "material_claim":
            accepted_clause_ids.update(review_clause_ids)
        elif final == "structural_context":
            item = inventory_by_id.get(occurrence_id) or {}
            handoff["structural_context"].append({
                "id": f"structural:{occurrence_id}",
                "partition_id": proposal.get("partition_id"),
                "occurrence_id": occurrence_id,
                "quote": item.get("displayed"),
                "classification": "structural_context",
                "importance": "supporting",
                "reason": reason,
                "inventory_ids": [occurrence_id],
            })
        handoff["classification_reviews"].append({
            "occurrence_id": occurrence_id,
            "claim_taker_partition_id": partition_id,
            "proposed_classification": proposed,
            "final_classification": final,
            "decision": decision,
            "reason": reason,
            "accepted_clause_ids": review_clause_ids,
        })
    for occurrence_id in inventory_by_id:
        if occurrence_id not in seen_reviews:
            problems.append(
                f"inventory occurrence {occurrence_id!r} has no coordinator classification review")

    canonical_by_id: dict[str, dict] = {}
    for index, claim in enumerate(canonical_claims):
        if not isinstance(claim, dict):
            problems.append(f"canonical claims[{index}] is not an object")
            continue
        claim_id = str(claim.get("id") or "").strip()
        if not claim_id:
            problems.append(f"canonical claims[{index}].id is missing")
            continue
        if claim_id in canonical_by_id:
            problems.append(f"canonical claim id {claim_id!r} is duplicated")
            continue
        canonical_by_id[claim_id] = claim

    clause_owners: dict[str, list[str]] = {}
    supporting_owners: dict[str, list[str]] = {}
    requirement_ids: set[str] = set()
    for claim_id, claim in canonical_by_id.items():
        classification = str(claim.get("classification") or "").strip()
        if classification not in CANONICAL_CLAIM_CLASSIFICATIONS:
            problems.append(
                f"canonical claim {claim_id!r} classification is missing or unknown")
        if classification == "material_claim":
            member_clause_ids = _listed_ids(
                claim.get("member_clause_ids"),
                f"canonical claim {claim_id!r} member_clause_ids", problems)
            primary_clause_id = str(claim.get("primary_clause_id") or "").strip()
            if primary_clause_id not in member_clause_ids:
                problems.append(
                    f"canonical claim {claim_id!r} primary_clause_id is not a member")
            member_occurrences: list[str] = []
            for clause_id in member_clause_ids:
                clause = clauses.get(clause_id)
                if clause is None:
                    problems.append(
                        f"canonical claim {claim_id!r} references unknown material "
                        f"clause {clause_id!r}")
                    continue
                occurrence_id = str(clause.get("occurrence_id") or "")
                if clause_id not in accepted_clause_ids:
                    problems.append(
                        f"canonical claim {claim_id!r} uses clause {clause_id!r} "
                        "that was not accepted by classification review")
                member_occurrences.append(occurrence_id)
                clause_owners.setdefault(clause_id, []).append(claim_id)
            declared_occurrences = _listed_ids(
                claim.get("occurrence_ids"),
                f"canonical claim {claim_id!r} occurrence_ids", problems)
            expected_occurrences = list(dict.fromkeys(member_occurrences))
            if (
                set(declared_occurrences) != set(expected_occurrences)
                or len(declared_occurrences) != len(expected_occurrences)
            ):
                problems.append(
                    f"canonical claim {claim_id!r} occurrence_ids do not match its clauses")
            inventory_ids = _listed_ids(
                claim.get("inventory_ids"),
                f"canonical claim {claim_id!r} inventory_ids", problems)
            if inventory_ids != declared_occurrences:
                problems.append(
                    f"canonical claim {claim_id!r} inventory_ids do not match occurrence_ids")
            primary = clauses.get(primary_clause_id) or {}
            if str(claim.get("primary_quote") or "") != str(primary.get("quote") or ""):
                problems.append(
                    f"canonical claim {claim_id!r} primary_quote does not match its primary clause")
            if str(claim.get("quote") or "") != str(claim.get("primary_quote") or ""):
                problems.append(
                    f"canonical claim {claim_id!r} public quote does not match primary_quote")
            if str(claim.get("public_label") or "").strip() != str(
                primary.get("public_label") or ""
            ).strip():
                problems.append(
                    f"canonical claim {claim_id!r} public_label is not carried from its primary clause")
            context_ids = _listed_ids(
                claim.get("context_occurrence_ids"),
                f"canonical claim {claim_id!r} context_occurrence_ids",
                problems, allow_empty=True)
            for context_id in context_ids:
                if context_id not in inventory_by_id:
                    problems.append(
                        f"canonical claim {claim_id!r} references unknown context "
                        f"occurrence {context_id!r}")
            raw_requirements = claim.get("population_requirements")
            if not isinstance(raw_requirements, list):
                problems.append(
                    f"canonical claim {claim_id!r} population_requirements is not an array")
                raw_requirements = []
            clean_requirements: list[dict] = []
            for index, requirement in enumerate(raw_requirements):
                label = f"canonical claim {claim_id!r} population_requirements[{index}]"
                if not isinstance(requirement, dict):
                    problems.append(f"{label} is not an object")
                    continue
                requirement_id = str(requirement.get("id") or "").strip()
                dimension = str(requirement.get("dimension") or "").strip()
                report_quote = str(requirement.get("report_quote") or "").strip()
                if not requirement_id:
                    problems.append(f"{label}.id is missing")
                elif requirement_id in requirement_ids:
                    problems.append(
                        f"population requirement id {requirement_id!r} is duplicated")
                requirement_ids.add(requirement_id)
                if dimension not in POPULATION_DIMENSIONS:
                    problems.append(f"{label}.dimension is missing or unknown")
                quote_problem = _public_text_problem(report_quote)
                if quote_problem:
                    problems.append(f"{label}.report_quote {quote_problem}")
                clean_requirements.append({
                    "id": requirement_id,
                    "dimension": dimension,
                    "report_quote": report_quote,
                })
            handoff["material_claim_ids"].append(claim_id)
            handoff["material_claim_inventory_ids"][claim_id] = declared_occurrences
            handoff["material_claim_clause_ids"][claim_id] = member_clause_ids
            handoff["population_requirements"][claim_id] = clean_requirements
        elif classification == "supporting_provenance":
            occurrences = _listed_ids(
                claim.get("occurrence_ids"),
                f"canonical claim {claim_id!r} occurrence_ids", problems)
            if len(occurrences) != 1:
                problems.append(
                    f"canonical claim {claim_id!r} supporting_provenance requires exactly one occurrence")
            for occurrence_id in occurrences:
                if final_classification.get(occurrence_id) != "supporting_provenance":
                    problems.append(
                        f"canonical claim {claim_id!r} occurrence {occurrence_id!r} "
                        "was not accepted as supporting_provenance")
                supporting_owners.setdefault(occurrence_id, []).append(claim_id)
            inventory_ids = _listed_ids(
                claim.get("inventory_ids"),
                f"canonical claim {claim_id!r} inventory_ids", problems)
            if inventory_ids != occurrences:
                problems.append(
                    f"canonical claim {claim_id!r} inventory_ids do not match occurrence_ids")
            if not _substantive_explanation(claim.get("reason")):
                problems.append(
                    f"canonical claim {claim_id!r} supporting_provenance reason "
                    "is missing or not substantive")

    for clause_id in sorted(accepted_clause_ids):
        owners = clause_owners.get(clause_id) or []
        if not owners:
            problems.append(
                f"accepted material clause {clause_id!r} has no canonical claim")
        elif len(owners) > 1:
            problems.append(
                f"material clause {clause_id!r} belongs to more than one canonical claim")
    for occurrence_id, classification in final_classification.items():
        if classification != "supporting_provenance":
            continue
        owners = supporting_owners.get(occurrence_id) or []
        if not owners:
            problems.append(
                f"supporting occurrence {occurrence_id!r} has no canonical supporting claim")
        elif len(owners) > 1:
            problems.append(
                f"supporting occurrence {occurrence_id!r} belongs to more than one canonical claim")

    for claim_id, inventory_ids in handoff["material_claim_inventory_ids"].items():
        for inventory_id in inventory_ids:
            handoff["material_inventory_claim_ids"].setdefault(
                inventory_id, []).append(claim_id)

    material_set = set(handoff["material_claim_ids"])
    plan_pairs: set[tuple[str, str]] = set()
    for index, row in enumerate(source_plan):
        label = f"coordinator.source_consideration_plan[{index}]"
        if not isinstance(row, dict):
            problems.append(f"{label} is not an object")
            continue
        unknown = sorted(set(row) - {"source_id", "claim_id", "decision", "reason"})
        if unknown:
            problems.append(f"{label} has unknown field {unknown[0]!r}")
        source_id = str(row.get("source_id") or "").strip()
        claim_id = str(row.get("claim_id") or "").strip()
        decision = str(row.get("decision") or "").strip()
        reason = str(row.get("reason") or "").strip()
        pair = (source_id, claim_id)
        if not source_id:
            problems.append(f"{label}.source_id is missing")
        if claim_id not in material_set:
            problems.append(
                f"{label}.claim_id {claim_id!r} is not a material canonical claim")
        if decision not in {"consider", "exclude"}:
            problems.append(f"{label}.decision is missing or unknown")
        if not _substantive_explanation(reason):
            problems.append(f"{label}.reason is missing or not substantive")
        if pair in plan_pairs:
            problems.append(
                f"coordinator source/claim plan {source_id!r}/{claim_id!r} is duplicated")
        plan_pairs.add(pair)
        handoff["source_consideration_plan"].append({
            "source_id": source_id,
            "claim_id": claim_id,
            "decision": decision,
            "reason": reason,
        })

    dependency_ids: set[str] = set()
    edges: set[tuple[str, str]] = set()
    clean_dependencies: list[dict] = []
    for index, dependency in enumerate(dependencies):
        label = f"coordinator.claim_dependencies[{index}]"
        if not isinstance(dependency, dict):
            problems.append(f"{label} is not an object")
            continue
        dependency_id = str(dependency.get("id") or "").strip()
        upstream = str(dependency.get("upstream_claim_id") or "").strip()
        downstream = str(dependency.get("downstream_claim_id") or "").strip()
        role = str(dependency.get("role") or "").strip()
        reason = str(dependency.get("reason") or "").strip()
        if not dependency_id:
            problems.append(f"{label}.id is missing")
        elif dependency_id in dependency_ids:
            problems.append(f"claim dependency id {dependency_id!r} is duplicated")
        dependency_ids.add(dependency_id)
        if upstream not in material_set:
            problems.append(
                f"claim dependency {dependency_id!r} references unknown upstream claim {upstream!r}")
        if downstream not in material_set:
            problems.append(
                f"claim dependency {dependency_id!r} references unknown downstream claim {downstream!r}")
        if upstream and upstream == downstream:
            problems.append(f"claim dependency {dependency_id!r} is a self dependency")
        if role != "decisive_operand":
            problems.append(
                f"claim dependency {dependency_id!r} role is missing or unknown")
        if not _substantive_explanation(reason):
            problems.append(
                f"claim dependency {dependency_id!r} reason is missing or not substantive")
        edge = (upstream, downstream)
        if edge in edges:
            problems.append(
                f"claim dependency edge {upstream!r}->{downstream!r} is duplicated")
        edges.add(edge)
        clean_dependencies.append({
            "id": dependency_id,
            "upstream_claim_id": upstream,
            "downstream_claim_id": downstream,
            "role": role,
            "reason": reason,
        })

    children: dict[str, set[str]] = {claim_id: set() for claim_id in material_set}
    indegree: dict[str, int] = {claim_id: 0 for claim_id in material_set}
    for upstream, downstream in edges:
        if upstream in material_set and downstream in material_set:
            if downstream not in children[upstream]:
                children[upstream].add(downstream)
                indegree[downstream] += 1
    queue = sorted(claim_id for claim_id, degree in indegree.items() if degree == 0)
    order: list[str] = []
    while queue:
        claim_id = queue.pop(0)
        order.append(claim_id)
        for child in sorted(children[claim_id]):
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)
                queue.sort()
    if len(order) != len(material_set):
        problems.append("claim dependency graph contains a cycle")
    ancestors: dict[str, set[str]] = {claim_id: set() for claim_id in material_set}
    for claim_id in order:
        for child in children.get(claim_id) or set():
            ancestors[child].add(claim_id)
            ancestors[child].update(ancestors[claim_id])
    handoff["claim_dependencies"] = clean_dependencies
    handoff["claim_ancestors"] = {
        claim_id: sorted(values) for claim_id, values in ancestors.items()}
    handoff["topological_claim_ids"] = order

    verifier_seen: set[str] = set()
    verifier_claim_counts: dict[str, int] = {}
    clean_assignments: list[dict] = []
    for index, assignment in enumerate(verifier_assignments):
        label = f"coordinator.verifier_assignments[{index}]"
        if not isinstance(assignment, dict):
            problems.append(f"{label} is not an object")
            continue
        verifier_id = str(assignment.get("verifier_id") or "").strip()
        if not verifier_id:
            problems.append(f"{label}.verifier_id is missing")
        elif verifier_id in verifier_seen:
            problems.append(f"verifier id {verifier_id!r} is duplicated")
        verifier_seen.add(verifier_id)
        claim_ids = _listed_ids(
            assignment.get("claim_ids"), f"{label}.claim_ids", problems)
        for claim_id in claim_ids:
            claim = canonical_by_id.get(claim_id)
            if claim is None:
                problems.append(
                    f"verifier assignment references unknown canonical claim {claim_id!r}")
                continue
            if claim.get("classification") != "material_claim":
                problems.append(
                    f"verifier assignment references non-material canonical claim {claim_id!r}")
                continue
            verifier_claim_counts[claim_id] = verifier_claim_counts.get(claim_id, 0) + 1
        clean_assignments.append({
            "verifier_id": verifier_id,
            "claim_ids": claim_ids,
        })
    for claim_id in handoff["material_claim_ids"]:
        count = verifier_claim_counts.get(claim_id, 0)
        if count == 0:
            problems.append(
                f"canonical material claim {claim_id!r} has no verifier assignment")
        elif count > 1:
            problems.append(
                f"canonical material claim {claim_id!r} is assigned to more than one verifier")

    handoff["verifier_assignments"] = clean_assignments
    return handoff, list(dict.fromkeys(problems))


def _correction_notice_problems(check: dict, occurrence_ids: list[str]) -> list[str]:
    """Validate an explicit repeated-occurrence correction without authoring it."""
    receipt = check.get("public_receipt")
    calculation = receipt.get("calculation") if isinstance(receipt, dict) else None
    report_operand = receipt.get("report_operand") if isinstance(receipt, dict) else None
    applicable = (
        check.get("verdict") == "contradicted"
        and len(occurrence_ids) > 1
        and isinstance(calculation, dict)
        and isinstance(report_operand, dict)
        and not values_equal(report_operand.get("value"), calculation.get("result"))
    )
    required = applicable and check.get("basis") == "report"
    supplied = "correction_notice" in check
    if not required and not (supplied and applicable):
        return []
    check_id = str(check.get("id") or "").strip() or "index"
    label = f"evidence-verifier check {check_id!r} correction_notice"
    notice = check.get("correction_notice")
    if not isinstance(notice, dict):
        return [f"{label} is missing or not an object"]
    problems: list[str] = []
    statement = str(notice.get("statement") or "").strip()
    report_value = notice.get("report_value")
    replacement = notice.get("replacement_value")
    locations = notice.get("locations")
    if not _substantive_explanation(statement):
        problems.append(f"{label}.statement is missing or not substantive")
    if not values_equal(report_value, report_operand.get("value")):
        problems.append(f"{label}.report_value does not match the report operand")
    if not values_equal(replacement, calculation.get("result")):
        problems.append(
            f"{label}.replacement_value does not match the calculation result")
    if (
        not isinstance(locations, list)
        or len(locations) != len(occurrence_ids)
        or len({str(value).strip() for value in locations}) != len(occurrence_ids)
    ):
        problems.append(
            f"{label}.locations does not name each repeated occurrence exactly once")
        locations = []
    for index, location in enumerate(locations):
        problem = _public_text_problem(location)
        if problem:
            problems.append(f"{label}.locations[{index}] {problem}")
        elif not _public_literal_in(location, statement):
            problems.append(
                f"{label}.statement does not contain locations[{index}]")
    if report_value in (None, "") or not _public_literal_in(report_value, statement):
        problems.append(f"{label}.statement does not contain report_value")
    if replacement in (None, "") or not _public_literal_in(replacement, statement):
        problems.append(f"{label}.statement does not contain replacement_value")
    explanation = str((receipt or {}).get("explanation") or "")
    if statement and not _public_literal_in(statement, explanation):
        problems.append(
            f"{label}.statement is not copied into public_receipt.explanation")
    return problems


def coordinator_preflight(canonical_claims, coordinator, inventory: dict,
                          proposed_checks, *,
                          presentation_doc: dict | None = None
                          ) -> tuple[dict, list[str]]:
    """Return exact host-handoff repair reasons before grounding acceptance."""
    handoff, problems = validate_coordinator_handoff(
        canonical_claims, coordinator, inventory)
    if not isinstance(proposed_checks, list):
        problems.append("evidence-verifier checks are not an array")
        proposed_checks = []
    expected_by_claim = handoff.get("material_claim_clause_ids") or {}
    for index, raw in enumerate(proposed_checks):
        if not isinstance(raw, dict):
            problems.append(
                f"evidence-verifier checks[{index}] is not an object")
            continue
        check_id = str(raw.get("id") or "").strip() or f"index {index}"
        claim_id = str(raw.get("claim_id") or "").strip()
        expected_ids = expected_by_claim.get(claim_id)
        if expected_ids is not None:
            addressed = _listed_ids(
                raw.get("addressed_clause_ids"),
                f"evidence-verifier check {check_id!r} addressed_clause_ids",
                problems)
            if len(addressed) != len(set(addressed)) or set(addressed) != set(expected_ids):
                problems.append(
                    f"evidence-verifier check {check_id!r} does not address every "
                    f"clause of canonical claim {claim_id!r}")
            occurrence_ids = (
                handoff.get("material_claim_inventory_ids") or {}).get(claim_id) or []
            problems.extend(_correction_notice_problems(raw, occurrence_ids))
        receipt = raw.get("public_receipt")
        calculation = (
            receipt.get("calculation") if isinstance(receipt, dict) else None
        )
        if calculation is None:
            continue
        if not isinstance(calculation, dict):
            problems.append(
                f"evidence-verifier check {check_id!r} "
                "public_receipt.calculation is not an object")
            continue
        if public_number(calculation.get("result")) is None:
            problems.append(
                f"evidence-verifier check {check_id!r} "
                "public_receipt.calculation.result is not a public numeric value")
    if presentation_doc is not None:
        presentation = (
            presentation_doc.get("presentation")
            if isinstance(presentation_doc, dict) else None
        )
        actions = (
            presentation.get("actions")
            if isinstance(presentation, dict) else None
        )
        actions = actions if isinstance(actions, list) else []
        for raw in proposed_checks:
            if not isinstance(raw, dict):
                continue
            notice = raw.get("correction_notice")
            if not isinstance(notice, dict):
                continue
            statement = str(notice.get("statement") or "").strip()
            check_id = str(raw.get("id") or "").strip()
            if statement and not any(
                isinstance(action, dict)
                and check_id in _check_ids_of(action)
                and _public_literal_in(statement, action.get("text"))
                for action in actions
            ):
                problems.append(
                    "presentation.actions does not include the exact correction "
                    f"statement for check {check_id!r}")
    return handoff, list(dict.fromkeys(problems))


def _assessment_population_alignment(raw, *, assessment_id: str,
                                     effect: str, basis: str,
                                     requirements: list[dict], report: str,
                                     evidence: pathlib.Path | None
                                     ) -> tuple[dict | None, list[str]]:
    """Resolve only host-declared population requirements and exact receipts."""
    problems: list[str] = []
    requirement_by_id = {
        str(row.get("id") or ""): row for row in requirements
        if isinstance(row, dict) and row.get("id")
    }
    if raw is None:
        if basis == "evidence" and requirements:
            problems.append(
                f"assessment {assessment_id!r} has no population alignment for "
                "its canonical claim requirements")
        return None, problems
    if basis != "evidence":
        return None, [
            f"assessment {assessment_id!r} population_alignment is allowed only "
            "for evidence basis"
        ]
    if not isinstance(raw, dict):
        return None, [f"assessment {assessment_id!r} population_alignment is not an object"]
    status = str(raw.get("status") or "").strip()
    reason = str(raw.get("reason") or "").strip()
    if not _substantive_explanation(reason):
        problems.append(
            f"assessment {assessment_id!r} population_alignment.reason is missing "
            "or not substantive")
    if status == "same_population":
        unknown = sorted(set(raw) - {"status", "reason", "links"})
        if unknown:
            problems.append(
                f"assessment {assessment_id!r} population_alignment has unknown "
                f"field {unknown[0]!r}")
        links = raw.get("links")
        if not isinstance(links, list) or not links:
            problems.append(
                f"assessment {assessment_id!r} population_alignment.links is "
                "missing or empty")
            links = []
        clean_links: list[dict] = []
        covered: list[str] = []
        for index, link in enumerate(links):
            label = f"assessment {assessment_id!r} population_alignment.links[{index}]"
            if not isinstance(link, dict):
                problems.append(f"{label} is not an object")
                continue
            unknown_link = sorted(set(link) - {
                "requirement_id", "dimension", "report_quote", "source_receipt",
            })
            if unknown_link:
                problems.append(f"{label} has unknown field {unknown_link[0]!r}")
            requirement_id = str(link.get("requirement_id") or "").strip()
            requirement = requirement_by_id.get(requirement_id)
            dimension = str(link.get("dimension") or "").strip()
            report_quote = str(link.get("report_quote") or "").strip()
            if requirement is None:
                problems.append(
                    f"{label}.requirement_id {requirement_id!r} is not declared "
                    "by the canonical claim")
            else:
                covered.append(requirement_id)
                if dimension != requirement.get("dimension"):
                    problems.append(
                        f"{label}.dimension does not match its population requirement")
                if report_quote != requirement.get("report_quote"):
                    problems.append(
                        f"{label}.report_quote does not match its population requirement")
            if dimension not in POPULATION_DIMENSIONS:
                problems.append(f"{label}.dimension is missing or unknown")
            if not quote_in_text(report_quote, report):
                problems.append(f"{label}.report_quote not found in visible report text")
            source_receipt, receipt_problems = validate_exact_source_receipt(
                evidence, link.get("source_receipt"), f"{label}.source_receipt")
            problems.extend(receipt_problems)
            clean_links.append({
                "requirement_id": requirement_id,
                "dimension": dimension,
                "report_quote": report_quote,
                "source_receipt": source_receipt,
            })
        if len(covered) != len(set(covered)):
            problems.append(
                f"assessment {assessment_id!r} population alignment repeats a "
                "claim requirement")
        for requirement_id in sorted(set(requirement_by_id) - set(covered)):
            problems.append(
                f"assessment {assessment_id!r} population alignment does not cover "
                f"claim requirement {requirement_id!r}")
        if effect == "unreconciled":
            problems.append(
                f"assessment {assessment_id!r} effect unreconciled cannot declare "
                "same_population")
        return {"status": status, "reason": reason, "links": clean_links}, problems
    if status == "unreconciled":
        unknown = sorted(set(raw) - {
            "status", "requirement_ids", "reason", "missing_dimensions",
            "conflict_receipts", "reconciliation_action",
        })
        if unknown:
            problems.append(
                f"assessment {assessment_id!r} population_alignment has unknown "
                f"field {unknown[0]!r}")
        requirement_ids = _listed_ids(
            raw.get("requirement_ids"),
            f"assessment {assessment_id!r} population_alignment.requirement_ids",
            problems)
        for requirement_id in requirement_ids:
            if requirement_id not in requirement_by_id:
                problems.append(
                    f"assessment {assessment_id!r} population alignment references "
                    f"unknown requirement {requirement_id!r}")
        dimensions = _listed_ids(
            raw.get("missing_dimensions"),
            f"assessment {assessment_id!r} population_alignment.missing_dimensions",
            problems)
        for dimension in dimensions:
            if dimension not in POPULATION_DIMENSIONS:
                problems.append(
                    f"assessment {assessment_id!r} population alignment has unknown "
                    f"missing dimension {dimension!r}")
        expected_dimensions = {
            str((requirement_by_id.get(requirement_id) or {}).get("dimension") or "")
            for requirement_id in requirement_ids
        }
        if set(dimensions) != expected_dimensions:
            problems.append(
                f"assessment {assessment_id!r} missing_dimensions do not match its "
                "named population requirements")
        receipts = raw.get("conflict_receipts")
        if not isinstance(receipts, list) or not receipts:
            problems.append(
                f"assessment {assessment_id!r} population_alignment.conflict_receipts "
                "is missing or empty")
            receipts = []
        clean_receipts: list[dict] = []
        for index, receipt in enumerate(receipts):
            canonical, receipt_problems = validate_exact_source_receipt(
                evidence, receipt,
                f"assessment {assessment_id!r} "
                f"population_alignment.conflict_receipts[{index}]")
            problems.extend(receipt_problems)
            if canonical is not None:
                clean_receipts.append(canonical)
        reconciliation = str(raw.get("reconciliation_action") or "").strip()
        if not _substantive_explanation(reconciliation):
            problems.append(
                f"assessment {assessment_id!r} population_alignment."
                "reconciliation_action is missing or not substantive")
        if effect != "unreconciled":
            problems.append(
                f"assessment {assessment_id!r} with unreconciled population must "
                "declare effect unreconciled")
        return {
            "status": status,
            "requirement_ids": requirement_ids,
            "reason": reason,
            "missing_dimensions": dimensions,
            "conflict_receipts": clean_receipts,
            "reconciliation_action": reconciliation,
        }, problems
    return None, [
        f"assessment {assessment_id!r} population_alignment.status is missing or unknown"
    ]


def validate_assessments(raw, *, handoff: dict, inventory: dict,
                         sources: list[dict], sandbox: pathlib.Path,
                         report_path: pathlib.Path, report: str
                         ) -> tuple[list[dict], dict[str, dict], list[str]]:
    """Validate private assessments, explicit origins, and dependency propagation."""
    if not isinstance(raw, list):
        return [], {}, ["assessments is missing or not an array"]
    problems: list[str] = []
    inventory_by_id = {
        str(row.get("id") or ""): row for row in (inventory.get("items") or [])
        if isinstance(row, dict) and row.get("id")
    }
    source_by_id = {
        str(row.get("id") or ""): row for row in sources
        if isinstance(row, dict) and row.get("id")
    }
    claim_ids = set(handoff.get("material_claim_ids") or [])
    claim_edges = {
        (
            str(row.get("upstream_claim_id") or ""),
            str(row.get("downstream_claim_id") or ""),
        )
        for row in handoff.get("claim_dependencies") or []
        if isinstance(row, dict)
    }
    by_id: dict[str, dict] = {}
    clean: list[dict] = []
    for index, row in enumerate(raw):
        label = f"assessments[{index}]"
        if not isinstance(row, dict):
            problems.append(f"{label} is not an object")
            continue
        unknown = sorted(set(row) - {
            "id", "claim_id", "basis", "effect", "source_id",
            "depends_on_assessment_ids", "operand_bindings", "calculation",
            "numeric_comparison", "population_alignment",
        })
        if unknown:
            problems.append(f"{label} has unknown field {unknown[0]!r}")
        assessment_id = str(row.get("id") or "").strip()
        claim_id = str(row.get("claim_id") or "").strip()
        basis = str(row.get("basis") or "").strip()
        effect = str(row.get("effect") or "").strip()
        source_id = str(row.get("source_id") or "").strip()
        if not assessment_id:
            problems.append(f"{label}.id is missing")
            continue
        if assessment_id in by_id:
            problems.append(f"assessment id {assessment_id!r} is duplicated")
        if claim_id not in claim_ids:
            problems.append(
                f"assessment {assessment_id!r} references unknown material claim {claim_id!r}")
        if basis not in {"report", "evidence"}:
            problems.append(f"assessment {assessment_id!r} basis is missing or unknown")
        if effect not in ASSESSMENT_EFFECTS:
            problems.append(f"assessment {assessment_id!r} effect is missing or unknown")
        if basis == "evidence":
            if not source_id:
                problems.append(f"assessment {assessment_id!r} source_id is missing")
            elif source_id not in source_by_id:
                problems.append(
                    f"assessment {assessment_id!r} source_id {source_id!r} is not retained")
        elif source_id:
            problems.append(
                f"assessment {assessment_id!r} report basis must not declare source_id")
        depends = _listed_ids(
            row.get("depends_on_assessment_ids"),
            f"assessment {assessment_id!r} depends_on_assessment_ids",
            problems, allow_empty=True)
        bindings_raw = row.get("operand_bindings")
        if not isinstance(bindings_raw, list) or not bindings_raw:
            problems.append(
                f"assessment {assessment_id!r} operand_bindings is missing or empty")
            bindings_raw = []
        bindings: list[dict] = []
        slots: set[str] = set()
        result_refs: list[str] = []
        for binding_index, binding in enumerate(bindings_raw):
            binding_label = (
                f"assessment {assessment_id!r} operand_bindings[{binding_index}]")
            if not isinstance(binding, dict):
                problems.append(f"{binding_label} is not an object")
                continue
            if sorted(set(binding) - {"slot", "origin"}):
                problems.append(f"{binding_label} has unknown fields")
            slot = str(binding.get("slot") or "").strip()
            if not slot:
                problems.append(f"{binding_label}.slot is missing")
            elif slot in slots:
                problems.append(
                    f"assessment {assessment_id!r} operand binding slot {slot!r} is duplicated")
            slots.add(slot)
            origin = binding.get("origin")
            if not isinstance(origin, dict):
                problems.append(f"{binding_label}.origin is not an object")
                continue
            kind = str(origin.get("kind") or "").strip()
            clean_origin: dict = {"kind": kind}
            if kind == "report_occurrence":
                unknown_origin = sorted(set(origin) - {"kind", "occurrence_id"})
                occurrence_id = str(origin.get("occurrence_id") or "").strip()
                clean_origin["occurrence_id"] = occurrence_id
                if unknown_origin:
                    problems.append(
                        f"{binding_label}.origin has unknown field {unknown_origin[0]!r}")
                if occurrence_id not in inventory_by_id:
                    problems.append(
                        f"assessment {assessment_id!r} references unknown report "
                        f"occurrence {occurrence_id!r}")
            elif kind == "source_receipt":
                unknown_origin = sorted(set(origin) - {"kind", "source_id", "receipt"})
                origin_source_id = str(origin.get("source_id") or "").strip()
                clean_origin["source_id"] = origin_source_id
                if unknown_origin:
                    problems.append(
                        f"{binding_label}.origin has unknown field {unknown_origin[0]!r}")
                if origin_source_id != source_id:
                    problems.append(
                        f"assessment {assessment_id!r} source receipt does not match "
                        "its retained source_id")
                source = source_by_id.get(origin_source_id) or {}
                evidence, path_problem = evidence_path(
                    sandbox, source.get("evidence_file"), report_path)
                if path_problem:
                    problems.append(path_problem)
                    evidence = None
                receipt, receipt_problems = validate_exact_source_receipt(
                    evidence, origin.get("receipt"), f"{binding_label}.origin.receipt")
                problems.extend(receipt_problems)
                clean_origin["receipt"] = receipt
            elif kind == "assessment_result":
                unknown_origin = sorted(set(origin) - {
                    "kind", "assessment_id", "field",
                })
                upstream_id = str(origin.get("assessment_id") or "").strip()
                field = str(origin.get("field") or "").strip()
                clean_origin.update({"assessment_id": upstream_id, "field": field})
                result_refs.append(upstream_id)
                if unknown_origin:
                    problems.append(
                        f"{binding_label}.origin has unknown field {unknown_origin[0]!r}")
                if field != "calculation.result":
                    problems.append(
                        f"assessment {assessment_id!r} assessment_result field is unknown")
            else:
                problems.append(
                    f"{binding_label}.origin.kind is missing or unknown")
            bindings.append({"slot": slot, "origin": clean_origin})
        if set(depends) != set(result_refs) or len(depends) != len(result_refs):
            problems.append(
                f"assessment {assessment_id!r} depends_on_assessment_ids do not "
                "match assessment_result bindings")
        calculation = row.get("calculation")
        clean_calculation = None
        if calculation is not None:
            if not isinstance(calculation, dict):
                problems.append(f"assessment {assessment_id!r} calculation is not an object")
            else:
                unknown_calc = sorted(set(calculation) - {"expression", "result"})
                if unknown_calc:
                    problems.append(
                        f"assessment {assessment_id!r} calculation has unknown field "
                        f"{unknown_calc[0]!r}")
                expression = str(calculation.get("expression") or "").strip()
                result = calculation.get("result")
                if public_number(result) is None:
                    problems.append(
                        f"assessment {assessment_id!r} calculation.result is not a "
                        "public numeric value")
                clean_calculation = {"expression": expression, "result": result}
        canonical = {
            "id": assessment_id,
            "claim_id": claim_id,
            "basis": basis,
            "effect": effect,
            "depends_on_assessment_ids": depends,
            "operand_bindings": bindings,
        }
        if source_id:
            canonical["source_id"] = source_id
        if clean_calculation is not None:
            canonical["calculation"] = clean_calculation
        if "numeric_comparison" in row:
            canonical["numeric_comparison"] = copy.deepcopy(row.get("numeric_comparison"))
        by_id[assessment_id] = canonical
        clean.append(canonical)

    assessment_edges: dict[str, set[str]] = {assessment_id: set() for assessment_id in by_id}
    indegree: dict[str, int] = {assessment_id: 0 for assessment_id in by_id}
    for assessment_id, assessment in by_id.items():
        for upstream_id in assessment.get("depends_on_assessment_ids") or []:
            upstream = by_id.get(upstream_id)
            if upstream is None:
                problems.append(
                    f"assessment {assessment_id!r} depends on unknown assessment {upstream_id!r}")
                continue
            upstream_claim = str(upstream.get("claim_id") or "")
            downstream_claim = str(assessment.get("claim_id") or "")
            if upstream_claim != downstream_claim and (
                upstream_claim, downstream_claim
            ) not in claim_edges:
                problems.append(
                    f"assessment {assessment_id!r} uses cross-claim assessment "
                    f"{upstream_id!r} without a declared claim dependency")
            if assessment_id not in assessment_edges[upstream_id]:
                assessment_edges[upstream_id].add(assessment_id)
                indegree[assessment_id] += 1
    queue = sorted(item for item, degree in indegree.items() if degree == 0)
    order: list[str] = []
    while queue:
        assessment_id = queue.pop(0)
        order.append(assessment_id)
        for child in sorted(assessment_edges[assessment_id]):
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)
                queue.sort()
    if len(order) != len(by_id):
        problems.append("assessment dependency graph contains a cycle")
        order.extend(sorted(set(by_id) - set(order)))

    owners = handoff.get("material_inventory_claim_ids") or {}
    contradiction_by_claim = {
        claim_id: [
            row for row in clean
            if row.get("claim_id") == claim_id and row.get("effect") == "contradicts"
        ]
        for claim_id in claim_ids
    }
    for assessment_id in order:
        assessment = by_id[assessment_id]
        resolved: dict[str, object] = {}
        for binding in assessment.get("operand_bindings") or []:
            slot = str(binding.get("slot") or "")
            origin = binding.get("origin") or {}
            kind = origin.get("kind")
            value = None
            if kind == "report_occurrence":
                occurrence_id = str(origin.get("occurrence_id") or "")
                item = inventory_by_id.get(occurrence_id) or {}
                value = item.get("displayed")
                for owner_claim in owners.get(occurrence_id) or []:
                    if owner_claim == assessment.get("claim_id"):
                        continue
                    if (owner_claim, assessment.get("claim_id")) not in claim_edges:
                        problems.append(
                            f"assessment {assessment_id!r} uses report occurrence "
                            f"{occurrence_id!r} from claim {owner_claim!r} without a "
                            "declared claim dependency")
                    if contradiction_by_claim.get(owner_claim):
                        problems.append(
                            f"assessment {assessment_id!r} uses stale report occurrence "
                            f"{occurrence_id!r} from contradicted upstream claim "
                            f"{owner_claim!r}")
            elif kind == "source_receipt":
                receipt = origin.get("receipt") or {}
                value = receipt.get("value") if isinstance(receipt, dict) else None
            elif kind == "assessment_result":
                upstream = by_id.get(str(origin.get("assessment_id") or "")) or {}
                value = (upstream.get("calculation") or {}).get("result")
                if value in (None, ""):
                    problems.append(
                        f"assessment {assessment_id!r} upstream assessment "
                        f"{origin.get('assessment_id')!r} has no grounded calculation result")
            resolved[slot] = value
        assessment["resolved_operands"] = resolved
        calculation = assessment.get("calculation")
        if isinstance(calculation, dict):
            operands = [
                {"label": slot, "value": value, "location": "private binding"}
                for slot, value in resolved.items()
            ]
            problem = calculation_problem(
                calculation.get("expression"), calculation.get("result"), operands)
            if problem:
                problems.append(f"assessment {assessment_id!r} {problem}")
        source = source_by_id.get(str(assessment.get("source_id") or "")) or {}
        evidence = None
        if assessment.get("basis") == "evidence":
            evidence, path_problem = evidence_path(
                sandbox, source.get("evidence_file"), report_path)
            if path_problem:
                problems.append(path_problem)
                evidence = None
        alignment, alignment_problems = _assessment_population_alignment(
            next((
                row.get("population_alignment") for row in raw
                if isinstance(row, dict) and row.get("id") == assessment_id
            ), None),
            assessment_id=assessment_id,
            effect=str(assessment.get("effect") or ""),
            basis=str(assessment.get("basis") or ""),
            requirements=(handoff.get("population_requirements") or {}).get(
                str(assessment.get("claim_id") or ""), []),
            report=report,
            evidence=evidence,
        )
        problems.extend(alignment_problems)
        if alignment is not None:
            assessment["population_alignment"] = alignment

    used_edges = {
        (
            str((by_id.get(upstream_id) or {}).get("claim_id") or ""),
            str(assessment.get("claim_id") or ""),
        )
        for assessment in clean
        for upstream_id in assessment.get("depends_on_assessment_ids") or []
        if (by_id.get(upstream_id) or {}).get("claim_id") != assessment.get("claim_id")
    }
    for upstream, downstream in sorted(claim_edges - used_edges):
        problems.append(
            f"claim dependency {upstream!r}->{downstream!r} has no downstream "
            "assessment_result binding")
    return clean, by_id, list(dict.fromkeys(problems))


def validate_assessment_numeric_policies(assessments: list[dict],
                                         checks: list[dict]
                                         ) -> tuple[dict[str, dict], list[str]]:
    """Apply only host-declared numeric policy to selected report operands."""
    problems: list[str] = []
    checks_by_claim = {
        str(row.get("claim_id") or ""): row for row in checks
        if isinstance(row, dict) and row.get("claim_id")
    }
    by_claim: dict[str, dict] = {}
    for assessment in assessments:
        assessment_id = str(assessment.get("id") or "")
        raw_policy = assessment.get("numeric_comparison")
        calculation = assessment.get("calculation")
        basis = assessment.get("basis")
        effect = assessment.get("effect")
        applicable = (
            basis == "report" and isinstance(calculation, dict)
            and effect in {"supports", "contradicts"}
        )
        if applicable and raw_policy is None:
            problems.append(
                f"assessment {assessment_id!r} numeric_comparison is required for "
                "report arithmetic")
            continue
        if not applicable and raw_policy is not None:
            problems.append(
                f"assessment {assessment_id!r} numeric_comparison is not allowed")
            continue
        if not applicable:
            continue
        claim_id = str(assessment.get("claim_id") or "")
        check = checks_by_claim.get(claim_id) or {}
        receipt = check.get("public_receipt") or {}
        report_operand = (
            receipt.get("report_operand") if isinstance(receipt, dict) else None)
        finding = {
            "basis": "report",
            "type": "arithmetic",
            "verdict": "confirmed" if effect == "supports" else "contradicted",
            "numeric_comparison": raw_policy,
        }
        canonical, policy_problems = validate_numeric_comparison(
            finding, report_operand, calculation)
        for problem in policy_problems:
            problems.append(f"assessment {assessment_id!r} {problem}")
        if canonical is not None:
            assessment["numeric_comparison"] = canonical
            final_verdict = str(check.get("verdict") or "")
            if (
                check.get("basis") == "report"
                and check.get("type") == "arithmetic"
                and final_verdict in {"confirmed", "contradicted"}
                and (
                    (effect == "supports" and final_verdict == "confirmed")
                    or (effect == "contradicts" and final_verdict == "contradicted")
                )
            ):
                if claim_id in by_claim:
                    problems.append(
                        f"claim {claim_id!r} has more than one decisive numeric policy")
                by_claim[claim_id] = copy.deepcopy(raw_policy)
    return by_claim, list(dict.fromkeys(problems))


def validate_resolutions(raw, *, assessments: list[dict], handoff: dict,
                         checks: list[dict]
                         ) -> tuple[list[dict], dict[str, dict], list[str]]:
    """Reconcile assessment states into exactly one host-authored claim outcome."""
    if not isinstance(raw, list):
        return [], {}, ["resolutions is missing or not an array"]
    problems: list[str] = []
    assessment_by_id = {
        str(row.get("id") or ""): row for row in assessments
        if isinstance(row, dict) and row.get("id")
    }
    assessment_ids_by_claim: dict[str, list[str]] = {}
    for assessment in assessments:
        assessment_ids_by_claim.setdefault(
            str(assessment.get("claim_id") or ""), []).append(
                str(assessment.get("id") or ""))
    check_by_claim: dict[str, list[dict]] = {}
    for check in checks:
        if isinstance(check, dict):
            check_by_claim.setdefault(str(check.get("claim_id") or ""), []).append(check)
    material_claim_ids = set(handoff.get("material_claim_ids") or [])
    by_claim: dict[str, dict] = {}
    clean: list[dict] = []
    for index, row in enumerate(raw):
        label = f"resolutions[{index}]"
        if not isinstance(row, dict):
            problems.append(f"{label} is not an object")
            continue
        unknown = sorted(set(row) - {
            "claim_id", "assessment_ids", "state", "final_verdict", "reason",
            "required_action_kind",
        })
        if unknown:
            problems.append(f"{label} has unknown field {unknown[0]!r}")
        claim_id = str(row.get("claim_id") or "").strip()
        if claim_id not in material_claim_ids:
            problems.append(f"{label}.claim_id {claim_id!r} is not material")
        if claim_id in by_claim:
            problems.append(f"claim resolution {claim_id!r} is duplicated")
        assessment_ids = _listed_ids(
            row.get("assessment_ids"),
            f"claim resolution {claim_id!r} assessment_ids", problems,
            allow_empty=True)
        expected_ids = assessment_ids_by_claim.get(claim_id) or []
        if set(assessment_ids) != set(expected_ids) or len(assessment_ids) != len(expected_ids):
            problems.append(
                f"claim resolution {claim_id!r} assessment_ids do not include every "
                "assessment for the claim")
        state = str(row.get("state") or "").strip()
        final_verdict = str(row.get("final_verdict") or "").strip()
        action_kind = str(row.get("required_action_kind") or "").strip()
        reason = str(row.get("reason") or "").strip()
        if state not in RESOLUTION_STATES:
            problems.append(f"claim resolution {claim_id!r} state is missing or unknown")
        if final_verdict not in KNOWN_VERDICTS:
            problems.append(
                f"claim resolution {claim_id!r} final_verdict is missing or unknown")
        if action_kind not in ACTION_KINDS:
            problems.append(
                f"claim resolution {claim_id!r} required_action_kind is missing or unknown")
        if not _substantive_explanation(reason):
            problems.append(
                f"claim resolution {claim_id!r} reason is missing or not substantive")
        canonical = {
            "claim_id": claim_id,
            "assessment_ids": assessment_ids,
            "state": state,
            "final_verdict": final_verdict,
            "reason": reason,
            "required_action_kind": action_kind,
        }
        by_claim[claim_id] = canonical
        clean.append(canonical)
    for claim_id in sorted(material_claim_ids - set(by_claim)):
        problems.append(f"material claim {claim_id!r} has no claim resolution")

    ancestors = handoff.get("claim_ancestors") or {}
    for claim_id, resolution in by_claim.items():
        selected = [assessment_by_id.get(item) or {} for item in resolution["assessment_ids"]]
        effects = {str(row.get("effect") or "") for row in selected if row}
        unresolved_ancestor = None
        for ancestor_id in ancestors.get(claim_id) or []:
            ancestor = by_claim.get(ancestor_id) or {}
            if ancestor.get("final_verdict") in {
                "not_checkable", "changed_since_report",
            }:
                unresolved_ancestor = ancestor_id
                break
            if ancestor.get("final_verdict") == "contradicted":
                replacements = [
                    assessment_by_id.get(item) or {}
                    for item in ancestor.get("assessment_ids") or []
                ]
                if not any(
                    row.get("effect") == "contradicts"
                    and public_number((row.get("calculation") or {}).get("result")) is not None
                    for row in replacements
                ):
                    unresolved_ancestor = ancestor_id
                    break
        if unresolved_ancestor:
            expected = ("dependency_unresolved", "not_checkable", "reconcile_before_change")
            if (
                resolution.get("state"), resolution.get("final_verdict"),
                resolution.get("required_action_kind"),
            ) != expected:
                problems.append(
                    f"claim resolution {claim_id!r} has unresolved upstream claim "
                    f"{unresolved_ancestor!r} and must resolve not_checkable")
        elif "changed_since_report" in effects:
            expected = ("changed_since_report", "changed_since_report", "review_before_share")
            if (
                resolution.get("state"), resolution.get("final_verdict"),
                resolution.get("required_action_kind"),
            ) != expected:
                problems.append(
                    f"claim resolution {claim_id!r} does not match its changed-since-report assessment")
        elif "unreconciled" in effects or ({"supports", "contradicts"} <= effects):
            expected = ("unreconciled", "not_checkable", "reconcile_before_change")
            if (
                resolution.get("state"), resolution.get("final_verdict"),
                resolution.get("required_action_kind"),
            ) != expected:
                suffix = (
                    " for conflicting aligned assessments"
                    if {"supports", "contradicts"} <= effects
                    else " for an unreconciled assessment"
                )
                problems.append(
                    f"claim resolution {claim_id!r} must be not_checkable with "
                    f"state 'unreconciled'{suffix}")
        elif effects == {"supports"}:
            expected = ("supported", "confirmed", "review_before_share")
            if (
                resolution.get("state"), resolution.get("final_verdict"),
                resolution.get("required_action_kind"),
            ) != expected:
                problems.append(
                    f"claim resolution {claim_id!r} does not match supporting assessments")
        elif effects == {"contradicts"}:
            expected = ("contradicted", "contradicted", "correct_report")
            if (
                resolution.get("state"), resolution.get("final_verdict"),
                resolution.get("required_action_kind"),
            ) != expected:
                problems.append(
                    f"claim resolution {claim_id!r} does not match contradicting assessments")
        elif not effects:
            expected = ("not_assessed", "not_checkable", "review_before_share")
            if (
                resolution.get("state"), resolution.get("final_verdict"),
                resolution.get("required_action_kind"),
            ) != expected:
                problems.append(
                    f"claim resolution {claim_id!r} with no decisive assessment must "
                    "resolve not_checkable")

        claim_checks = check_by_claim.get(claim_id) or []
        if len(claim_checks) != 1:
            problems.append(
                f"claim resolution {claim_id!r} must have exactly one customer check")
        else:
            check = claim_checks[0]
            if check.get("verdict") != resolution.get("final_verdict"):
                problems.append(
                    f"customer check for claim {claim_id!r} verdict does not match "
                    "its claim resolution")
            check_ids = _listed_ids(
                check.get("assessment_ids"),
                f"customer check for claim {claim_id!r} assessment_ids", problems,
                allow_empty=not resolution.get("assessment_ids"))
            if set(check_ids) != set(resolution.get("assessment_ids") or []):
                problems.append(
                    f"customer check for claim {claim_id!r} assessment_ids do not "
                    "match its claim resolution")
    return clean, by_claim, list(dict.fromkeys(problems))


def _safe_bundle_path(root: pathlib.Path, raw, label: str,
                      problems: list[str]) -> pathlib.Path | None:
    text = str(raw or "").strip()
    candidate = pathlib.Path(text)
    if not text or candidate.is_absolute() or ".." in candidate.parts:
        problems.append(f"{label} is not a safe relative path")
        return None
    path = (root / candidate).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError:
        problems.append(f"{label} leaves the role bundle root")
        return None
    return path


def _validate_role_bundle_content(path: pathlib.Path, *, role_id: str,
                                  role: str, stage: str, field: str,
                                  problems: list[str]) -> dict | None:
    """Validate exact role/stage bundle mechanics without inspecting meaning."""
    try:
        payload = json.loads(path.read_text())
    except (OSError, UnicodeError, json.JSONDecodeError):
        problems.append(f"role run {role_id!r} {field} is not valid JSON")
        return None
    if not isinstance(payload, dict):
        problems.append(f"role run {role_id!r} {field} is not a JSON object")
        return None
    if payload.get("contract_version") != WORKFLOW_VERSION:
        problems.append(
            f"role run {role_id!r} {field} has the wrong private workflow version")
    if payload.get("role") != role:
        problems.append(f"role run {role_id!r} {field} does not match its role")
    if payload.get("stage") != stage:
        problems.append(f"role run {role_id!r} {field} does not match its stage")
    required = (
        ROLE_INPUT_FIELDS.get(stage, set())
        if field == "input_bundle" else ROLE_OUTPUT_FIELDS.get(stage, set())
    )
    common = {"contract_version", "role", "stage"}
    if field == "input_bundle":
        allowed = common | required | {"repair_context"}
    else:
        allowed = common | required | {"status"}
        if payload.get("status") != "complete":
            problems.append(f"role run {role_id!r} output_bundle status is not complete")
    for name in sorted(required - set(payload)):
        problems.append(
            f"role run {role_id!r} {field} is missing required field {name!r}")
    unknown = sorted(set(payload) - allowed)
    if unknown:
        problems.append(
            f"role run {role_id!r} {field} has unknown field {unknown[0]!r}")
    repair_context = payload.get("repair_context")
    if repair_context is not None:
        if field != "input_bundle" or not isinstance(repair_context, dict):
            problems.append(
                f"role run {role_id!r} repair_context is not an input object")
        else:
            if set(repair_context) != {
                "prior_role_output", "mechanical_repair_reasons",
            }:
                problems.append(
                    f"role run {role_id!r} repair_context fields are invalid")
            if not isinstance(repair_context.get("prior_role_output"), dict):
                problems.append(
                    f"role run {role_id!r} repair_context.prior_role_output is not an object")
            reasons = repair_context.get("mechanical_repair_reasons")
            if not isinstance(reasons, list) or not reasons or any(
                not isinstance(reason, str) or not reason.strip() for reason in reasons
            ):
                problems.append(
                    f"role run {role_id!r} repair_context.mechanical_repair_reasons "
                    "is missing or invalid")
    return payload


def _role_body(payload: dict | None) -> dict:
    """Remove the mechanical role envelope from one materialized bundle."""
    return {
        key: copy.deepcopy(value) for key, value in (payload or {}).items()
        if key not in {
            "contract_version", "role", "stage", "status", "repair_context",
        }
    }


def _keyed_rows(raw, *, label: str, key_of, problems: list[str]) -> dict:
    """Index exact host rows without interpreting any row contents."""
    if not isinstance(raw, list):
        problems.append(f"{label} is not an array")
        return {}
    indexed: dict = {}
    for index, row in enumerate(raw):
        if not isinstance(row, dict):
            problems.append(f"{label}[{index}] is not an object")
            continue
        key = key_of(row)
        if not key or (isinstance(key, tuple) and not all(key)):
            problems.append(f"{label}[{index}] has no stable identity")
            continue
        if key in indexed:
            problems.append(f"{label} contains duplicate identity {key!r}")
        indexed[key] = row
    return indexed


def _compare_keyed_rows(actual, expected, *, label: str, key_of,
                        problems: list[str]) -> None:
    """Require exact rows by opaque identity while ignoring list ordering."""
    actual_by_key = _keyed_rows(
        actual, label=f"role {label}", key_of=key_of, problems=problems)
    expected_by_key = _keyed_rows(
        expected, label=f"accepted {label}", key_of=key_of,
        problems=problems)
    for key in sorted(set(actual_by_key) | set(expected_by_key), key=str):
        if key not in actual_by_key:
            problems.append(f"role {label} is missing accepted identity {key!r}")
        elif key not in expected_by_key:
            problems.append(f"role {label} contains unknown identity {key!r}")
        elif actual_by_key[key] != expected_by_key[key]:
            problems.append(
                f"role {label} does not exactly match accepted identity {key!r}")


def _validate_role_wiring(runs: list[dict], expected: dict,
                          problems: list[str]) -> None:
    """Tie bounded v6 role bundles to the exact bundle accepted downstream."""
    by_stage: dict[str, list[dict]] = {}
    for run in runs:
        by_stage.setdefault(str(run.get("stage") or ""), []).append(run)

    claim_runs = by_stage.get("claim_taking") or []
    raw_coordinator = expected.get("coordinator")
    raw_coordinator = raw_coordinator if isinstance(raw_coordinator, dict) else {}
    partitions = raw_coordinator.get("partition_results")
    partitions = partitions if isinstance(partitions, list) else []
    partition_by_id = _keyed_rows(
        partitions, label="accepted coordinator partitions",
        key_of=lambda row: str(row.get("partition_id") or ""),
        problems=problems)
    claim_outputs: dict[str, dict] = {}
    inventory = expected.get("inventory")
    inventory = inventory if isinstance(inventory, dict) else {}
    inventory_by_id = _keyed_rows(
        inventory.get("items") or [], label="accepted inventory",
        key_of=lambda row: str(row.get("id") or ""), problems=problems)
    for run in claim_runs:
        role_id = str(run.get("id") or "")
        input_body = _role_body(run.get("input_payload"))
        output_body = _role_body(run.get("output_payload"))
        partition_id = str(output_body.get("partition_id") or "")
        if input_body.get("partition_id") != partition_id:
            problems.append(
                f"role run {role_id!r} claim-taker input/output partition_id differs")
        if partition_id in claim_outputs:
            problems.append(
                f"claim-taker partition {partition_id!r} has more than one role output")
        claim_outputs[partition_id] = output_body
        if output_body != partition_by_id.get(partition_id):
            problems.append(
                f"role run {role_id!r} claim-taker output does not exactly match "
                f"coordinator partition {partition_id!r}")

        input_inventory = input_body.get("inventory")
        input_inventory = input_inventory if isinstance(input_inventory, dict) else {}
        input_items = _keyed_rows(
            input_inventory.get("items") or [],
            label=f"role run {role_id!r} claim-taker inventory",
            key_of=lambda row: str(row.get("id") or ""), problems=problems)
        allowed_ids = {
            str(row.get("occurrence_id") or "")
            for row in output_body.get("occurrence_decisions") or []
            if isinstance(row, dict)
        }
        for clause in output_body.get("clauses") or []:
            if isinstance(clause, dict):
                allowed_ids.update(
                    str(value or "")
                    for value in clause.get("context_occurrence_ids") or [])
        allowed_ids.discard("")
        if set(input_items) != allowed_ids:
            problems.append(
                f"role run {role_id!r} claim-taker inventory does not match its "
                "partition occurrence and context ids")
        for occurrence_id, item in input_items.items():
            if item != inventory_by_id.get(occurrence_id):
                problems.append(
                    f"role run {role_id!r} claim-taker inventory occurrence "
                    f"{occurrence_id!r} does not exactly match accepted inventory")
    for partition_id in sorted(set(partition_by_id) - set(claim_outputs)):
        problems.append(
            f"accepted coordinator partition {partition_id!r} has no claim-taker output")
    for partition_id in sorted(set(claim_outputs) - set(partition_by_id)):
        problems.append(
            f"claim-taker output partition {partition_id!r} is not in the coordinator handoff")

    plan_runs = by_stage.get("coordinator_semantic_plan") or []
    if len(plan_runs) != 1:
        problems.append(
            "role provenance must contain exactly one final coordinator semantic-plan run")
    canonical_claims = expected.get("canonical_claims")
    canonical_claims = canonical_claims if isinstance(canonical_claims, list) else []
    sources = expected.get("sources")
    sources = sources if isinstance(sources, list) else []
    report_metadata = expected.get("report_metadata")
    report_metadata = report_metadata if isinstance(report_metadata, dict) else {}
    if len(plan_runs) == 1:
        run = plan_runs[0]
        role_id = str(run.get("id") or "")
        input_body = _role_body(run.get("input_payload"))
        output_body = _role_body(run.get("output_payload"))
        expected_input = {
            "partition_results": partitions,
            "inventory": inventory,
            "report_metadata": report_metadata,
            "internal_candidates": input_body.get("internal_candidates"),
            "approved_source_manifest": sources,
        }
        if not isinstance(input_body.get("internal_candidates"), list):
            problems.append(
                f"role run {role_id!r} internal_candidates is not an array")
        if input_body != expected_input:
            problems.append(
                f"role run {role_id!r} coordinator semantic-plan input does not "
                "exactly match claim-taker outputs, inventory, metadata, and approved sources")
        expected_output = {
            "classification_reviews": raw_coordinator.get(
                "classification_reviews"),
            "canonical_claims": canonical_claims,
            "source_consideration_plan": raw_coordinator.get(
                "source_consideration_plan"),
            "claim_dependencies": raw_coordinator.get("claim_dependencies"),
            "verifier_assignments": raw_coordinator.get("verifier_assignments"),
        }
        if output_body != expected_output:
            problems.append(
                f"role run {role_id!r} coordinator semantic-plan output does not "
                "exactly match the merged coordinator handoff")

    claim_by_id = _keyed_rows(
        canonical_claims, label="accepted canonical claims",
        key_of=lambda row: str(row.get("id") or ""), problems=problems)
    _keyed_rows(
        sources, label="accepted retained sources",
        key_of=lambda row: str(row.get("id") or ""), problems=problems)
    source_plan = raw_coordinator.get("source_consideration_plan")
    source_plan = source_plan if isinstance(source_plan, list) else []
    assignments = raw_coordinator.get("verifier_assignments")
    assignments = assignments if isinstance(assignments, list) else []
    expected_assignment_sets = sorted(
        tuple(sorted(str(value or "") for value in row.get("claim_ids") or []))
        for row in assignments if isinstance(row, dict)
    )
    verifier_runs = by_stage.get("dependency_ordered_verification") or []
    actual_assignment_sets: list[tuple[str, ...]] = []
    verifier_assessments: list[dict] = []
    verifier_source_rows: list[dict] = []
    final_assessments = expected.get("assessments")
    final_assessments = final_assessments if isinstance(final_assessments, list) else []
    final_assessment_by_id = _keyed_rows(
        final_assessments, label="accepted assessments",
        key_of=lambda row: str(row.get("id") or ""), problems=problems)
    for run in verifier_runs:
        role_id = str(run.get("id") or "")
        input_body = _role_body(run.get("input_payload"))
        output_body = _role_body(run.get("output_payload"))
        input_claims = input_body.get("canonical_claims")
        input_claims = input_claims if isinstance(input_claims, list) else []
        input_claim_ids = [
            str(row.get("id") or "") for row in input_claims
            if isinstance(row, dict)
        ]
        actual_assignment_sets.append(tuple(sorted(input_claim_ids)))
        for claim in input_claims:
            claim_id = str(claim.get("id") or "") if isinstance(claim, dict) else ""
            if claim != claim_by_id.get(claim_id):
                problems.append(
                    f"role run {role_id!r} verifier canonical claim {claim_id!r} "
                    "does not exactly match the coordinator claim")
        relevant_text = input_body.get("relevant_report_text")
        if not isinstance(relevant_text, str):
            problems.append(
                f"role run {role_id!r} relevant_report_text is not text")
        else:
            for claim in input_claims:
                if isinstance(claim, dict) and not quote_in_text(
                        str(claim.get("quote") or ""), relevant_text):
                    problems.append(
                        f"role run {role_id!r} relevant_report_text omits canonical "
                        f"claim {claim.get('id')!r}")
        expected_plan = [
            row for row in source_plan
            if isinstance(row, dict) and row.get("claim_id") in input_claim_ids
        ]
        if input_body.get("source_consideration_plan") != expected_plan:
            problems.append(
                f"role run {role_id!r} source_consideration_plan does not exactly "
                "match its assigned canonical claims")
        considered_source_ids = {
            str(row.get("source_id") or "") for row in expected_plan
            if row.get("decision") == "consider"
        }
        expected_sources = [
            row for row in sources
            if isinstance(row, dict) and row.get("id") in considered_source_ids
        ]
        if input_body.get("assigned_sources") != expected_sources:
            problems.append(
                f"role run {role_id!r} assigned_sources do not exactly match the "
                "coordinator source plan")

        output_assessments = output_body.get("assessments")
        output_assessments = (
            output_assessments if isinstance(output_assessments, list) else [])
        verifier_assessments.extend(output_assessments)
        output_source_rows = output_body.get("source_consideration_results")
        output_source_rows = (
            output_source_rows if isinstance(output_source_rows, list) else [])
        verifier_source_rows.extend(output_source_rows)
        for field in ("proposed_resolutions", "checks"):
            rows = output_body.get(field)
            rows = rows if isinstance(rows, list) else []
            row_claim_ids = [
                str(row.get("claim_id") or "") for row in rows
                if isinstance(row, dict)
            ]
            if sorted(row_claim_ids) != sorted(input_claim_ids):
                problems.append(
                    f"role run {role_id!r} {field} do not cover exactly its "
                    "assigned canonical claims")
        expected_upstream: list[dict] = []
        seen_upstream: set[str] = set()
        for assessment in output_assessments:
            if not isinstance(assessment, dict):
                continue
            for binding in assessment.get("operand_bindings") or []:
                origin = binding.get("origin") if isinstance(binding, dict) else None
                if not isinstance(origin, dict) or origin.get("kind") != "assessment_result":
                    continue
                upstream_id = str(origin.get("assessment_id") or "")
                upstream = final_assessment_by_id.get(upstream_id) or {}
                if upstream.get("claim_id") in input_claim_ids or upstream_id in seen_upstream:
                    continue
                seen_upstream.add(upstream_id)
                expected_upstream.append({
                    "assessment_id": upstream_id,
                    "field": "calculation.result",
                    "value": (upstream.get("calculation") or {}).get("result"),
                })
        if input_body.get("accepted_upstream_assessment_results") != expected_upstream:
            problems.append(
                f"role run {role_id!r} accepted_upstream_assessment_results do not "
                "exactly match its declared assessment-result bindings")
    if sorted(actual_assignment_sets) != expected_assignment_sets:
        problems.append(
            "evidence-verifier role inputs do not exactly match coordinator assignments")
    _compare_keyed_rows(
        verifier_assessments, final_assessments, label="verifier assessments",
        key_of=lambda row: str(row.get("id") or ""), problems=problems)
    final_source_rows = expected.get("source_consideration")
    final_source_rows = final_source_rows if isinstance(final_source_rows, list) else []
    _compare_keyed_rows(
        verifier_source_rows, final_source_rows,
        label="verifier source-consideration results",
        key_of=lambda row: (
            str(row.get("source_id") or ""), str(row.get("claim_id") or "")),
        problems=problems)

    resolution_runs = by_stage.get("coordinator_global_resolution") or []
    if len(resolution_runs) != 1:
        problems.append(
            "role provenance must contain exactly one final coordinator global-resolution run")
    if len(resolution_runs) == 1:
        run = resolution_runs[0]
        role_id = str(run.get("id") or "")
        input_body = _role_body(run.get("input_payload"))
        output_body = _role_body(run.get("output_payload"))
        expected_input = {
            "canonical_claims": canonical_claims,
            "assessments": final_assessments,
            "source_consideration_results": final_source_rows,
            "claim_dependencies": raw_coordinator.get("claim_dependencies"),
        }
        if input_body != expected_input:
            problems.append(
                f"role run {role_id!r} coordinator global-resolution input does "
                "not exactly match verifier outputs")
        expected_output = {
            "sources": sources,
            "source_consideration": final_source_rows,
            "whole_source_exclusions": expected.get("whole_source_exclusions"),
            "assessments": final_assessments,
            "resolutions": expected.get("resolutions"),
            "checks": expected.get("checks"),
            "presentation": expected.get("presentation"),
        }
        if output_body != expected_output:
            problems.append(
                f"role run {role_id!r} coordinator global-resolution output does "
                "not exactly match the final acceptance bundle")


def validate_role_provenance(raw, bundle_root: pathlib.Path, *,
                             evidence_root: pathlib.Path | None = None,
                             expected_workflow: dict | None = None,
                             ) -> tuple[dict | None, list[str]]:
    """Validate bounded role bundles, digests, and observed read paths."""
    if not isinstance(raw, dict):
        return None, ["role_provenance is missing or not an object"]
    problems: list[str] = []
    route = str(raw.get("route") or "").strip()
    if route not in {"native_subagents", "sequential"}:
        problems.append("role_provenance.route is missing or unknown")
    runs = raw.get("runs")
    if not isinstance(runs, list) or not runs:
        problems.append("role_provenance.runs is missing or empty")
        runs = []
    seen: set[str] = set()
    roles: set[str] = set()
    stages: set[str] = set()
    clean_runs: list[dict] = []
    loaded_runs: list[dict] = []
    for index, row in enumerate(runs):
        label = f"role_provenance.runs[{index}]"
        if not isinstance(row, dict):
            problems.append(f"{label} is not an object")
            continue
        role_id = str(row.get("id") or "").strip()
        role = str(row.get("role") or "").strip()
        stage = str(row.get("stage") or "").strip()
        if not role_id:
            problems.append(f"{label}.id is missing")
        elif role_id in seen:
            problems.append(f"role run id {role_id!r} is duplicated")
        seen.add(role_id)
        if role not in {"claim_taker", "coordinator", "evidence_verifier"}:
            problems.append(f"role run {role_id!r} role is missing or unknown")
        if stage not in {
            "claim_taking", "coordinator_semantic_plan",
            "dependency_ordered_verification", "coordinator_global_resolution",
        }:
            problems.append(f"role run {role_id!r} stage is missing or unknown")
        elif ROLE_STAGE_OWNERS.get(stage) != role:
            problems.append(
                f"role run {role_id!r} role does not own stage {stage!r}")
        roles.add(role)
        stages.add(stage)
        canonical_files: dict[str, dict] = {}
        bundle_payloads: dict[str, dict] = {}
        for field in ("input_bundle", "output_bundle"):
            value = row.get(field)
            if not isinstance(value, dict):
                problems.append(f"role run {role_id!r} {field} is not an object")
                continue
            path = _safe_bundle_path(
                bundle_root, value.get("path"),
                f"role run {role_id!r} {field}.path", problems)
            digest = str(value.get("sha256") or "").strip().lower()
            if not re.fullmatch(r"[0-9a-f]{64}", digest):
                problems.append(f"role run {role_id!r} {field}.sha256 is invalid")
            if path is not None:
                if not path.is_file():
                    problems.append(f"role run {role_id!r} {field} file is missing")
                else:
                    actual = hashlib.sha256(path.read_bytes()).hexdigest()
                    if actual != digest:
                        problems.append(
                            f"role run {role_id!r} {field}.sha256 does not match its file")
                    if field == "input_bundle" and path.stat().st_mode & 0o222:
                        problems.append(
                            f"role run {role_id!r} input_bundle is not read-only")
                    content = _validate_role_bundle_content(
                        path, role_id=role_id, role=role, stage=stage,
                        field=field, problems=problems)
                    if content is not None:
                        bundle_payloads[field] = content
            canonical_files[field] = {
                "path": str(value.get("path") or "").strip(), "sha256": digest,
            }
        allowed = _listed_ids(
            row.get("allowed_read_paths"),
            f"role run {role_id!r} allowed_read_paths", problems)
        observed = _listed_ids(
            row.get("observed_read_paths"),
            f"role run {role_id!r} observed_read_paths", problems)
        for observed_path in observed:
            if observed_path not in set(allowed):
                problems.append(
                    f"role run {role_id!r} observed undeclared read path "
                    f"{observed_path!r}")
        input_path = (canonical_files.get("input_bundle") or {}).get("path")
        expected_allowed = [input_path] if input_path else []
        input_payload = bundle_payloads.get("input_bundle") or {}
        if stage == "dependency_ordered_verification":
            for source_index, source in enumerate(
                    input_payload.get("assigned_sources") or []):
                if not isinstance(source, dict):
                    problems.append(
                        f"role run {role_id!r} assigned_sources[{source_index}] "
                        "is not an object")
                    continue
                source_path, source_problem = evidence_path(
                    pathlib.Path(evidence_root or bundle_root),
                    source.get("evidence_file"), None)
                if source_problem:
                    problems.append(
                        f"role run {role_id!r} assigned_sources[{source_index}] "
                        f"{source_problem}")
                    continue
                try:
                    relative = source_path.resolve().relative_to(
                        bundle_root.resolve())
                except ValueError:
                    problems.append(
                        f"role run {role_id!r} assigned source leaves the role bundle root")
                    continue
                expected_allowed.append(str(relative))
        expected_allowed = list(dict.fromkeys(expected_allowed))
        if input_path and allowed != expected_allowed:
            problems.append(
                f"role run {role_id!r} allowed_read_paths do not match its "
                "materialized input bundle and assigned source files")
        if input_path and input_path not in observed:
            problems.append(
                f"role run {role_id!r} did not record reading its input bundle")
        clean_runs.append({
            "id": role_id, "role": role, "stage": stage,
            **canonical_files,
            "allowed_read_paths": allowed,
            "observed_read_paths": observed,
        })
        loaded_runs.append({
            "id": role_id, "role": role, "stage": stage,
            "input_payload": bundle_payloads.get("input_bundle"),
            "output_payload": bundle_payloads.get("output_bundle"),
        })
    for required_role in ("claim_taker", "coordinator", "evidence_verifier"):
        if required_role not in roles:
            problems.append(f"role_provenance has no {required_role} run")
    for required_stage in (
        "claim_taking", "coordinator_semantic_plan",
        "dependency_ordered_verification", "coordinator_global_resolution",
    ):
        if required_stage not in stages:
            problems.append(f"role_provenance has no {required_stage} stage")
    if isinstance(expected_workflow, dict):
        _validate_role_wiring(loaded_runs, expected_workflow, problems)
    return {"route": route, "runs": clean_runs}, list(dict.fromkeys(problems))


def bundle_sha256(*, report_path: pathlib.Path, text: str, inventory: dict,
                  proposed_claims: list, claims_meta: dict, checks_doc: dict,
                  sandbox: pathlib.Path) -> str:
    """Hash exact report/private bundle state and actual retained evidence bytes."""
    evidence_rows: list[dict] = []
    for source in checks_doc.get("sources") or []:
        if not isinstance(source, dict):
            continue
        path, problem = evidence_path(
            sandbox, source.get("evidence_file"), report_path)
        evidence_rows.append({
            "source_id": str(source.get("id") or ""),
            "evidence_file": str(source.get("evidence_file") or ""),
            "actual_sha256": (
                hashlib.sha256(path.read_bytes()).hexdigest()
                if path is not None and problem is None else None
            ),
        })
    digest_meta = {
        key: copy.deepcopy(value) for key, value in claims_meta.items()
        if key in {"contract_version", "report_period", "report_date", "coordinator"}
    }
    payload = {
        "report_sha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
        "visible_text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "inventory": copy.deepcopy(inventory),
        "claims": copy.deepcopy(proposed_claims),
        "claims_meta": digest_meta,
        "checks": copy.deepcopy(checks_doc),
        "evidence": evidence_rows,
    }
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_receipts(report: str, sandbox: pathlib.Path, proposed: list,
                      claim_ids: set[str],
                      report_path: pathlib.Path | None = None, *,
                      sources: list[dict] | None = None,
                      claim_labels: dict[str, str] | None = None,
                      report_date: str | None = None,
                      report_period: str | None = None,
                      numeric_comparisons: dict[str, dict] | None = None,
                      population_alignments: dict[str, dict] | None = None,
                      explicit_operand_values: dict[str, list] | None = None,
                      ) -> tuple[list, list]:
    """Ground agent-authored checks; never invent their public semantics."""
    validated: list[dict] = []
    discarded: list[dict] = []
    source_map = {
        str(row.get("id") or ""): row for row in (sources or [])
        if isinstance(row, dict) and row.get("id")
    }
    labels = claim_labels or {}
    seen_ids: set[str] = set()
    seen_claim_ids: set[str] = set()
    for raw in proposed:
        finding = dict(raw) if isinstance(raw, dict) else {}
        problems: list[str] = []
        receipt_updates: dict = {}
        check_id = str(finding.get("id") or "").strip()
        if not check_id:
            problems.append("check id is missing")
        elif not _SOURCE_ID.fullmatch(check_id):
            problems.append("check id is not stable or public-safe")
        elif check_id in seen_ids:
            problems.append(f"check id {check_id!r} is duplicated")
        verdict = finding.get("verdict")
        if verdict not in KNOWN_VERDICTS:
            problems.append("verdict is missing or unknown")
        claim_id = str(finding.get("claim_id") or "").strip()
        if not claim_id:
            problems.append("check has no claim_id")
        elif claim_id not in claim_ids:
            problems.append(f"claim_id {claim_id!r} is not in the ledger")
        elif claim_id in seen_claim_ids:
            problems.append(f"claim_id {claim_id!r} already has an accepted check")
        claim_label = str(labels.get(claim_id) or "").strip()
        if not claim_label:
            problems.append(f"claim_id {claim_id!r} has no public_label handoff")
        basis = str(finding.get("basis") or "").strip()
        if basis not in {"report", "evidence"}:
            problems.append("basis is missing or unknown")
        importance = str(finding.get("importance") or "").strip()
        if importance not in {"material", "supporting"}:
            problems.append("check importance is missing or unknown")
        if not str(finding.get("type") or "").strip():
            problems.append("check type is missing")
        finding.update({
            "id": check_id,
            "claim_id": claim_id,
            "basis": basis,
            "importance": importance,
        })
        if claim_id in (numeric_comparisons or {}):
            finding["numeric_comparison"] = copy.deepcopy(
                (numeric_comparisons or {})[claim_id])
        severity = finding.get("severity")
        if severity not in {None, "high", "medium", "low"}:
            problems.append("check severity is unknown")
        finding["severity"] = severity
        if not quote_in_text(finding.get("report_quote", ""), report):
            problems.append("report_quote not found in visible report text")
        if verdict == "changed_since_report" and basis != "evidence":
            problems.append(
                "changed_since_report requires an evidence receipt for the later value")
        if finding.get("current_source_kind") not in (None, ""):
            problems.append("current_source_kind is not accepted; source kind comes from sources")
        if finding.get("evidence_file") not in (None, "") or finding.get("evidence_files"):
            problems.append(
                "check evidence_file is not accepted; link public_receipt.source_id")

        public_raw = finding.get("public_receipt")
        source_id = str(
            ((public_raw or {}).get("source_id") or "")
            if isinstance(public_raw, dict) else ""
        ).strip()
        source = source_map.get(source_id)
        evidence = None
        if basis == "evidence":
            if source is not None:
                evidence, path_problem = evidence_path(
                    sandbox, source.get("evidence_file"), report_path)
                if path_problem:
                    problems.append(path_problem)
                else:
                    receipt_updates.update({
                        "source_id": source_id,
                        "evidence_mode": source.get("kind"),
                        "evidence_file": source.get("evidence_file"),
                    })
        if basis == "evidence" and verdict in EVIDENCE_RECEIPT_VERDICTS:
            json_receipts = finding.get("evidence_json")
            evidence_quote = str(finding.get("evidence_quote") or "").strip()
            if json_receipts not in (None, []) and not isinstance(json_receipts, list):
                problems.append("evidence_json is not a list")
                json_receipts = []
            json_receipts = json_receipts or []
            if json_receipts and evidence_quote:
                problems.append("declare either evidence_json or evidence_quote, not both")
            if evidence is not None and json_receipts:
                matched, canonical = json_pointer_receipt(evidence, json_receipts)
                if matched:
                    receipt_updates.update({
                        "evidence_receipt_mode": "json-pointers",
                        "evidence_json": canonical,
                        "evidence_quote": None,
                    })
                else:
                    problems.append("JSON pointer receipt did not match the retained source")
            elif evidence is not None and evidence_quote:
                if quote_in_text(evidence_quote, load_text(evidence)):
                    receipt_updates.update({
                        "evidence_receipt_mode": "exact-quote",
                        "evidence_quote": evidence_quote,
                    })
                else:
                    problems.append(
                        "evidence receipt needs exact pointers or a grounded exact quote")
            elif evidence is not None:
                problems.append(
                    "evidence receipt needs exact pointers or a grounded exact quote")
        elif basis == "report" and (
            finding.get("evidence_json") or finding.get("evidence_quote")
        ):
            problems.append("report-basis check must not declare evidence receipts")

        population_alignment = (population_alignments or {}).get(claim_id)
        if population_alignment is not None:
            receipt_updates["population_alignment"] = copy.deepcopy(
                population_alignment)

        if verdict == "changed_since_report":
            reconstruction = str(finding.get("reconstruction_attempt") or "").strip()
            if not reconstruction:
                problems.append("changed_since_report has no reconstruction attempt")
            else:
                reconstruction_problem = _public_text_problem(reconstruction)
                if reconstruction_problem:
                    problems.append(
                        f"changed_since_report reconstruction_attempt {reconstruction_problem}")
            report_value = finding.get("report_value")
            current_value = finding.get("current_value")
            current_as_of = str(finding.get("current_as_of") or "").strip()
            canonical_report_date = str(finding.get("report_date") or report_date or "").strip()
            finding["report_date"] = canonical_report_date
            date_receipt, date_problems = validate_date_receipt(
                evidence, finding.get("date_receipt"), current_as_of)
            problems.extend(date_problems)
            if date_receipt is not None:
                receipt_updates["date_receipt"] = date_receipt

        public_receipt, public_problems = _validate_public_receipt(
            finding, report, receipt_updates, source_map, claim_label,
            explicit_operand_values=(explicit_operand_values or {}).get(claim_id))
        problems.extend(public_problems)
        if public_receipt is not None:
            receipt_updates["public_receipt"] = public_receipt

        if verdict == "changed_since_report":
            report_value = finding.get("report_value")
            current_value = finding.get("current_value")
            current_as_of = str(finding.get("current_as_of") or "").strip()
            canonical_report_date = str(finding.get("report_date") or report_date or "").strip()
            if report_value in (None, ""):
                problems.append("changed_since_report has no report value")
            if current_value in (None, ""):
                problems.append("changed_since_report has no current value")
            if not current_as_of:
                problems.append("changed_since_report has no current as-of date")
            if not canonical_report_date:
                problems.append("changed_since_report has no report date")
            if report_value not in (None, "") and not explicit_value_in_quote(
                report_value, str(finding.get("report_quote") or "")
            ):
                problems.append(
                    "changed_since_report report value is not visible in report_quote")
            if values_equal(report_value, current_value):
                problems.append("changed_since_report current value equals the report value")
            resolved_values = _resolved_receipt_values(finding, receipt_updates)
            evidence_quote = str(receipt_updates.get("evidence_quote") or "")
            current_grounded = _value_in(current_value, resolved_values)
            if not current_grounded and evidence_quote:
                current_grounded = explicit_value_in_quote(current_value, evidence_quote)
            if current_value not in (None, "") and not current_grounded:
                problems.append("current_value does not match the receipt")
            receipt = receipt_updates.get("public_receipt") or {}
            if receipt:
                report_operand = receipt.get("report_operand") or {}
                if report_value not in (None, "") and not values_equal(
                    report_value, report_operand.get("value")
                ):
                    problems.append("report_value does not match the public report operand")
                decisive_values = [
                    row.get("value") for row in receipt.get("decisive_operands") or []
                    if isinstance(row, dict)
                ]
                if current_value not in (None, "") and not _value_in(
                    current_value, decisive_values
                ):
                    problems.append("current_value is not a decisive public operand")
                if canonical_report_date and not _value_in(
                    canonical_report_date, decisive_values
                ):
                    problems.append("report_date is not a decisive public operand")
                if current_as_of and not _value_in(current_as_of, decisive_values):
                    problems.append("current_as_of is not a decisive public operand")
            report_day = parse_date(canonical_report_date)
            current_day = parse_date(current_as_of)
            if canonical_report_date and report_day is None:
                problems.append("report_date is not a recognized date")
            if current_as_of and current_day is None:
                problems.append("current_as_of is not a recognized date")
            if report_day is not None and current_day is not None and current_day <= report_day:
                problems.append("current_as_of is not later than report_date")

        canonical = {**finding, **receipt_updates}
        if problems:
            discarded.append({**canonical, "problems": problems})
        else:
            seen_ids.add(check_id)
            seen_claim_ids.add(claim_id)
            validated.append(canonical)
    return validated, discarded


def parse_date(value) -> date | None:
    """Parse an ISO day or a month-name day. Time-of-day text is ignored."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, date) and not hasattr(value, "hour"):
        return value
    text = str(value).strip()
    if not text:
        return None
    match = _DATE.search(text)
    if match:
        year, month, day = (int(part) for part in match.group(0).split("-"))
        try:
            return date(year, month, day)
        except ValueError:
            return None
    match = _NAMED_DATE.search(text)
    if match:
        month = _MONTHS.get(match.group(1).lower())
        if month:
            try:
                return date(int(match.group(3)), month, int(match.group(2)))
            except ValueError:
                return None
    match = _DAY_MONTH_DATE.search(text)
    if match:
        month = _MONTHS.get(match.group(2).lower())
        if month:
            try:
                return date(int(match.group(3)), month, int(match.group(1)))
            except ValueError:
                return None
    return None


def attach_claim_outcomes(claims: list, checks: list) -> list:
    by_claim: dict[str, list] = {}
    for check in checks:
        by_claim.setdefault(str(check.get("claim_id") or ""), []).append(check)
    out = []
    for claim in claims:
        options = by_claim.get(claim["id"]) or []
        if len(options) != 1:
            out.append({**claim, "outcome": "not_reached", "check_id": None})
            continue
        best = options[0]
        out.append({
            **claim,
            "outcome": best.get("verdict"),
            "check_id": best.get("id"),
        })
    return out


def semantic_status(claims: list, checks: list, error: str | None = None) -> str:
    if error:
        return "failed"
    material = [row for row in claims if row.get("importance") == "material"]
    if not checks:
        if material:
            return "not_run"
        if any(row.get("classification") == "supporting_provenance" for row in claims):
            return "complete"
        return "not_run"
    pool = material or [
        row for row in claims
        if row.get("classification") != "supporting_provenance"]
    if not pool:
        return "complete"
    if all(row.get("outcome") not in (None, "not_reached") for row in pool):
        return "complete"
    return "partial"


def _check_ids_of(item) -> list[str]:
    if not isinstance(item, dict):
        return []
    raw = item.get("check_ids")
    if raw is None:
        raw = item.get("check_id")
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw.strip()] if raw.strip() else []
    if isinstance(raw, list):
        return [str(value).strip() for value in raw if str(value).strip()]
    return []


def _ids_problem(ids: list[str], accepted: set[str], label: str) -> str | None:
    if not ids:
        return f"{label} has no check ids"
    unknown = [item for item in ids if item not in accepted]
    if unknown:
        return f"{label} references unknown check id {unknown[0]!r}"
    return None


def validate_presentation(doc, report: str,
                          accepted_ids: set[str] | None = None, *,
                          accepted_checks: list[dict] | None = None,
                          resolutions: dict[str, dict] | None = None,
                          claim_ancestors: dict[str, list[str]] | None = None,
                          source_consideration: list[dict] | None = None,
                          ) -> tuple[dict | None, list[str]]:
    if not isinstance(doc, dict) or "presentation" not in doc:
        return None, ["presentation is missing"]
    pres = doc.get("presentation")
    if pres is None:
        return None, ["presentation is missing"]
    problems = []
    if not isinstance(pres, dict):
        return None, ["presentation is not an object"]
    accepted = accepted_ids or set()
    check_rows = [
        row for row in (accepted_checks or []) if isinstance(row, dict)]
    checks_by_id = {
        str(row.get("id") or "").strip(): row for row in check_rows
        if str(row.get("id") or "").strip()
    }
    if accepted_checks is None:
        problems.append("presentation accepted check ledger is missing")
    summary = pres.get("summary")
    if summary is not None and not isinstance(summary, str):
        problems.append("presentation.summary is not a string")
        summary = None
    summary_text = str(summary or "").strip()
    summary_ids = _check_ids_of(pres)
    if not _substantive_explanation(summary_text):
        problems.append("presentation.summary is missing or not substantive")
    elif len(re.findall(r"[A-Za-z0-9%$]+", summary_text)) > 45:
        problems.append("presentation.summary is not concise")
    id_problem = _ids_problem(summary_ids, accepted, "presentation.summary")
    if id_problem:
        problems.append(id_problem)
    if len(summary_ids) != len(set(summary_ids)):
        problems.append("presentation.summary check ids are duplicated")
    confirmed_ids = {
        check_id for check_id, row in checks_by_id.items()
        if row.get("verdict") == "confirmed"
    }
    if confirmed_ids and not (confirmed_ids & set(summary_ids)):
        problems.append(
            "presentation must select at least one visible confirmed check")
    actions = pres.get("actions") or []
    limits = pres.get("limits") or []
    cleaned_actions = []
    cleaned_limits = []
    for name, items, bucket in (
        ("actions", actions, cleaned_actions),
        ("limits", limits, cleaned_limits),
    ):
        if not isinstance(items, list):
            problems.append(f"presentation.{name} is not a list")
            continue
        for index, item in enumerate(items):
            label = f"presentation.{name}[{index}]"
            if not isinstance(item, dict):
                problems.append(f"{label} is not an object")
                continue
            text = str(item.get("text") or "").strip()
            quote = str(item.get("report_quote") or "").strip()
            item_id = str(item.get("id") or "")
            if not text or not quote:
                problems.append(f"{label} is incomplete")
                continue
            if name == "actions" and not re.fullmatch(r"A[0-9]+", item_id):
                problems.append(f"{label} id is invalid")
                continue
            if not quote_in_text(quote, report):
                problems.append(f"{label} report_quote not found in visible report text")
                continue
            ids = _check_ids_of(item)
            id_problem = _ids_problem(ids, accepted, label)
            if id_problem:
                problems.append(id_problem)
                continue
            if len(ids) != len(set(ids)):
                problems.append(f"{label} check ids are duplicated")
                continue
            if not _substantive_explanation(text):
                problems.append(f"{label}.text is not substantive or public-safe")
                continue
            cleaned = {
                "id": item_id or f"{name[:1].upper()}{index + 1}",
                "text": text,
                "report_quote": quote,
                "check_ids": ids,
            }
            if name == "actions":
                kind = str(item.get("kind") or "").strip()
                if kind not in ACTION_KINDS:
                    problems.append(f"{label}.kind is missing or unknown")
                    continue
                cited_checks = [checks_by_id[item_id] for item_id in ids]
                resolution_ids = _listed_ids(
                    item.get("resolution_ids"),
                    f"{label}.resolution_ids", problems)
                resolution_map = resolutions or {}
                for resolution_id in resolution_ids:
                    if resolution_id not in resolution_map:
                        problems.append(
                            f"{label}.resolution_ids references unknown claim "
                            f"resolution {resolution_id!r}")
                cited_claim_ids = {
                    str(row.get("claim_id") or "") for row in cited_checks
                }
                cited_resolutions = [
                    resolution_map.get(claim_id) or {}
                    for claim_id in cited_claim_ids
                ]
                for claim_id in sorted(cited_claim_ids):
                    if claim_id not in resolution_ids:
                        problems.append(
                            f"{label}.resolution_ids omits cited claim {claim_id!r}")
                    for ancestor_id in (claim_ancestors or {}).get(claim_id) or []:
                        if ancestor_id not in resolution_ids:
                            problems.append(
                                f"{label} resolution_ids omit dependency ancestor "
                                f"{ancestor_id!r}")
                unreconciled = [
                    row for row in cited_checks
                    if (row.get("population_alignment") or {}).get("status")
                    == "unreconciled"
                ]
                if kind == "correct_report":
                    if unreconciled:
                        problems.append(
                            f"{label} cannot use correct_report for an "
                            "unreconciled population")
                    if any(row.get("verdict") != "contradicted" for row in cited_checks):
                        problems.append(
                            f"{label} correct_report is not supported only by "
                            "accepted contradictions")
                    for claim_id in sorted(cited_claim_ids):
                        resolution = resolution_map.get(claim_id) or {}
                        if resolution.get("required_action_kind") != "correct_report":
                            problems.append(
                                f"{label} correct_report does not match claim "
                                f"resolution {claim_id!r}")
                        closure = {
                            claim_id, *((claim_ancestors or {}).get(claim_id) or [])}
                        conflicting = [
                            row for row in (source_consideration or [])
                            if row.get("claim_id") in closure
                            and row.get("verifier_decision") == "unreconciled"
                        ]
                        if conflicting:
                            problems.append(
                                f"{label} cannot correct_report with an unresolved "
                                f"source conflict for claim {claim_id!r}")
                        for ancestor_id in sorted(closure - {claim_id}):
                            ancestor = resolution_map.get(ancestor_id) or {}
                            if ancestor.get("final_verdict") in {
                                "not_checkable", "changed_since_report",
                            }:
                                problems.append(
                                    f"{label} cannot correct_report with unresolved "
                                    f"ancestor {ancestor_id!r}")
                elif kind == "reconcile_before_change":
                    if any(
                        row.get("required_action_kind") != "reconcile_before_change"
                        or row.get("final_verdict") != "not_checkable"
                        for row in cited_resolutions
                    ):
                        problems.append(
                            f"{label} reconcile_before_change does not match its "
                            "cited claim resolutions")
                    for row in unreconciled:
                        statement = str(
                            (row.get("population_alignment") or {}).get(
                                "reconciliation_action") or ""
                        ).strip()
                        if statement and not _public_literal_in(statement, text):
                            problems.append(
                                f"{label} does not include the exact reconciliation "
                                f"action for check {row.get('id')!r}")
                elif any(
                    row.get("required_action_kind") != "review_before_share"
                    for row in cited_resolutions
                ):
                    problems.append(
                        f"{label} review_before_share cannot stand in for a "
                        "correction or reconciliation action")
                cleaned["kind"] = kind
                cleaned["resolution_ids"] = resolution_ids
            bucket.append(cleaned)
    if not cleaned_actions:
        problems.append("presentation.actions has no accepted action")
    elif len({row["id"] for row in cleaned_actions}) != len(cleaned_actions):
        problems.append("presentation.actions ids are duplicated")
    for check in accepted_checks or []:
        if not isinstance(check, dict):
            continue
        check_id = str(check.get("id") or "").strip()
        notice = check.get("correction_notice")
        if isinstance(notice, dict):
            statement = str(notice.get("statement") or "").strip()
            if statement and not any(
                check_id in row["check_ids"]
                and _public_literal_in(statement, row["text"])
                for row in cleaned_actions
            ):
                problems.append(
                    "presentation.actions does not include the exact correction "
                    f"statement for check {check_id!r}")
        alignment = check.get("population_alignment")
        if not isinstance(alignment, dict) or alignment.get("status") != "unreconciled":
            continue
        reconciliation = str(alignment.get("reconciliation_action") or "").strip()
        if not any(
            row.get("kind") == "reconcile_before_change"
            and check_id in row["check_ids"]
            and _public_literal_in(reconciliation, row["text"])
            for row in cleaned_actions
        ):
            problems.append(
                "presentation.actions has no reconcile_before_change action "
                f"for check {check_id!r}")
    if problems and not summary_text and not cleaned_actions and not cleaned_limits:
        return None, problems
    return {
        "summary": summary_text,
        "check_ids": summary_ids,
        "actions": cleaned_actions,
        "limits": cleaned_limits,
    }, problems


def load_checks(path: pathlib.Path) -> tuple[list, dict | None]:
    doc = json.loads(path.read_text())
    if not isinstance(doc, dict):
        raise ValueError("checks file must be an object with checks and sources arrays")
    if not isinstance(doc.get("checks"), list):
        raise ValueError("checks file has no checks array")
    if not isinstance(doc.get("sources"), list):
        raise ValueError("checks file has no sources array")
    return doc["checks"], doc


def load_claims(path: pathlib.Path) -> list:
    claims, _meta = load_claims_bundle(path)
    return claims


def load_claims_bundle(path: pathlib.Path) -> tuple[list, dict]:
    doc = json.loads(path.read_text())
    meta = {}
    if isinstance(doc, list):
        return doc, meta
    if isinstance(doc, dict) and isinstance(doc.get("claims"), list):
        meta["contract_version"] = doc.get("contract_version")
        period = doc.get("report_period")
        date = doc.get("report_date")
        if isinstance(period, str) and period.strip():
            meta["report_period"] = period.strip()
        if isinstance(date, str) and date.strip():
            meta["report_date"] = date.strip()
        meta["coordinator"] = doc.get("coordinator")
        return doc["claims"], meta
    raise ValueError("claims file has no claims array")


def apply_host_classifications(ledger: list, discarded_claims: list,
                               inventory: dict, *,
                               structural_context: list[dict] | None = None,
                               material_inventory_claim_ids: dict | None = None
                               ) -> list:
    """Apply explicit host classifications; never derive them from content."""
    by_id = {
        str(item.get("id") or ""): item
        for item in (inventory.get("items") or [])
        if isinstance(item, dict) and item.get("id")
    }
    authorized = {
        str(inventory_id): {str(claim_id) for claim_id in claim_ids}
        for inventory_id, claim_ids in (material_inventory_claim_ids or {}).items()
        if isinstance(claim_ids, list)
    }
    used: dict[str, list[dict]] = {}
    kept: list[dict] = []
    assignments = [
        *(row for row in ledger if isinstance(row, dict)),
        *(row for row in (structural_context or []) if isinstance(row, dict)),
    ]
    structural_ids = {
        id(row) for row in (structural_context or []) if isinstance(row, dict)
    }
    for claim in assignments:
        problems = []
        classification = str(claim.get("classification") or "")
        ids = claim_inventory_ids(claim)
        if not ids:
            problems.append(f"{classification or 'classification'} requires inventory ids")
        if classification in {"supporting_provenance", "structural_context"} \
                and len(ids) != 1:
            problems.append(f"{classification} requires exactly one inventory id")
        for iid in ids:
            item = by_id.get(iid)
            if item is None:
                problems.append(f"inventory id {iid!r} is not in the inventory")
                continue
            previous = used.get(iid) or []
            if previous:
                claim_id = str(claim.get("id") or "")
                previous_ids = {str(row.get("id") or "") for row in previous}
                allowed = authorized.get(iid) or set()
                if not (
                    classification == "material_claim"
                    and all(
                        row.get("classification") == "material_claim"
                        for row in previous
                    )
                    and claim_id in allowed
                    and previous_ids <= allowed
                ):
                    problems.append(f"inventory id {iid!r} is assigned more than once")
                    continue
            if classification in {"supporting_provenance", "structural_context"}:
                shown = normalize(str(item.get("displayed") or item.get("quote") or ""))
                quote = normalize(str(claim.get("quote") or ""))
                if not quote or shown != quote:
                    problems.append(
                        f"{classification} quote is not the exact inventory text")
                if not _substantive_explanation(claim.get("reason")):
                    problems.append(
                        f"{classification} reason is missing or not substantive")
        if classification == "material_claim" and claim.get("importance") != "material":
            problems.append("material_claim requires importance material")
        if classification in {"supporting_provenance", "structural_context"} \
                and claim.get("importance") != "supporting":
            problems.append(f"{classification} requires importance supporting")
        if problems:
            dropped = {**claim, "problems": problems}
            discarded_claims.append(dropped)
        else:
            for iid in ids:
                used.setdefault(iid, []).append(claim)
                item = by_id[iid]
                item["classification"] = classification
                item["importance"] = (
                    "material" if classification == "material_claim" else "supporting")
            claim["importance"] = (
                "material" if classification == "material_claim" else "supporting")
            if id(claim) not in structural_ids:
                kept.append(claim)
    return kept


def attach_arithmetic_uses(ledger: list, validated: list, uses: list) -> tuple[list, list]:
    """Mark exact inventory ids as arithmetic inputs without creating verdicts."""
    if not uses:
        return validated, ledger
    used_inventory_ids: set[str] = set()
    for use in uses:
        if not isinstance(use, dict):
            continue
        for value in use.get("inventory_ids") or []:
            item = str(value or "").strip()
            if item:
                used_inventory_ids.add(item)
        for addend in use.get("addends") or []:
            if not isinstance(addend, dict):
                continue
            item = str(addend.get("inventory_id") or "").strip()
            if item:
                used_inventory_ids.add(item)
    if not used_inventory_ids:
        return validated, ledger
    for claim in ledger:
        if claim.get("classification") == "supporting_provenance":
            continue
        matched = sorted(set(claim_inventory_ids(claim)) & used_inventory_ids)
        if not matched:
            continue
        claim["arithmetic_inventory_ids"] = matched
    return validated, ledger


def _missing(path: pathlib.Path, label: str) -> int:
    print(f"accept: missing {label} {path}", file=sys.stderr)
    return 2


def _row_repair_reasons(rows: list[dict], label: str) -> list[str]:
    reasons: list[str] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            reasons.append(f"{label} at index {index} is not an object")
            continue
        if row.get("group_problem"):
            reasons.extend(str(problem) for problem in row.get("problems") or [])
            continue
        row_id = str(row.get("id") or "").strip()
        prefix = f"{label} {row_id!r}" if row_id else f"{label} at index {index}"
        for problem in row.get("problems") or []:
            reasons.append(f"{prefix} {problem}")
    return reasons


def _inventory_repair_reasons(rows: list[dict]) -> list[str]:
    """Serialize inventory reconciliation failures without leaking dict reprs."""
    reasons: list[str] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            reasons.append(f"inventory reconciliation row at index {index} is invalid")
            continue
        inventory_id = str(row.get("id") or "").strip()
        prefix = (
            f"inventory occurrence {inventory_id!r}"
            if inventory_id
            else f"inventory reconciliation row at index {index}"
        )
        claim_id = str(row.get("claim_id") or "").strip()
        if claim_id:
            prefix += f" assigned to {claim_id!r}"
        reason = str(row.get("reason") or "is uncovered").strip()
        reasons.append(f"{prefix}: {reason}")
    return reasons


def validate_check_assessment_bindings(checks: list[dict],
                                       assessments_by_id: dict[str, dict]
                                       ) -> list[str]:
    """Bind the one public receipt to the selected private assessment origins."""
    problems: list[str] = []
    for check in checks:
        if not isinstance(check, dict):
            continue
        check_id = str(check.get("id") or "")
        verdict = str(check.get("verdict") or "")
        if verdict == "not_checkable":
            continue
        receipt = check.get("public_receipt") or {}
        source_id = str(receipt.get("source_id") or "") if isinstance(receipt, dict) else ""
        effect = (
            "supports" if verdict == "confirmed"
            else "contradicts" if verdict == "contradicted"
            else "changed_since_report"
        )
        candidates = []
        for assessment_id in check.get("assessment_ids") or []:
            assessment = assessments_by_id.get(str(assessment_id or "")) or {}
            if assessment.get("effect") != effect:
                continue
            if check.get("basis") == "report" and assessment.get("basis") == "report":
                candidates.append(assessment)
            elif (
                check.get("basis") == "evidence"
                and assessment.get("basis") == "evidence"
                and assessment.get("source_id") == source_id
            ):
                candidates.append(assessment)
        if len(candidates) != 1:
            problems.append(
                f"customer check {check_id!r} must select exactly one decisive "
                "assessment for its public receipt")
            continue
        assessment = candidates[0]
        decisive = receipt.get("decisive_operands") or []
        resolved = assessment.get("resolved_operands") or {}
        for index, operand in enumerate(decisive):
            slot = f"decisive_operands/{index}"
            if slot not in resolved:
                problems.append(
                    f"customer check {check_id!r} public operand {index} has no "
                    "explicit assessment origin")
            elif not values_equal(
                (operand or {}).get("value") if isinstance(operand, dict) else None,
                resolved.get(slot),
            ):
                problems.append(
                    f"customer check {check_id!r} public operand {index} does not "
                    "match its explicit assessment origin")
        public_calculation = (
            receipt.get("calculation") if isinstance(receipt, dict) else None)
        private_calculation = assessment.get("calculation")
        if public_calculation is not None and public_calculation != private_calculation:
            problems.append(
                f"customer check {check_id!r} public calculation does not match "
                "its decisive assessment calculation")
    return list(dict.fromkeys(problems))


def validate_whole_source_exclusions(raw, sources: list[dict],
                                     pairs: list[dict]
                                     ) -> tuple[list[dict], list[str]]:
    """Expose only separately authored whole-source exclusions to Technical scope."""
    if not isinstance(raw, list):
        return [], ["whole_source_exclusions is missing or not an array"]
    source_ids = {
        str(row.get("id") or "") for row in sources if isinstance(row, dict)}
    decisions: dict[str, list[str]] = {source_id: [] for source_id in source_ids}
    for pair in pairs:
        if isinstance(pair, dict):
            decisions.setdefault(str(pair.get("source_id") or ""), []).append(
                str(pair.get("verifier_decision") or ""))
    fully_excluded = {
        source_id for source_id, values in decisions.items()
        if values and set(values) == {"exclude"}
    }
    problems: list[str] = []
    accepted: list[dict] = []
    seen: set[str] = set()
    for index, row in enumerate(raw):
        label = f"whole_source_exclusions[{index}]"
        if not isinstance(row, dict):
            problems.append(f"{label} is not an object")
            continue
        source_id = str(row.get("source_id") or "").strip()
        reason = str(row.get("reason") or "").strip()
        if source_id not in source_ids:
            problems.append(f"{label}.source_id {source_id!r} is not retained")
        if source_id in seen:
            problems.append(f"whole-source exclusion {source_id!r} is duplicated")
        seen.add(source_id)
        if source_id not in fully_excluded:
            problems.append(
                f"whole-source exclusion {source_id!r} is not excluded for every "
                "material claim")
        if not _substantive_explanation(reason):
            problems.append(f"{label}.reason is missing or not substantive")
        accepted.append({"source_id": source_id, "exclusion_reason": reason})
    for source_id in sorted(fully_excluded - seen):
        problems.append(
            f"fully excluded source {source_id!r} has no whole-source exclusion reason")
    return accepted, list(dict.fromkeys(problems))


def validate_acceptance_bundle(*, text: str, sandbox: pathlib.Path,
                               proposed: list, checks_doc: dict,
                               proposed_claims: list, claims_meta: dict,
                               inventory: dict, report_path: pathlib.Path,
                               arithmetic_uses: list | None = None,
                               bundle_root: pathlib.Path | None = None,
                               validation_stage: str = "full") -> dict:
    """Run the one side-effect-free validation path used by every CLI stage."""
    if validation_stage not in {"semantic_plan", "full"}:
        raise ValueError(f"unknown validation_stage {validation_stage!r}")
    digest = bundle_sha256(
        report_path=report_path, text=text, inventory=inventory,
        proposed_claims=proposed_claims, claims_meta=claims_meta,
        checks_doc=checks_doc, sandbox=sandbox)
    proposed = copy.deepcopy(proposed)
    checks_doc = copy.deepcopy(checks_doc if isinstance(checks_doc, dict) else {})
    proposed_claims = copy.deepcopy(proposed_claims)
    claims_meta = copy.deepcopy(claims_meta)
    inventory = copy.deepcopy(inventory)
    raw_inventory = copy.deepcopy(inventory)
    arithmetic_uses = copy.deepcopy(list(arithmetic_uses or []))
    bundle_root = pathlib.Path(bundle_root or report_path.parent)

    workflow_problems: list[str] = []
    if (
        claims_meta.get("contract_version") != WORKFLOW_VERSION
        or checks_doc.get("contract_version") != WORKFLOW_VERSION
    ):
        workflow_problems.append(
            f"private workflow version must be {WORKFLOW_VERSION}")
    if validation_stage == "full" and checks_doc.get("checks") != proposed:
        workflow_problems.append(
            "checks loader input does not match checks_doc.checks")
    for check in proposed:
        if not isinstance(check, dict):
            continue
        check_id = str(check.get("id") or "")
        if "numeric_comparison" in check:
            workflow_problems.append(
                f"customer check {check_id!r} numeric_comparison must be declared "
                "on its private assessment")
        if "population_alignment" in check:
            workflow_problems.append(
                f"customer check {check_id!r} population_alignment must be declared "
                "on its private assessment")

    coordinator_handoff, coordinator_problems = coordinator_preflight(
        proposed_claims, claims_meta.get("coordinator"), inventory, proposed,
        presentation_doc=checks_doc)
    proposed_sources = list((checks_doc or {}).get("sources") or [])
    accepted_sources, discarded_sources = validate_sources(
        sandbox, proposed_sources, report_path)
    grounded_claims, discarded_claims = validate_claims(text, proposed_claims)
    claim_ids = {row["id"] for row in grounded_claims}

    population_requirement_problems: list[str] = []
    for claim_id, requirements in (
        coordinator_handoff.get("population_requirements") or {}
    ).items():
        for requirement in requirements:
            quote = str(requirement.get("report_quote") or "")
            if not quote_in_text(quote, text):
                population_requirement_problems.append(
                    f"canonical claim {claim_id!r} population requirement "
                    f"{requirement.get('id')!r} report_quote is not visible")

    source_plan_problems = validate_source_plan_coverage(
        coordinator_handoff.get("source_consideration_plan"),
        accepted_sources, grounded_claims)
    if validation_stage == "semantic_plan":
        repair_reasons = list(workflow_problems)
        repair_reasons.extend(coordinator_problems)
        repair_reasons.extend(_row_repair_reasons(
            discarded_sources, "retained source"))
        repair_reasons.extend(_row_repair_reasons(
            discarded_claims, "canonical claim"))
        repair_reasons.extend(population_requirement_problems)
        repair_reasons.extend(source_plan_problems)
        repair_reasons = list(dict.fromkeys(repair_reasons))
        return {
            "status": "failed" if repair_reasons else "complete",
            "contract_version": WORKFLOW_VERSION,
            "validation_stage": "semantic_plan",
            "bundle_sha256": digest,
            "repair_reasons": repair_reasons,
            "coordinator": coordinator_handoff,
            "sources": accepted_sources,
            "discarded_sources": discarded_sources,
            "claims": grounded_claims,
            "discarded_claims": discarded_claims,
        }

    assessments, assessments_by_id, assessment_problems = validate_assessments(
        checks_doc.get("assessments"), handoff=coordinator_handoff,
        inventory=inventory, sources=accepted_sources, sandbox=sandbox,
        report_path=report_path, report=text)
    numeric_comparisons, numeric_policy_problems = (
        validate_assessment_numeric_policies(assessments, proposed))
    population_alignments: dict[str, dict] = {}
    explicit_values: dict[str, list] = {}
    for assessment in assessments:
        claim_id = str(assessment.get("claim_id") or "")
        explicit_values.setdefault(claim_id, []).extend(
            list((assessment.get("resolved_operands") or {}).values()))
    for check in proposed:
        if not isinstance(check, dict) or check.get("basis") != "evidence":
            continue
        claim_id = str(check.get("claim_id") or "")
        receipt = check.get("public_receipt") or {}
        source_id = str(
            receipt.get("source_id") if isinstance(receipt, dict) else "")
        choices = [
            assessment for assessment in assessments
            if assessment.get("claim_id") == claim_id
            and assessment.get("basis") == "evidence"
            and assessment.get("source_id") == source_id
            and isinstance(assessment.get("population_alignment"), dict)
        ]
        if len(choices) == 1:
            population_alignments[claim_id] = choices[0]["population_alignment"]

    validated, discarded = validate_receipts(
        text, sandbox, proposed, claim_ids, report_path,
        sources=accepted_sources,
        claim_labels={row["id"]: row["public_label"] for row in grounded_claims},
        report_date=claims_meta.get("report_date"),
        report_period=claims_meta.get("report_period"),
        numeric_comparisons=numeric_comparisons,
        population_alignments=population_alignments,
        explicit_operand_values=explicit_values)
    binding_problems = validate_check_assessment_bindings(
        validated, assessments_by_id)
    resolutions, resolution_by_claim, resolution_problems = validate_resolutions(
        checks_doc.get("resolutions"), assessments=assessments,
        handoff=coordinator_handoff, checks=validated)
    source_consideration, source_consideration_problems = (
        validate_source_consideration(
            (checks_doc or {}).get("source_consideration"),
            accepted_sources,
            grounded_claims,
            validated,
            assessments=assessments,
            coordinator_plan=coordinator_handoff.get(
                "source_consideration_plan"),
        )
    )
    whole_source_exclusions, whole_source_exclusion_problems = (
        validate_whole_source_exclusions(
            checks_doc.get("whole_source_exclusions"),
            accepted_sources, source_consideration))
    ledger = attach_claim_outcomes(grounded_claims, validated)
    ledger = apply_host_classifications(
        ledger, discarded_claims, inventory,
        structural_context=coordinator_handoff["structural_context"],
        material_inventory_claim_ids=(
            coordinator_handoff["material_inventory_claim_ids"]),
    )
    validated, ledger = attach_arithmetic_uses(
        ledger, validated, list(arithmetic_uses or []))
    inventory_cover = cover(
        inventory, ledger,
        structural_context=coordinator_handoff["structural_context"],
        material_inventory_claim_ids=(
            coordinator_handoff["material_inventory_claim_ids"]),
    )
    accepted_ids = {
        str(row.get("id") or "").strip() for row in validated if row.get("id")}
    presentation, presentation_problems = validate_presentation(
        checks_doc, text, accepted_ids, accepted_checks=validated,
        resolutions=resolution_by_claim,
        claim_ancestors=coordinator_handoff.get("claim_ancestors"),
        source_consideration=source_consideration)
    role_provenance, role_provenance_problems = validate_role_provenance(
        checks_doc.get("role_provenance"), bundle_root,
        evidence_root=sandbox,
        expected_workflow={
            "inventory": raw_inventory,
            "report_metadata": {
                key: claims_meta[key] for key in ("report_period", "report_date")
                if key in claims_meta and claims_meta.get(key) is not None
            },
            "canonical_claims": proposed_claims,
            "coordinator": claims_meta.get("coordinator"),
            "sources": proposed_sources,
            "assessments": checks_doc.get("assessments"),
            "source_consideration": checks_doc.get("source_consideration"),
            "whole_source_exclusions": checks_doc.get(
                "whole_source_exclusions"),
            "resolutions": checks_doc.get("resolutions"),
            "checks": checks_doc.get("checks"),
            "presentation": checks_doc.get("presentation"),
        })
    material_ledger = [
        row for row in ledger
        if row.get("classification") != "supporting_provenance"
        and row.get("importance") != "supporting"
    ]
    material_claim_ids = {
        str(row.get("id") or "") for row in material_ledger if row.get("id")
    }
    material_proposed = [
        row for row in proposed
        if str(row.get("claim_id") or "") in material_claim_ids
    ]
    material_validated = [
        row for row in validated
        if str(row.get("claim_id") or "") in material_claim_ids
    ]

    repair_reasons = list(workflow_problems)
    repair_reasons.extend(coordinator_problems)
    repair_reasons.extend(_row_repair_reasons(
        discarded_sources, "retained source"))
    repair_reasons.extend(_row_repair_reasons(
        discarded_claims, "canonical claim"))
    repair_reasons.extend(_row_repair_reasons(
        discarded, "evidence-verifier check"))
    repair_reasons.extend(population_requirement_problems)
    repair_reasons.extend(source_plan_problems)
    repair_reasons.extend(assessment_problems)
    repair_reasons.extend(numeric_policy_problems)
    repair_reasons.extend(binding_problems)
    repair_reasons.extend(resolution_problems)
    repair_reasons.extend(source_consideration_problems)
    repair_reasons.extend(whole_source_exclusion_problems)
    repair_reasons.extend(presentation_problems)
    repair_reasons.extend(role_provenance_problems)
    repair_reasons.extend(sorted(
        _inventory_repair_reasons(inventory_cover["missing"])
    ))
    repair_reasons = list(dict.fromkeys(repair_reasons))

    payload = {
        "status": "failed" if repair_reasons else "complete",
        "contract_version": WORKFLOW_VERSION,
        "bundle_sha256": digest,
        "repair_reasons": repair_reasons,
        "checks": validated,
        "validated": validated,
        "discarded": discarded,
        "sources": accepted_sources,
        "discarded_sources": discarded_sources,
        "source_consideration": source_consideration,
        "source_consideration_problems": source_consideration_problems,
        "whole_source_exclusions": whole_source_exclusions,
        "assessments": assessments,
        "assessments_by_id": assessments_by_id,
        "resolutions": resolutions,
        "resolution_by_claim": resolution_by_claim,
        "role_provenance": role_provenance,
        "proposed": len(material_proposed),
        "grounded": len(material_validated),
        "claims": ledger,
        "discarded_claims": discarded_claims,
        "claims_in_ledger": len(material_ledger),
        "supporting_claims": len(ledger) - len(material_ledger),
        "claims_reached_by_a_check": sum(
            1 for row in material_ledger
            if row.get("outcome") not in (None, "not_reached")
        ),
        "semantic_status": semantic_status(
            ledger, validated,
            error="acceptance validation failed" if repair_reasons else None,
        ),
        "presentation": presentation,
        "presentation_problems": presentation_problems,
        "report_period": claims_meta.get("report_period"),
        "report_date": claims_meta.get("report_date"),
        "inventory": inventory,
        "inventory_missing": inventory_cover["missing"],
        "extractor_checkable_fraction": inventory_cover["extractor_fraction"],
        "engine_checkable_fraction": inventory_cover["engine_fraction"],
        "coordinator": coordinator_handoff,
        "structural_context_count": len(coordinator_handoff["structural_context"]),
    }
    if coordinator_problems:
        payload["discarded_claims"].append({
            "id": "coordinator",
            "quote": "",
            "public_label": "",
            "importance": "supporting",
            "classification": "structural_context",
            "problems": coordinator_problems,
        })
    return payload


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--report", required=True, type=pathlib.Path)
    ap.add_argument("--checks", required=True, type=pathlib.Path)
    ap.add_argument("--claims", required=True, type=pathlib.Path)
    ap.add_argument("--out", required=True, type=pathlib.Path)
    ap.add_argument("--evidence-dir", type=pathlib.Path, default=None)
    ap.add_argument("--report-text", type=pathlib.Path, default=None)
    ap.add_argument("--findings", type=pathlib.Path, default=None)
    stage_group = ap.add_mutually_exclusive_group()
    stage_group.add_argument(
        "--semantic-plan-only", action="store_true",
        help="validate the coordinator semantic plan before verifier fan-out",
    )
    stage_group.add_argument(
        "--preflight-only", action="store_true",
        help="validate role handoffs and return exact repair reasons before acceptance",
    )
    ap.add_argument(
        "--preflight-record", type=pathlib.Path, default=None,
        help="complete preflight.json whose exact bundle digest final acceptance must match",
    )
    args = ap.parse_args()

    if not args.report.is_file():
        return _missing(args.report, "report")
    if not args.checks.is_file():
        return _missing(args.checks, "checks")
    if not args.claims.is_file():
        return _missing(args.claims, "claims")
    if args.findings is not None and not args.findings.is_file():
        return _missing(args.findings, "findings")
    sidecar = args.report_text
    if sidecar is not None and not sidecar.is_file():
        if needs_sidecar(args.report):
            return _missing(sidecar, "report-text")
        sidecar = None
    if sidecar is None and needs_sidecar(args.report):
        print(
            "accept: this format needs --report-text with visible report text.",
            file=sys.stderr,
        )
        return 2

    try:
        proposed, checks_doc = load_checks(args.checks)
        proposed_claims, claims_meta = load_claims_bundle(args.claims)
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"accept: {exc}", file=sys.stderr)
        return 2

    sandbox = args.evidence_dir if args.evidence_dir is not None else args.report.parent
    text = report_text(args.report, sidecar)
    if not text:
        print(
            "accept: no visible report text. Write report-visible.txt and pass --report-text.",
            file=sys.stderr,
        )
        return 2

    inventory = None
    arithmetic_uses: list = []
    if args.findings is not None and args.findings.is_file():
        try:
            findings_doc = json.loads(args.findings.read_text())
            inventory = findings_doc.get("inventory")
            arithmetic_uses = list(findings_doc.get("arithmetic_uses") or [])
        except (OSError, json.JSONDecodeError, TypeError):
            inventory = None
            arithmetic_uses = []
    if not isinstance(inventory, dict):
        inventory = inventory_for(args.report)

    payload = validate_acceptance_bundle(
        text=text, sandbox=sandbox, proposed=proposed, checks_doc=checks_doc,
        proposed_claims=proposed_claims, claims_meta=claims_meta,
        inventory=inventory, report_path=args.report,
        arithmetic_uses=arithmetic_uses,
        bundle_root=args.checks.parent,
        validation_stage=(
            "semantic_plan" if args.semantic_plan_only else "full"))
    if args.semantic_plan_only:
        semantic_plan = {
            "contract_version": WORKFLOW_VERSION,
            "status": payload["status"],
            "validation_stage": "semantic_plan",
            "bundle_sha256": payload["bundle_sha256"],
            "repair_reasons": payload["repair_reasons"],
            "coordinator": payload["coordinator"],
        }
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(semantic_plan, indent=2) + "\n")
        print(
            f"semantic-plan preflight: {len(payload['repair_reasons'])} "
            "repair reason(s)"
        )
        for reason in payload["repair_reasons"]:
            print(f"  REPAIR {reason}")
        return 2 if payload["repair_reasons"] else 0
    if args.preflight_only:
        preflight = {
            "contract_version": WORKFLOW_VERSION,
            "status": payload["status"],
            "bundle_sha256": payload["bundle_sha256"],
            "repair_reasons": payload["repair_reasons"],
            "coordinator": payload["coordinator"],
        }
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(preflight, indent=2) + "\n")
        print(
            f"preflight: {len(payload['repair_reasons'])} repair reason(s)"
        )
        for reason in payload["repair_reasons"]:
            print(f"  REPAIR {reason}")
        return 2 if payload["repair_reasons"] else 0
    parity_reasons: list[str] = []
    preflight_record = None
    if args.preflight_record is None:
        parity_reasons.append("final acceptance requires --preflight-record")
    elif not args.preflight_record.is_file():
        parity_reasons.append("final acceptance preflight record is missing")
    else:
        try:
            preflight_record = json.loads(args.preflight_record.read_text())
        except (OSError, json.JSONDecodeError):
            parity_reasons.append("final acceptance preflight record is invalid")
        if isinstance(preflight_record, dict):
            if preflight_record.get("contract_version") != WORKFLOW_VERSION:
                parity_reasons.append(
                    "final acceptance preflight record has the wrong private workflow version")
            if preflight_record.get("status") != "complete" \
                    or preflight_record.get("repair_reasons") != []:
                parity_reasons.append(
                    "final acceptance preflight record is not complete with zero reasons")
            if preflight_record.get("bundle_sha256") != payload["bundle_sha256"]:
                parity_reasons.append(
                    "final acceptance bundle digest does not match preflight")
    if parity_reasons:
        payload["repair_reasons"] = list(dict.fromkeys([
            *payload["repair_reasons"], *parity_reasons,
        ]))
        payload["status"] = "failed"
        payload["semantic_status"] = "failed"
    payload["preflight_parity"] = {
        "matched": not parity_reasons,
        "record": (
            args.preflight_record.name if args.preflight_record is not None else None),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n")
    print(
        f"accept: {payload['grounded']} grounded, {len(payload['discarded'])} discarded "
        f"of {payload['proposed']}; "
        f"ledger {payload['claims_reached_by_a_check']} of {payload['claims_in_ledger']}"
    )
    for row in payload["discarded_claims"]:
        print(f"  DISCARDED CLAIM {row.get('id')}: {'; '.join(row.get('problems') or [])}")
    for row in payload["discarded_sources"]:
        print(f"  DISCARDED SOURCE {row.get('id')}: {'; '.join(row.get('problems') or [])}")
    for row in payload["discarded"]:
        print(f"  DISCARDED {row.get('id')}: {'; '.join(row.get('problems') or [])}")
    return 2 if payload["repair_reasons"] else 0


if __name__ == "__main__":
    sys.exit(main())
