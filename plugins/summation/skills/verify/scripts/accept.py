#!/usr/bin/env python3
"""Keep or drop proposed checks by grounding them in the report and evidence.

A check survives when its quotes and pointers resolve. A bad row is discarded.
The run continues. Exit 0 when receipts.json was written.

Usage:
    accept.py --report <file> --checks checks.json --claims claims.json
              --out receipts.json [--evidence-dir DIR] [--report-text visible.txt]
"""
from __future__ import annotations

import argparse
from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import json
import pathlib
import re
import sys

_SCRIPTS = pathlib.Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
from inventory import claim_inventory_ids, cover, inventory_for  # noqa: E402
from receipt_math import calculation_problem  # noqa: E402
from severity import normalize_severity  # noqa: E402

FALLBACK_VERDICTS = frozenset({
    "confirmed", "contradicted", "not_checkable", "changed_since_report",
})
CLAIM_CLASSIFICATIONS = frozenset({"material_claim", "supporting_provenance"})


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
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return FALLBACK_VERDICTS


KNOWN_VERDICTS = load_known_verdicts()
EVIDENCE_RECEIPT_VERDICTS = frozenset({
    "confirmed", "contradicted", "changed_since_report",
}) & KNOWN_VERDICTS


_SUFFIX = {
    "K": Decimal("1000"),
    "M": Decimal("1000000"),
    "B": Decimal("1000000000"),
}
_QTOKEN = re.compile(
    r"\((?:\$)?\d[\d,]*\.?\d*[KMB]?%?\)"
    r"|(?:\$)?-?\d[\d,]*\.?\d*[KMB]?%?",
    re.I,
)
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_DATE_KEYS = frozenset({
    "as_of", "date", "current_as_of", "queried_at", "timestamp",
    "latest_complete_date", "complete_date", "as_of_date", "snapshot_date",
})
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
PRIVATE_NAMES = frozenset({
    "findings.json", "receipts.json", "checks.json", "claims.json",
    "grade-artifact.json", "report-visible.txt", "ledger.json",
    "source-findings.json", "provenance.json",
})
_ABS_PATH = re.compile(
    r"(?:/Users/|/home/|/var/folders/|/private/tmp/|/tmp/|[A-Z]:\\)[^\s\"'<]+",
    re.I,
)
_JSON_POINTER_EXACT = re.compile(r"(?:/[A-Za-z0-9_~.-]+)+")
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
    needle = normalize(quote)
    haystack = normalize(text)
    if not needle:
        return False
    if needle in haystack:
        return True
    if parse_quantity(needle) is None:
        return False
    return any(quantities_equal(needle, token) for token in _QTOKEN.findall(haystack))


def strip_tags(html: str) -> str:
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    return re.sub(r"<[^>]+>", " ", html)


def load_text(path: pathlib.Path) -> str:
    raw = path.read_text(errors="replace")
    suffix = path.suffix.lower()
    if suffix == ".html":
        raw = strip_tags(raw)
    elif suffix == ".json":
        try:
            compact = json.dumps(json.loads(raw), ensure_ascii=False, separators=(",", ":"))
            return normalize(raw) + " " + normalize(compact)
        except json.JSONDecodeError:
            pass
    return normalize(raw)


