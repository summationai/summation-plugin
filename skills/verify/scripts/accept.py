#!/usr/bin/env python3
"""Keep or drop proposed checks by grounding them in the report and evidence.

A check survives when its quotes and pointers resolve. A bad row is discarded.
Preflight and acceptance use the same validation result and exact repair reasons.

Usage:
    accept.py --report <file> --checks checks.json --claims claims.json
              --out receipts.json [--evidence-dir DIR] [--report-text visible.txt]
"""
from __future__ import annotations

import argparse
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


def validate_population_alignment(finding: dict, report: str,
                                  evidence: pathlib.Path | None, *,
                                  report_date: str | None = None,
                                  report_period: str | None = None
                                  ) -> tuple[dict | None, list[str]]:
    """Validate host-declared population judgment through exact receipts only."""
    raw = finding.get("population_alignment")
    basis = str(finding.get("basis") or "")
    verdict = str(finding.get("verdict") or "")
    dated = bool(str(report_date or "").strip() or str(report_period or "").strip())
    if raw is None:
        if basis == "evidence" and verdict == "contradicted" and dated:
            return None, ["dated evidence contradiction requires population_alignment"]
        if basis == "evidence" and verdict == "confirmed" and dated:
            return None, ["dated evidence confirmation requires population_alignment"]
        return None, []
    if basis != "evidence":
        return None, ["population_alignment is allowed only for evidence-basis checks"]
    if not isinstance(raw, dict):
        return None, ["population_alignment is not an object"]
    status = str(raw.get("status") or "").strip()
    reason = str(raw.get("reason") or "").strip()
    problems: list[str] = []
    if not _substantive_explanation(reason):
        problems.append("population_alignment.reason is missing or not substantive")
    if status == "same_population":
        unknown = sorted(set(raw) - {"status", "reason", "links"})
        if unknown:
            problems.append(
                f"population_alignment has unknown field {unknown[0]!r}")
        links = raw.get("links")
        if not isinstance(links, list) or not links:
            problems.append("population_alignment.links is missing or empty")
            links = []
        canonical_links: list[dict] = []
        for index, link in enumerate(links):
            label = f"population_alignment.links[{index}]"
            if not isinstance(link, dict):
                problems.append(f"{label} is not an object")
                continue
            unknown_link = sorted(
                set(link) - {"dimension", "report_quote", "source_receipt"})
            if unknown_link:
                problems.append(
                    f"{label} has unknown field {unknown_link[0]!r}")
            dimension = str(link.get("dimension") or "").strip()
            report_quote = str(link.get("report_quote") or "").strip()
            if dimension not in POPULATION_DIMENSIONS:
                problems.append(f"{label}.dimension is missing or unknown")
            if not quote_in_text(report_quote, report):
                problems.append(f"{label}.report_quote not found in visible report text")
            source_receipt, receipt_problems = validate_exact_source_receipt(
                evidence, link.get("source_receipt"), f"{label}.source_receipt")
            problems.extend(receipt_problems)
            clean = {
                "dimension": dimension,
                "report_quote": report_quote,
                "source_receipt": source_receipt,
            }
            canonical_links.append(clean)
        canonical = {
            "status": status, "reason": reason, "links": canonical_links,
        }
    elif status == "unreconciled":
        unknown = sorted(set(raw) - {
            "status", "reason", "missing_dimensions", "conflict_receipts",
            "reconciliation_action",
        })
        if unknown:
            problems.append(
                f"population_alignment has unknown field {unknown[0]!r}")
        dimensions = raw.get("missing_dimensions")
        if not isinstance(dimensions, list) or not dimensions:
            problems.append(
                "population_alignment.missing_dimensions is missing or empty")
            dimensions = []
        clean_dimensions = [str(value or "").strip() for value in dimensions]
        if len(clean_dimensions) != len(set(clean_dimensions)):
            problems.append("population_alignment.missing_dimensions is duplicated")
        for index, dimension in enumerate(clean_dimensions):
            if dimension not in POPULATION_DIMENSIONS:
                problems.append(
                    f"population_alignment.missing_dimensions[{index}] is unknown")
        receipts = raw.get("conflict_receipts")
        if not isinstance(receipts, list) or not receipts:
            problems.append(
                "population_alignment.conflict_receipts is missing or empty")
            receipts = []
        canonical_receipts: list[dict] = []
        for index, receipt in enumerate(receipts):
            canonical_receipt, receipt_problems = validate_exact_source_receipt(
                evidence, receipt,
                f"population_alignment.conflict_receipts[{index}]")
            problems.extend(receipt_problems)
            if canonical_receipt is not None:
                canonical_receipts.append(canonical_receipt)
        reconciliation = str(raw.get("reconciliation_action") or "").strip()
        if not _substantive_explanation(reconciliation):
            problems.append(
                "population_alignment.reconciliation_action is missing or not substantive")
        if verdict != "not_checkable":
            problems.append(
                f"unreconciled population cannot have verdict {verdict!r}; "
                "use not_checkable")
        canonical = {
            "status": status,
            "reason": reason,
            "missing_dimensions": clean_dimensions,
            "conflict_receipts": canonical_receipts,
            "reconciliation_action": reconciliation,
        }
    else:
        return None, ["population_alignment.status is missing or unknown"]
    return canonical, problems


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
                                  checks: list[dict]) -> tuple[list[dict], list[str]]:
    """Validate only host-declared source-to-claim coverage and exclusions."""
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
    check_by_claim = {
        str(row.get("claim_id") or "").strip(): row for row in checks
        if isinstance(row, dict) and str(row.get("claim_id") or "").strip()
    }
    cited_claims_by_source: dict[str, set[str]] = {}
    for check in checks:
        if not isinstance(check, dict):
            continue
        source_id = str(
            ((check.get("public_receipt") or {}).get("source_id") or "")
            if isinstance(check.get("public_receipt"), dict) else ""
        ).strip()
        claim_id = str(check.get("claim_id") or "").strip()
        if source_id and claim_id:
            cited_claims_by_source.setdefault(source_id, set()).add(claim_id)

    accepted: list[dict] = []
    problems: list[str] = []
    seen: set[str] = set()
    for index, row in enumerate(raw):
        label = f"source_consideration[{index}]"
        if not isinstance(row, dict):
            problems.append(f"{label} is not an object")
            continue
        unknown = sorted(set(row) - {"source_id", "claim_ids", "exclusion_reason"})
        if unknown:
            problems.append(f"{label} has unknown field {unknown[0]!r}")
        source_id = str(row.get("source_id") or "").strip()
        if not source_id:
            problems.append(f"{label}.source_id is missing")
        elif source_id not in source_ids:
            problems.append(f"{label}.source_id {source_id!r} is not retained")
        elif source_id in seen:
            problems.append(f"source_consideration source {source_id!r} is duplicated")
        seen.add(source_id)
        has_claims = "claim_ids" in row
        has_exclusion = "exclusion_reason" in row
        if has_claims == has_exclusion:
            problems.append(
                f"{label} must contain exactly one claim_ids or exclusion_reason")
            continue
        if has_claims:
            claim_ids = row.get("claim_ids")
            if not isinstance(claim_ids, list) or not claim_ids:
                problems.append(f"{label}.claim_ids is missing or empty")
                claim_ids = []
            clean_ids = [str(value or "").strip() for value in claim_ids]
            if any(not value for value in clean_ids):
                problems.append(f"{label}.claim_ids contains an empty id")
            if len(clean_ids) != len(set(clean_ids)):
                problems.append(f"{label}.claim_ids is duplicated")
            for claim_id in clean_ids:
                if claim_id not in material_claim_ids:
                    problems.append(
                        f"{label}.claim_ids references unknown material claim {claim_id!r}")
                    continue
                check = check_by_claim.get(claim_id)
                cited_source_id = str(
                    ((check or {}).get("public_receipt") or {}).get("source_id") or ""
                ).strip()
                if cited_source_id != source_id:
                    problems.append(
                        f"source_consideration source {source_id!r} maps claim "
                        f"{claim_id!r} but its accepted check does not cite that source")
            actual = cited_claims_by_source.get(source_id) or set()
            if set(clean_ids) != actual:
                problems.append(
                    f"source_consideration source {source_id!r} claim_ids do not "
                    "match its accepted check citations")
            accepted.append({"source_id": source_id, "claim_ids": clean_ids})
        else:
            reason = str(row.get("exclusion_reason") or "").strip()
            if not _substantive_explanation(reason):
                problems.append(
                    f"{label}.exclusion_reason is missing or not substantive")
            if cited_claims_by_source.get(source_id):
                problems.append(
                    f"source_consideration source {source_id!r} is cited and cannot "
                    "also be excluded")
            accepted.append({
                "source_id": source_id,
                "exclusion_reason": reason,
            })
    for source_id in sorted(source_ids - seen):
        problems.append(
            f"accepted source {source_id!r} has no source_consideration row")
    return accepted, list(dict.fromkeys(problems))


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
                             claim_label: str) -> tuple[dict | None, list[str]]:
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
            grounded = explicit_value_in_quote(value, report_quote)
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


def _listed_ids(raw, label: str, problems: list[str]) -> list[str]:
    if not isinstance(raw, list) or not raw:
        problems.append(f"{label} is missing or not a non-empty array")
        return []
    out = [str(value or "").strip() for value in raw]
    if any(not value for value in out):
        problems.append(f"{label} contains an empty id")
    if len(out) != len(set(out)):
        problems.append(f"{label} contains a duplicate id")
    return [value for value in out if value]


def _member_ref(raw, label: str, problems: list[str]) -> tuple[str, str] | None:
    if not isinstance(raw, dict):
        problems.append(f"{label} is not an object")
        return None
    partition_id = str(raw.get("partition_id") or "").strip()
    candidate_id = str(raw.get("candidate_id") or "").strip()
    if not partition_id or not candidate_id:
        problems.append(f"{label} is missing partition_id or candidate_id")
        return None
    return partition_id, candidate_id


def _clause_ref(raw, label: str, problems: list[str], *,
                required: bool) -> tuple[str, str, str | None] | None:
    ref = _member_ref(raw, label, problems)
    if ref is None:
        return None
    clause_id = str((raw or {}).get("clause_id") or "").strip()
    if required and not clause_id:
        problems.append(f"{label}.clause_id is missing")
        return None
    if not required and clause_id:
        problems.append(f"{label}.clause_id is not allowed for a non-material candidate")
    return ref[0], ref[1], clause_id or None