def _json_objects(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _json_objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from _json_objects(child)


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


def json_field_receipt(evidence: pathlib.Path, quote: str) -> tuple[bool, str | None]:
    if evidence.suffix.lower() != ".json" or not quote:
        return False, None
    candidate = quote.strip().rstrip(",")
    candidate = re.sub(r",\s*(?:\.{3}|…)+\s*", ", ", candidate)
    if not candidate.startswith("{"):
        candidate = "{" + candidate
    if not candidate.endswith("}"):
        candidate += "}"
    try:
        fragment = json.loads(candidate)
        payload = json.loads(evidence.read_text())
    except (json.JSONDecodeError, OSError):
        return False, None
    if not isinstance(fragment, dict) or len(fragment) < 2:
        return False, None
    for obj in _json_objects(payload):
        if all(key in obj and values_equal(obj[key], expected)
               for key, expected in fragment.items()):
            return True, json.dumps(fragment, ensure_ascii=False, separators=(", ", ": "))
    return False, None


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
        or _JSON_POINTER_EXACT.fullmatch(text)
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
    seen: set[str] = set()
    if not isinstance(proposed, list):
        return [], [{"id": "", "problems": ["sources is not a list"]}]
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
        if kind == "supplied_file" and retrieval is not None:
            problems.append("supplied_file source must not declare live retrieval metadata")
        if kind == "live_tool":
            if not isinstance(retrieval, dict):
                problems.append("live_tool source retrieval metadata is missing")
            else:
                retrieved_at = str(retrieval.get("retrieved_at") or "").strip()
                tool = str(retrieval.get("tool") or "").strip()
                arguments = retrieval.get("arguments")
                if not _ISO_TIME.fullmatch(retrieved_at):
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
        if problems:
            discarded.append({**canonical, "problems": problems})
        else:
            seen.add(source_id)
            accepted.append(canonical)
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


def _dates_on_object(obj: dict) -> list[str]:
    found = []
    for key, value in obj.items():
        if not isinstance(value, str) or not value.strip():
            continue
        if key.lower() in _DATE_KEYS or _DATE.search(value):
            found.append(value.strip())
    return found


def _parent_record(payload, pointer: str):
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        return payload if isinstance(payload, dict) else None
    current = payload
    parts = [part.replace("~1", "/").replace("~0", "~") for part in pointer[1:].split("/")]
    for token in parts[:-1]:
        try:
            if isinstance(current, list):
                current = current[int(token)]
            elif isinstance(current, dict):
                current = current[token]
            else:
                return None
        except (KeyError, IndexError, ValueError, TypeError):
            return None
    return current if isinstance(current, dict) else None


def _json_values_from_receipts(finding: dict, receipt_updates: dict) -> list:
    values = []
    groups = receipt_updates.get("evidence_receipts")
    if groups:
        for group in groups:
            for item in group.get("evidence_json") or []:
                if isinstance(item, dict) and "value" in item:
                    values.append(item["value"])
        return values
    if "evidence_json" in receipt_updates:
        for item in receipt_updates.get("evidence_json") or []:
            if isinstance(item, dict) and "value" in item:
                values.append(item["value"])
    return values


def _json_pointers(finding: dict, receipt_updates: dict) -> list[str]:
    pointers = []
    for item in receipt_updates.get("evidence_json") or finding.get("evidence_json") or []:
        if isinstance(item, dict) and item.get("pointer"):
            pointers.append(str(item["pointer"]))
    for group in receipt_updates.get("evidence_receipts") or []:
        for item in group.get("evidence_json") or []:
            if isinstance(item, dict) and item.get("pointer"):
                pointers.append(str(item["pointer"]))
    return pointers


def _dates_on_same_record(payload, pointers: list[str], current_value) -> list[str]:
    dates = []
    seen = set()
    records = []
    for pointer in pointers:
        parent = _parent_record(payload, pointer)
        if isinstance(parent, dict) and id(parent) not in seen:
            seen.add(id(parent))
            records.append(parent)
    if not records and current_value not in (None, ""):
        for obj in _json_objects(payload):
            if not isinstance(obj, dict) or id(obj) in seen:
                continue
            if any(values_equal(value, current_value) for value in obj.values()):
                seen.add(id(obj))
                records.append(obj)
    for record in records:
        dates.extend(_dates_on_object(record))
    return dates


def _csv_dates_for_value(path: pathlib.Path, current_value) -> list[str]:
    if path.suffix.lower() != ".csv" or current_value in (None, ""):
        return []
    import csv
    import io
    try:
        raw = path.read_text(errors="replace")
    except OSError:
        return []
    rows = list(csv.reader(io.StringIO(raw)))
    if not rows:
        return []
    header = rows[0]
    dates = []
    for row in rows:
        if not any(cell != "" and values_equal(cell, current_value) for cell in row):
            continue
        for index, cell in enumerate(row):
            if not isinstance(cell, str) or not cell.strip():
                continue
            key = header[index] if index < len(header) else ""
            if str(key).lower() in _DATE_KEYS or _DATE.search(cell):
                dates.append(cell.strip())
    return dates


def _date_matches(declared: str, candidates: list[str]) -> bool:
    want = declared.strip()
    want_day = _DATE.search(want)
    for item in candidates:
        if item == want:
            return True
        if want_day and want_day.group(0) in item:
            return True
    return False


def _resolved_receipt_values(finding: dict, receipt_updates: dict) -> list:
    values = list(_json_values_from_receipts(finding, receipt_updates))
    quote = receipt_updates.get("evidence_quote") or finding.get("evidence_quote")
    if quote:
        parsed = parse_quantity(quote)
        if parsed is not None:
            values.append(parsed)
        values.extend(
            parse_quantity(token) for token in _QTOKEN.findall(str(quote))
            if parse_quantity(token) is not None
        )
    return values


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
    if value in (None, "") or isinstance(value, bool):
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


def _validate_public_receipt(finding: dict, report: str,
                             receipt_updates: dict,
                             sources: dict[str, dict]) -> tuple[dict | None, list[str]]:
    raw = finding.get("public_receipt")
    if not isinstance(raw, dict):
        return None, ["public_receipt is missing or not an object"]
    problems: list[str] = []
    allowed = {
        "report_operand", "decisive_operands", "explanation",
        "calculation", "source_id",
    }
    unknown = sorted(set(raw) - allowed)
    if unknown:
        problems.append(f"public_receipt has unknown field {unknown[0]!r}")
    report_operand, report_problems = _operand_problem(
        raw.get("report_operand"), "public_receipt.report_operand")
    problems.extend(report_problems)
    decisive_raw = raw.get("decisive_operands")
    decisive: list[dict] = []
    if not isinstance(decisive_raw, list) or not decisive_raw:
        problems.append("public_receipt.decisive_operands is missing or empty")
    else:
        for index, operand in enumerate(decisive_raw):
            canonical, operand_problems = _operand_problem(
                operand, f"public_receipt.decisive_operands[{index}]")
            problems.extend(operand_problems)
            if canonical is not None:
                decisive.append(canonical)
    explanation = str(raw.get("explanation") or "").strip()
    if not _substantive_explanation(explanation):
        problems.append("public_receipt.explanation is missing or not substantive")
    basis = str(finding.get("basis") or "")
    source_id = str(raw.get("source_id") or "").strip()
    source = sources.get(source_id)
    if basis == "evidence":
        if not source_id:
            problems.append("public_receipt.source_id is required for evidence basis")
        elif source is None:
            problems.append(f"public_receipt.source_id {source_id!r} is not retained")
    elif source_id:
        problems.append("public_receipt.source_id is not allowed for report basis")
    report_quote = str(finding.get("report_quote") or "")
    if report_operand is not None and report_operand.get("value") not in (None, ""):
        if not quote_in_text(str(report_operand["value"]), report_quote):
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
                grounded = quote_in_text(str(value), evidence_quote)
        else:
            grounded = quote_in_text(str(value), report)
        if not grounded:
            problems.append(
                f"public_receipt.decisive_operands[{index}].value is not grounded"
            )
    calculation = raw.get("calculation")
    canonical_calculation = None
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
            if result in (None, "") or isinstance(result, bool):
                problems.append("public_receipt.calculation.result is missing")
            elif isinstance(result, str):
                result_problem = _public_text_problem(result)
                if result_problem:
                    problems.append(f"public_receipt.calculation.result {result_problem}")
            if not expression_problem and result not in (None, ""):
                math_problem = calculation_problem(expression, result, decisive)
                if math_problem:
                    problems.append(f"public_receipt.{math_problem}")
            canonical_calculation = {"expression": expression, "result": result}
    if (
        basis == "report"
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
    return (None if problems else canonical), problems


def validate_claims(report: str, proposed: list) -> tuple[list, list]:
    grounded, discarded = [], []
    seen = set()
    for claim in proposed:
        problems = []
        cid = str(claim.get("id") or "").strip()
        quote = claim.get("quote", "")
        importance = claim.get("importance")
        classification = claim.get("classification") or "material_claim"
        reason = str(claim.get("reason") or "").strip()
        if not cid:
            problems.append("claim has no id")
        elif cid in seen:
            problems.append(f"claim id {cid!r} is duplicated")
        if classification not in CLAIM_CLASSIFICATIONS:
            problems.append("claim classification is missing or unknown")
        if classification == "supporting_provenance":
            if importance not in {None, "supporting"}:
                problems.append("supporting_provenance requires importance supporting")
            importance = "supporting"
            if not reason:
                problems.append("supporting_provenance has no reason")
        elif importance not in {"material", "supporting"}:
            problems.append("claim importance is missing or unknown")
        if not quote_in_text(str(quote), report):
            problems.append("claim quote not found in visible report text")
        quote_problem = _public_text_problem(quote)
        if quote_problem:
            problems.append(f"claim quote {quote_problem}")
        row = {
            "id": cid,
            "quote": quote,
            "importance": importance if importance in {"material", "supporting"} else "material",
            "classification": (
                classification if classification in CLAIM_CLASSIFICATIONS
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


def validate_receipts(report: str, sandbox: pathlib.Path, proposed: list,
                      claim_ids: set[str],
                      report_path: pathlib.Path | None = None, *,
                      sources: list[dict] | None = None,
                      report_date: str | None = None) -> tuple[list, list]:
    """Ground agent-authored checks; never invent their public semantics."""
    validated: list[dict] = []
    discarded: list[dict] = []
    source_map = {
        str(row.get("id") or ""): row for row in (sources or [])
        if isinstance(row, dict) and row.get("id")
    }
    seen_ids: set[str] = set()
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
        if verdict == "contradicted":
            finding["severity"] = normalize_severity(
                finding.get("severity"), contradicted=True,
                importance=importance or "material")
        else:
            finding["severity"] = None
        if not quote_in_text(finding.get("report_quote", ""), report):
            problems.append("report_quote not found in visible report text")
        second = finding.get("report_quote_2")
        if second and basis == "report" and not quote_in_text(second, report):
            problems.append("report_quote_2 not found in visible report text")
        elif second and basis != "report":
            problems.append("report_quote_2 is only allowed for report basis")
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
        if basis == "evidence" and verdict in EVIDENCE_RECEIPT_VERDICTS:
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
            json_receipts = finding.get("evidence_json")
            if json_receipts not in (None, []) and not isinstance(json_receipts, list):
                problems.append("evidence_json is not a list")
                json_receipts = []
            json_receipts = json_receipts or []
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
            elif evidence is not None:
                quote = str(finding.get("evidence_quote") or "")
                evidence_texts = (
                    load_text(evidence),
                    normalize(evidence.read_text(errors="replace")),
                )
                if quote and any(quote_in_text(quote, text) for text in evidence_texts):
                    receipt_updates.update({
                        "evidence_receipt_mode": "verbatim",
                        "evidence_quote": quote,
                    })
                else:
                    matched, canonical = json_field_receipt(evidence, quote)
                    if matched:
                        receipt_updates.update({
                            "evidence_receipt_mode": "json-object-fields",
                            "evidence_quote": canonical,
                        })
                    else:
                        problems.append(
                            "evidence receipt needs exact pointers or a grounded exact quote")
        elif basis == "report" and (
            finding.get("evidence_json") or finding.get("evidence_quote")
        ):
            problems.append("report-basis check must not declare evidence receipts")

        if verdict in EVIDENCE_RECEIPT_VERDICTS:
            public_receipt, public_problems = _validate_public_receipt(
                finding, report, receipt_updates, source_map)
            problems.extend(public_problems)
            if public_receipt is not None:
                receipt_updates["public_receipt"] = public_receipt
        elif finding.get("public_receipt") not in (None, {}):
            problems.append("public_receipt is only allowed for a decisive verdict")

        if verdict == "not_checkable":
            explanation = str(finding.get("explanation") or "").strip()
            if not _substantive_explanation(explanation):
                problems.append("not_checkable explanation is missing or not substantive")
            finding["explanation"] = explanation

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
            if report_value in (None, ""):
                problems.append("changed_since_report has no report value")
            if current_value in (None, ""):
                problems.append("changed_since_report has no current value")
            if not current_as_of:
                problems.append("changed_since_report has no current as-of date")
            if not canonical_report_date:
                problems.append("changed_since_report has no report date")
            if report_value not in (None, "") and not quote_in_text(
                str(report_value), str(finding.get("report_quote") or "")
            ):
                problems.append(
                    "changed_since_report report value is not visible in report_quote")
            if values_equal(report_value, current_value):
                problems.append("changed_since_report current value equals the report value")
            resolved_values = _resolved_receipt_values(finding, receipt_updates)
            if current_value not in (None, "") and not _value_in(
                current_value, resolved_values
            ):
                problems.append("current_value does not match the receipt")
            receipt = receipt_updates.get("public_receipt") or {}
            decisive_values = [
                row.get("value") for row in receipt.get("decisive_operands") or []
                if isinstance(row, dict)
            ]
            if current_value not in (None, "") and not _value_in(
                current_value, decisive_values
            ):
                problems.append("current_value is not a decisive public operand")
            payload = None
            if evidence is not None and evidence.suffix.lower() == ".json":
                try:
                    payload = json.loads(evidence.read_text())
                except (OSError, json.JSONDecodeError):
                    payload = None
            pointers = _json_pointers(finding, receipt_updates)
            dates: list[str] = []
            if payload is not None:
                dates = _dates_on_same_record(payload, pointers, current_value)
            if not dates and evidence is not None:
                dates = _csv_dates_for_value(evidence, current_value)
            if current_as_of:
                if not dates:
                    problems.append(
                        "current_as_of is not on the same record as the current value")
                elif not _date_matches(current_as_of, dates):
                    problems.append("current_as_of does not match evidence date")
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
    rank = {
        "error": 0,
        "contradicted": 0,
        "changed_since_report": 1,
        "confirmed": 2,
        "not_checkable": 3,
        "used_for_internal_arithmetic": 2,
    }
    by_claim: dict[str, list] = {}
    for check in checks:
        by_claim.setdefault(str(check.get("claim_id") or ""), []).append(check)
    out = []
    for claim in claims:
        options = by_claim.get(claim["id"]) or []
        if not options:
            out.append({**claim, "outcome": "not_reached", "check_id": None})
            continue
        best = sorted(options, key=lambda row: rank.get(row.get("verdict"), 9))[0]
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
                          accepted_ids: set[str] | None = None
                          ) -> tuple[dict | None, list[str]]:
    if not isinstance(doc, dict) or "presentation" not in doc:
        return None, []
    pres = doc.get("presentation")
    if pres is None:
        return None, []
    problems = []
    if not isinstance(pres, dict):
        return None, ["presentation is not an object"]
    accepted = accepted_ids or set()
    summary = pres.get("summary")
    if summary is not None and not isinstance(summary, str):
        problems.append("presentation.summary is not a string")
        summary = None
    summary_text = str(summary or "").strip()
    summary_ids = _check_ids_of(pres)
    if summary_text:
        id_problem = _ids_problem(summary_ids, accepted, "presentation.summary")
        if id_problem:
            problems.append(id_problem)
            summary_text = ""
            summary_ids = []
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
            if not text or not quote:
                problems.append(f"{label} is incomplete")
                continue
            if not quote_in_text(quote, report):
                problems.append(f"{label} report_quote not found in visible report text")
                continue
            ids = _check_ids_of(item)
            id_problem = _ids_problem(ids, accepted, label)
            if id_problem:
                problems.append(id_problem)
                continue
            bucket.append({
                "id": str(item.get("id") or f"{name[:1].upper()}{index + 1}"),
                "text": text,
                "report_quote": quote,
                "check_ids": ids,
            })
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
        return doc["claims"], meta
    raise ValueError("claims file has no claims array")


def apply_host_classifications(ledger: list, discarded_claims: list,
                               inventory: dict) -> list:
    """Apply host supporting_provenance. Code does not guess meaning from words."""
    by_id = {
        str(item.get("id") or ""): item
        for item in (inventory.get("items") or [])
        if isinstance(item, dict) and item.get("id")
    }
    used: set[str] = set()
    kept = []
    for claim in ledger:
        if claim.get("classification") != "supporting_provenance":
            kept.append(claim)
            continue
        problems = []
        ids = claim_inventory_ids(claim)
        if len(ids) != 1:
            problems.append("supporting_provenance requires exactly one inventory id")
        else:
            iid = ids[0]
            item = by_id.get(iid)
            if item is None:
                problems.append(f"inventory id {iid!r} is not in the inventory")
            else:
                shown = normalize(str(item.get("displayed") or item.get("quote") or ""))
                quote = normalize(str(claim.get("quote") or ""))
                if not quote or shown != quote:
                    problems.append(
                        "supporting_provenance quote is not the exact inventory text")
                if iid in used:
                    problems.append(
                        f"inventory id {iid!r} already has supporting_provenance")
                if not problems:
                    used.add(iid)
                    item["importance"] = "supporting"
                    claim["importance"] = "supporting"
        if problems:
            dropped = {**claim, "problems": problems}
            discarded_claims.append(dropped)
        else:
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
        if not (set(claim_inventory_ids(claim)) & used_inventory_ids):
            continue
        claim["verification_mode"] = "internal_arithmetic"
        claim["found_by"] = claim.get("found_by") or "arithmetic"
        if claim.get("outcome") in (None, "not_reached"):
            claim["outcome"] = "used_for_internal_arithmetic"
            claim["check_id"] = None
    return validated, ledger


def _missing(path: pathlib.Path, label: str) -> int:
    print(f"accept: missing {label} {path}", file=sys.stderr)
    return 2


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--report", required=True, type=pathlib.Path)
    ap.add_argument("--checks", required=True, type=pathlib.Path)
    ap.add_argument("--claims", required=True, type=pathlib.Path)
    ap.add_argument("--out", required=True, type=pathlib.Path)
    ap.add_argument("--evidence-dir", type=pathlib.Path, default=None)
    ap.add_argument("--report-text", type=pathlib.Path, default=None)
    ap.add_argument("--findings", type=pathlib.Path, default=None)
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

    proposed_sources = list((checks_doc or {}).get("sources") or [])
    accepted_sources, discarded_sources = validate_sources(
        sandbox, proposed_sources, args.report)
    grounded_claims, discarded_claims = validate_claims(text, proposed_claims)
    claim_ids = {row["id"] for row in grounded_claims}
    validated, discarded = validate_receipts(
        text, sandbox, proposed, claim_ids, args.report,
        sources=accepted_sources, report_date=claims_meta.get("report_date"))
    ledger = attach_claim_outcomes(grounded_claims, validated)
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
    ledger = apply_host_classifications(ledger, discarded_claims, inventory)
    validated, ledger = attach_arithmetic_uses(ledger, validated, arithmetic_uses)
    inventory_cover = cover(inventory, ledger)
    accepted_ids = {
        str(row.get("id") or "").strip() for row in validated if row.get("id")}
    presentation, presentation_problems = validate_presentation(
        checks_doc, text, accepted_ids)
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
    payload = {
        "checks": validated,
        "validated": validated,
        "discarded": discarded,
        "sources": accepted_sources,
        "discarded_sources": discarded_sources,
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
        "semantic_status": semantic_status(ledger, validated),
        "presentation": presentation,
        "presentation_problems": presentation_problems,
        "report_period": claims_meta.get("report_period"),
        "report_date": claims_meta.get("report_date"),
        "inventory": inventory,
        "inventory_missing": inventory_cover["missing"],
        "extractor_checkable_fraction": inventory_cover["extractor_fraction"],
        "engine_checkable_fraction": inventory_cover["engine_fraction"],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n")
    print(
        f"accept: {len(material_validated)} grounded, {len(discarded)} discarded "
        f"of {len(material_proposed)}; "
        f"ledger {payload['claims_reached_by_a_check']} of {payload['claims_in_ledger']}"
    )
    for row in discarded_claims:
        print(f"  DISCARDED CLAIM {row.get('id')}: {'; '.join(row.get('problems') or [])}")
    for row in discarded_sources:
        print(f"  DISCARDED SOURCE {row.get('id')}: {'; '.join(row.get('problems') or [])}")
    for row in discarded:
        print(f"  DISCARDED {row.get('id')}: {'; '.join(row.get('problems') or [])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