def _public_literal_in(value, text) -> bool:
    literal = normalize(str(value or ""))
    return bool(literal) and literal in normalize(str(text or ""))


def validate_coordinator_handoff(canonical_claims, coordinator,
                                 inventory: dict) -> tuple[dict, list[str]]:
    """Validate explicit worker membership and verifier ownership by ids only."""
    handoff = {
        "membership": [],
        "structural_context": [],
        "material_claim_ids": [],
        "material_claim_clause_refs": {},
        "material_claim_inventory_ids": {},
        "material_inventory_claim_ids": {},
        "verifier_assignments": [],
    }
    problems: list[str] = []
    if not isinstance(canonical_claims, list):
        return handoff, ["canonical claims are not an array"]
    if not isinstance(coordinator, dict):
        return handoff, ["coordinator handoff is missing or not an object"]
    partitions = coordinator.get("partition_results")
    membership = coordinator.get("membership")
    verifier_assignments = coordinator.get("verifier_assignments")
    if not isinstance(partitions, list):
        problems.append("coordinator.partition_results is not an array")
        partitions = []
    if not isinstance(membership, list):
        problems.append("coordinator.membership is not an array")
        membership = []
    if not isinstance(verifier_assignments, list):
        problems.append("coordinator.verifier_assignments is not an array")
        verifier_assignments = []

    inventory_rows = [
        row for row in (inventory.get("items") or [])
        if isinstance(row, dict) and row.get("id")
    ] if isinstance(inventory, dict) else []
    inventory_by_id = {str(row["id"]): row for row in inventory_rows}
    if len(inventory_by_id) != len(inventory_rows):
        problems.append("inventory ids are duplicated")

    candidates: dict[tuple[str, str], dict] = {}
    inventory_owner: dict[str, tuple[str, str]] = {}
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
        rows = partition.get("candidates")
        if not isinstance(rows, list):
            problems.append(f"{label}.candidates is not an array")
            continue
        for candidate_index, candidate in enumerate(rows):
            candidate_label = f"{label}.candidates[{candidate_index}]"
            if not isinstance(candidate, dict):
                problems.append(f"{candidate_label} is not an object")
                continue
            candidate_id = str(candidate.get("id") or "").strip()
            key = (partition_id, candidate_id)
            if not candidate_id:
                problems.append(f"{candidate_label}.id is missing")
                continue
            if key in candidates:
                problems.append(
                    f"worker candidate {partition_id!r}/{candidate_id!r} is duplicated")
                continue
            classification = str(candidate.get("classification") or "").strip()
            if classification not in CLAIM_CLASSIFICATIONS:
                problems.append(
                    f"worker candidate {partition_id!r}/{candidate_id!r} "
                    "classification is missing or unknown")
            importance = str(candidate.get("importance") or "").strip()
            if classification == "material_claim" and importance != "material":
                problems.append(
                    f"worker candidate {partition_id!r}/{candidate_id!r} "
                    "material_claim requires importance material")
            if classification in {"supporting_provenance", "structural_context"} \
                    and importance != "supporting":
                problems.append(
                    f"worker candidate {partition_id!r}/{candidate_id!r} "
                    f"{classification} requires importance supporting")
            if classification == "supporting_provenance":
                label_problem = _public_text_problem(
                    candidate.get("public_label"), operand_label=True)
                if label_problem:
                    problems.append(
                        f"worker candidate {partition_id!r}/{candidate_id!r} "
                        f"public_label {label_problem}")
            clean_clauses: list[dict] = []
            if classification == "material_claim":
                raw_clauses = candidate.get("clauses")
                clause_label = (
                    f"worker candidate {partition_id!r}/{candidate_id!r} clauses")
                if not isinstance(raw_clauses, list) or not raw_clauses:
                    problems.append(
                        f"{clause_label} is missing or not a non-empty array")
                    raw_clauses = []
                clause_ids: set[str] = set()
                for clause_index, clause in enumerate(raw_clauses):
                    item_label = f"{clause_label}[{clause_index}]"
                    if not isinstance(clause, dict):
                        problems.append(f"{item_label} is not an object")
                        continue
                    clause_id = str(clause.get("id") or "").strip()
                    clause_quote = str(clause.get("quote") or "").strip()
                    public_label = str(clause.get("public_label") or "").strip()
                    if not clause_id:
                        problems.append(f"{item_label}.id is missing")
                    elif clause_id in clause_ids:
                        problems.append(
                            f"worker candidate {partition_id!r}/{candidate_id!r} "
                            f"clause id {clause_id!r} is duplicated")
                    clause_ids.add(clause_id)
                    if not quote_in_text(clause_quote, str(candidate.get("quote") or "")):
                        problems.append(
                            f"worker candidate {partition_id!r}/{candidate_id!r} "
                            f"clause {clause_id!r} quote is not exact candidate text")
                    quote_problem = _public_text_problem(clause_quote)
                    if quote_problem:
                        problems.append(f"{item_label}.quote {quote_problem}")
                    label_problem = _public_text_problem(
                        public_label, operand_label=True)
                    if label_problem:
                        problems.append(f"{item_label}.public_label {label_problem}")
                    clean_clauses.append({
                        "id": clause_id,
                        "quote": clause_quote,
                        "public_label": public_label,
                    })
            if classification == "supporting_provenance" \
                    and not _substantive_explanation(candidate.get("reason")):
                problems.append(
                    f"worker candidate {partition_id!r}/{candidate_id!r} "
                    "supporting_provenance reason is missing or not substantive")
            raw_ids = candidate.get("inventory_ids")
            ids = _listed_ids(
                raw_ids,
                f"worker candidate {partition_id!r}/{candidate_id!r} inventory_ids",
                problems,
            )
            for inventory_id in ids:
                if inventory_id not in inventory_by_id:
                    problems.append(
                        f"inventory id {inventory_id!r} is not in the inventory")
                    continue
                if inventory_id in inventory_owner:
                    problems.append(
                        f"inventory id {inventory_id!r} is assigned more than once")
                else:
                    inventory_owner[inventory_id] = key
            if classification == "structural_context":
                if len(ids) != 1:
                    problems.append(
                        f"worker candidate {partition_id!r}/{candidate_id!r} "
                        "structural_context requires exactly one inventory id")
                quote = normalize(str(candidate.get("quote") or ""))
                item = inventory_by_id.get(ids[0]) if len(ids) == 1 else None
                shown = normalize(str((item or {}).get("displayed") or ""))
                if not quote or quote != shown:
                    problems.append(
                        f"worker candidate {partition_id!r}/{candidate_id!r} "
                        "structural_context quote is not the exact inventory text")
                if not _substantive_explanation(candidate.get("reason")):
                    problems.append(
                        f"worker candidate {partition_id!r}/{candidate_id!r} "
                        "structural_context reason is missing or not substantive")
            candidates[key] = {
                **candidate,
                "inventory_ids": ids,
                "clauses": clean_clauses,
            }

    for inventory_id in inventory_by_id:
        if inventory_id not in inventory_owner:
            problems.append(f"inventory id {inventory_id!r} is not assigned by a worker candidate")

    assigned: dict[tuple[str, str, str | None], str | None] = {}
    membership_rows: list[dict] = []
    for index, row in enumerate(membership):
        label = f"coordinator.membership[{index}]"
        base_ref = _member_ref(row, label, problems)
        if base_ref is None:
            continue
        if base_ref not in candidates:
            problems.append(
                f"membership references unknown worker candidate "
                f"{base_ref[0]!r}/{base_ref[1]!r}")
            continue
        candidate = candidates[base_ref]
        material = candidate.get("classification") == "material_claim"
        ref = _clause_ref(row, label, problems, required=material)
        if ref is None:
            continue
        clause_id = ref[2]
        if material and clause_id not in {
            str(item.get("id") or "") for item in candidate.get("clauses") or []
        }:
            problems.append(
                f"membership references unknown clause {clause_id!r} on worker "
                f"candidate {ref[0]!r}/{ref[1]!r}")
            continue
        if ref in assigned:
            problems.append(
                f"worker candidate {ref[0]!r}/{ref[1]!r} clause "
                f"{clause_id!r} is assigned more than once")
            continue
        canonical_id_raw = row.get("canonical_claim_id") if isinstance(row, dict) else None
        canonical_id = (
            str(canonical_id_raw).strip()
            if canonical_id_raw not in (None, "") else None
        )
        if candidate.get("classification") == "structural_context":
            if canonical_id is not None:
                problems.append(
                    f"structural worker candidate {ref[0]!r}/{ref[1]!r} "
                    "must not name a canonical claim")
            handoff["structural_context"].append({
                "id": f"{ref[0]}:{ref[1]}",
                "partition_id": ref[0],
                "candidate_id": ref[1],
                "quote": candidate.get("quote"),
                "classification": "structural_context",
                "importance": "supporting",
                "reason": candidate.get("reason"),
                "inventory_ids": list(candidate.get("inventory_ids") or []),
            })
        elif canonical_id is None:
            problems.append(
                f"worker candidate {ref[0]!r}/{ref[1]!r} has no canonical claim")
        assigned[ref] = canonical_id
        membership_row = {
            "partition_id": ref[0],
            "candidate_id": ref[1],
            "canonical_claim_id": canonical_id,
        }
        if clause_id:
            membership_row["clause_id"] = clause_id
        membership_rows.append(membership_row)
    for base_ref, candidate in candidates.items():
        expected_clause_ids = (
            [str(row.get("id") or "") for row in candidate.get("clauses") or []]
            if candidate.get("classification") == "material_claim" else [None]
        )
        for clause_id in expected_clause_ids:
            ref = (base_ref[0], base_ref[1], clause_id)
            if ref not in assigned:
                suffix = f" clause {clause_id!r}" if clause_id else ""
                problems.append(
                    f"worker candidate {base_ref[0]!r}/{base_ref[1]!r}"
                    f"{suffix} has no membership assignment")

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

    refs_by_claim: dict[str, list[tuple[str, str, str | None]]] = {}
    for ref, canonical_id in assigned.items():
        if canonical_id is None:
            continue
        if canonical_id not in canonical_by_id:
            problems.append(f"membership references unknown canonical claim {canonical_id!r}")
            continue
        refs_by_claim.setdefault(canonical_id, []).append(ref)
    for claim_id, claim in canonical_by_id.items():
        classification = str(claim.get("classification") or "").strip()
        if classification not in CANONICAL_CLAIM_CLASSIFICATIONS:
            problems.append(
                f"canonical claim {claim_id!r} classification is missing or unknown")
        declared_refs_raw = claim.get("member_refs")
        if not isinstance(declared_refs_raw, list) or not declared_refs_raw:
            problems.append(f"canonical claim {claim_id!r} member_refs is missing or empty")
            declared_refs = []
        else:
            declared_refs: list[tuple[str, str, str | None]] = []
            for index, raw_ref in enumerate(declared_refs_raw):
                ref = _clause_ref(
                    raw_ref,
                    f"canonical claim {claim_id!r} member_refs[{index}]",
                    problems,
                    required=classification == "material_claim",
                )
                if ref is not None:
                    declared_refs.append(ref)
            if len(declared_refs) != len(set(declared_refs)):
                problems.append(f"canonical claim {claim_id!r} member_refs are duplicated")
        actual_refs = refs_by_claim.get(claim_id, [])
        if set(declared_refs) != set(actual_refs) or len(declared_refs) != len(actual_refs):
            problems.append(
                f"canonical claim {claim_id!r} member_refs do not match coordinator membership")
        member_ids: list[str] = []
        member_classes: set[str] = set()
        member_labels: set[str] = set()
        for ref in actual_refs:
            candidate = candidates.get((ref[0], ref[1])) or {}
            member_ids.extend(candidate.get("inventory_ids") or [])
            member_classes.add(str(candidate.get("classification") or ""))
            clause = next((
                row for row in candidate.get("clauses") or []
                if str(row.get("id") or "") == str(ref[2] or "")
            ), None)
            label = str(
                (clause or {}).get("public_label")
                if ref[2] else candidate.get("public_label")
            ).strip()
            if label:
                member_labels.add(label)
        member_ids = list(dict.fromkeys(member_ids))
        declared_ids = _listed_ids(
            claim.get("inventory_ids"),
            f"canonical claim {claim_id!r} inventory_ids",
            problems,
        )
        if set(declared_ids) != set(member_ids) or len(declared_ids) != len(member_ids):
            problems.append(
                f"canonical claim {claim_id!r} inventory_ids do not match its members")
        if member_classes and member_classes != {classification}:
            problems.append(
                f"canonical claim {claim_id!r} classification does not match its members")
        if classification == "supporting_provenance" \
                and not _substantive_explanation(claim.get("reason")):
            problems.append(
                f"canonical claim {claim_id!r} supporting_provenance reason "
                "is missing or not substantive")
        if classification in CANONICAL_CLAIM_CLASSIFICATIONS and str(
            claim.get("public_label") or ""
        ).strip() not in member_labels:
            problems.append(
                f"canonical claim {claim_id!r} public_label is not carried "
                "from a member candidate")
        if classification == "material_claim":
            handoff["material_claim_ids"].append(claim_id)
            handoff["material_claim_inventory_ids"][claim_id] = declared_ids
            handoff.setdefault("material_claim_clause_refs", {})[claim_id] = [
                {
                    "partition_id": ref[0],
                    "candidate_id": ref[1],
                    "clause_id": ref[2],
                }
                for ref in actual_refs
            ]

    for claim_id, inventory_ids in handoff["material_claim_inventory_ids"].items():
        for inventory_id in inventory_ids:
            handoff["material_inventory_claim_ids"].setdefault(
                inventory_id, []).append(claim_id)

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

    handoff["membership"] = membership_rows
    handoff["verifier_assignments"] = clean_assignments
    return handoff, list(dict.fromkeys(problems))


def _correction_notice_problems(check: dict, clause_refs: list[dict]) -> list[str]:
    """Validate an explicit repeated-occurrence correction without authoring it."""
    receipt = check.get("public_receipt")
    calculation = receipt.get("calculation") if isinstance(receipt, dict) else None
    report_operand = receipt.get("report_operand") if isinstance(receipt, dict) else None
    applicable = (
        check.get("verdict") == "contradicted"
        and len(clause_refs) > 1
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
        or len(locations) != len(clause_refs)
        or len({str(value).strip() for value in locations}) != len(clause_refs)
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
    expected_by_claim = handoff.get("material_claim_clause_refs") or {}
    for index, raw in enumerate(proposed_checks):
        if not isinstance(raw, dict):
            problems.append(
                f"evidence-verifier checks[{index}] is not an object")
            continue
        check_id = str(raw.get("id") or "").strip() or f"index {index}"
        claim_id = str(raw.get("claim_id") or "").strip()
        expected_refs = expected_by_claim.get(claim_id)
        if expected_refs is not None:
            addressed_raw = raw.get("addressed_clause_refs")
            addressed: list[tuple[str, str, str | None]] = []
            if not isinstance(addressed_raw, list) or not addressed_raw:
                addressed_raw = []
            for ref_index, ref_raw in enumerate(addressed_raw):
                ref = _clause_ref(
                    ref_raw,
                    f"evidence-verifier check {check_id!r} "
                    f"addressed_clause_refs[{ref_index}]",
                    problems,
                    required=True,
                )
                if ref is not None:
                    addressed.append(ref)
            expected = {
                (
                    str(ref.get("partition_id") or ""),
                    str(ref.get("candidate_id") or ""),
                    str(ref.get("clause_id") or ""),
                )
                for ref in expected_refs
            }
            if len(addressed) != len(set(addressed)) or set(addressed) != expected:
                problems.append(
                    f"evidence-verifier check {check_id!r} does not address every "
                    f"clause of canonical claim {claim_id!r}")
            problems.extend(_correction_notice_problems(raw, expected_refs))
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


def validate_receipts(report: str, sandbox: pathlib.Path, proposed: list,
                      claim_ids: set[str],
                      report_path: pathlib.Path | None = None, *,
                      sources: list[dict] | None = None,
                      claim_labels: dict[str, str] | None = None,
                      report_date: str | None = None,
                      report_period: str | None = None) -> tuple[list, list]:
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
        severity = finding.get("severity")
        if severity not in {None, "high", "medium", "low"}:
            problems.append("check severity is unknown")
        finding["severity"] = severity
        if not quote_in_text(finding.get("report_quote", ""), report):
            problems.append("report_quote not found in visible report text")
        if "report_quote_2" in finding:
            problems.append("report_quote_2 is not accepted; use public_receipt operands")
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

        population_alignment, population_problems = validate_population_alignment(
            finding, report, evidence,
            report_date=report_date, report_period=report_period)
        problems.extend(population_problems)
        if population_alignment is not None:
            receipt_updates["population_alignment"] = population_alignment

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
            finding, report, receipt_updates, source_map, claim_label)
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
                          accepted_checks: list[dict] | None = None
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
                elif kind == "reconcile_before_change":
                    if not unreconciled or len(unreconciled) != len(cited_checks):
                        problems.append(
                            f"{label} reconcile_before_change must cite only "
                            "unreconciled checks")
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
                    row.get("verdict") == "contradicted" or row in unreconciled
                    for row in cited_checks
                ):
                    problems.append(
                        f"{label} review_before_share cannot stand in for a "
                        "correction or reconciliation action")
                cleaned["kind"] = kind
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


def validate_acceptance_bundle(*, text: str, sandbox: pathlib.Path,
                               proposed: list, checks_doc: dict,
                               proposed_claims: list, claims_meta: dict,
                               inventory: dict, report_path: pathlib.Path,
                               arithmetic_uses: list | None = None) -> dict:
    """Run the one side-effect-free validation path used by both CLI modes."""
    coordinator_handoff, coordinator_problems = coordinator_preflight(
        proposed_claims, claims_meta.get("coordinator"), inventory, proposed,
        presentation_doc=checks_doc)
    proposed_sources = list((checks_doc or {}).get("sources") or [])
    accepted_sources, discarded_sources = validate_sources(
        sandbox, proposed_sources, report_path)
    grounded_claims, discarded_claims = validate_claims(text, proposed_claims)
    claim_ids = {row["id"] for row in grounded_claims}
    validated, discarded = validate_receipts(
        text, sandbox, proposed, claim_ids, report_path,
        sources=accepted_sources,
        claim_labels={row["id"]: row["public_label"] for row in grounded_claims},
        report_date=claims_meta.get("report_date"),
        report_period=claims_meta.get("report_period"))
    source_consideration, source_consideration_problems = (
        validate_source_consideration(
            (checks_doc or {}).get("source_consideration"),
            accepted_sources,
            grounded_claims,
            validated,
        )
    )
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
        checks_doc, text, accepted_ids, accepted_checks=validated)
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

    repair_reasons = list(coordinator_problems)
    repair_reasons.extend(_row_repair_reasons(
        discarded_sources, "retained source"))
    repair_reasons.extend(_row_repair_reasons(
        discarded_claims, "canonical claim"))
    repair_reasons.extend(_row_repair_reasons(
        discarded, "evidence-verifier check"))
    repair_reasons.extend(source_consideration_problems)
    repair_reasons.extend(presentation_problems)
    repair_reasons.extend(sorted(
        _inventory_repair_reasons(inventory_cover["missing"])
    ))
    repair_reasons = list(dict.fromkeys(repair_reasons))

    payload = {
        "status": "failed" if repair_reasons else "complete",
        "repair_reasons": repair_reasons,
        "checks": validated,
        "validated": validated,
        "discarded": discarded,
        "sources": accepted_sources,
        "discarded_sources": discarded_sources,
        "source_consideration": source_consideration,
        "source_consideration_problems": source_consideration_problems,
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
    ap.add_argument(
        "--preflight-only", action="store_true",
        help="validate role handoffs and return exact repair reasons before acceptance",
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
        arithmetic_uses=arithmetic_uses)
    if args.preflight_only:
        preflight = {
            "status": payload["status"],
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
