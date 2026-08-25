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
import json
import pathlib
import re
import sys

_SCRIPTS = pathlib.Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
from inventory import claim_inventory_ids, cover, inventory_for  # noqa: E402
from severity import normalize_severity  # noqa: E402

EVIDENCE_SUFFIXES = frozenset({
    ".json", ".jsonl", ".txt", ".sql", ".csv", ".yaml", ".yml", ".md", ".html",
})
REPORT_ONLY_TYPES = frozenset({"internal", "logic", "arithmetic", "units", "selection"})
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
_CURRENCY_CUE = re.compile(
    r"(?i)(?:data\s+is\s+)?current\s+through|current\s+as\s+of|"
    r"\bas\s+of\b|\bas-of\b|\bas\s+at\b"
)
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
_PREFERRED_DATE_KEYS = (
    "latest_complete_date", "complete_date", "current_through",
    "current_through_date", "as_of", "as_of_date", "asof", "as_at",
    "data_date", "snapshot_date", "effective_date", "date",
)
_SKIP_DATE_KEYS = frozenset({
    "generated_at", "queried_at", "timestamp", "created_at", "updated_at",
})
_SKIP_EVIDENCE_NAMES = frozenset({
    "claims.json", "checks.json", "findings.json", "receipts.json",
    "grade-artifact.json",
})
VISIBLE_REPORT_SUFFIXES = frozenset({".html", ".md", ".txt", ".csv"})


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


def unit_class(value) -> str | None:
    if parse_quantity(value) is None:
        return None
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float, Decimal)):
        return "count"
    text = str(value)
    if "%" in text:
        return "percent"
    if re.search(r"[\$€£¥]", text):
        return "currency"
    return "count"


def unit_classes_compatible(left, right) -> bool:
    a = unit_class(left)
    b = unit_class(right)
    return a is not None and a == b


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


def resolve_json_pointer_receipts(
        sandbox: pathlib.Path, finding: dict, receipts: list,
        report_path: pathlib.Path | None) -> tuple[list | None, str | None]:
    candidates = []
    path_error = None
    for name in [finding.get("evidence_file"), *(finding.get("evidence_files") or [])]:
        name = str(name or "")
        if not name or name in candidates:
            continue
        resolved, err = evidence_path(sandbox, name, report_path)
        if err:
            path_error = err
            continue
        candidates.append((name, resolved))
    if not candidates:
        return None, path_error or "evidence_file is missing"
    grouped: dict[str, list] = {}
    for receipt in receipts:
        matched = None
        for name, path in candidates:
            ok, canonical = json_pointer_receipt(path, [receipt])
            if ok:
                matched = (name, canonical[0])
                break
        if matched is None:
            return None, path_error or "JSON pointer receipt did not match an evidence file"
        name, canonical_receipt = matched
        grouped.setdefault(name, []).append(canonical_receipt)
    return [
        {"evidence_file": name, "evidence_json": grouped[name]}
        for name, _path in candidates if name in grouped
    ], None


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


def _load_evidence_payload(
        finding: dict, receipt_updates: dict, sandbox: pathlib.Path,
        report_path: pathlib.Path | None) -> tuple[pathlib.Path | None, object]:
    name = str(finding.get("evidence_file") or receipt_updates.get("evidence_file") or "")
    path, err = evidence_path(sandbox, name, report_path) if name else (None, "missing")
    if err or path is None:
        return None, None
    if path.suffix.lower() != ".json":
        return path, None
    try:
        return path, json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return path, None


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


def _collect_comparable(quote, json_values: list) -> tuple[list, list, list]:
    numbers = []
    classes = []
    strings = []
    seen_n = set()

    def add_num(number, source):
        if number is None:
            return
        key = str(number)
        if key not in seen_n:
            seen_n.add(key)
            numbers.append(number)
            classes.append(unit_class(source))

    def add_str(text):
        item = normalize(str(text))
        if item and item not in strings:
            strings.append(item)

    for value in json_values:
        if isinstance(value, bool):
            continue
        parsed = parse_quantity(value)
        if parsed is not None:
            add_num(parsed, value)
        elif isinstance(value, str) and value.strip():
            add_str(value)
    if quote:
        for token in _QTOKEN.findall(str(quote)):
            add_num(parse_quantity(token), token)
        add_num(parse_quantity(quote), quote)
        if not numbers:
            add_str(quote)
    return numbers, strings, classes


def _strings_match(left: str, right: str) -> bool:
    return left == right or quote_in_text(left, right) or quote_in_text(right, left)


def _verdict_receipt_problem(finding: dict, receipt_updates: dict) -> str | None:
    verdict = finding.get("verdict")
    if verdict not in {"confirmed", "contradicted"}:
        return None
    report_quote = finding.get("report_quote") or ""
    if finding.get("basis") == "report":
        evidence_quote = finding.get("report_quote_2") or ""
        json_values = []
    else:
        evidence_quote = receipt_updates.get("evidence_quote") or finding.get("evidence_quote") or ""
        json_values = _json_values_from_receipts(finding, receipt_updates)
    report_nums, report_strs, report_classes = _collect_comparable(report_quote, [])
    evidence_nums, evidence_strs, evidence_classes = _collect_comparable(
        evidence_quote, json_values)
    comparable = (report_nums and evidence_nums) or (report_strs and evidence_strs)
    if not comparable:
        return None
    matched = False
    if report_nums and evidence_nums:
        matched = any(
            values_equal(left, right) for left in report_nums for right in evidence_nums)
    if not matched and report_strs and evidence_strs:
        matched = any(
            _strings_match(left, right) for left in report_strs for right in evidence_strs)
    if (
        verdict == "confirmed"
        and report_nums
        and evidence_nums
        and not matched
    ):
        compatible = any(
            r is not None and r == e
            for r in report_classes
            for e in evidence_classes
        )
        if not compatible:
            return "report and evidence unit classes are not compatible"
    if verdict == "confirmed" and not matched:
        return "confirmed verdict is not supported by the receipt values"
    if verdict == "contradicted" and matched:
        return "contradicted verdict is not supported by the receipt values"
    return None


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
                      report_path: pathlib.Path | None = None) -> tuple[list, list]:
    validated, discarded = [], []
    for finding in proposed:
        problems = []
        receipt_updates = {}
        verdict = finding.get("verdict")
        if verdict not in KNOWN_VERDICTS:
            problems.append("verdict is missing or unknown")
        claim_id = str(finding.get("claim_id") or "").strip()
        if not claim_id:
            problems.append("check has no claim_id")
        elif claim_id not in claim_ids:
            problems.append(f"claim_id {claim_id!r} is not in the ledger")
        finding = {
            **finding,
            "claim_id": claim_id,
            "basis": finding.get("basis") or (
                "report" if finding.get("type") in REPORT_ONLY_TYPES else "evidence"),
            "importance": finding.get("importance") or "material",
        }
        if verdict == "contradicted":
            finding["severity"] = normalize_severity(
                finding.get("severity"), contradicted=True,
                importance=str(finding.get("importance") or "material"))
        else:
            finding["severity"] = None
        if not quote_in_text(finding.get("report_quote", ""), report):
            problems.append("report_quote not found in visible report text")
        second = finding.get("report_quote_2")
        basis = finding.get("basis")
        if second and basis == "report" and not quote_in_text(second, report):
            problems.append("report_quote_2 not found in visible report text")
        elif second and basis != "report":
            receipt_updates["report_quote_2"] = None
        if basis == "report" and verdict == "contradicted" and not second:
            problems.append("report-only contradiction has no second report receipt")
        if verdict == "changed_since_report" and basis != "evidence":
            problems.append(
                "changed_since_report requires an evidence receipt for the current value")
        if basis == "evidence" and verdict in EVIDENCE_RECEIPT_VERDICTS:
            evidence_name = str(finding.get("evidence_file") or "")
            json_receipts = finding.get("evidence_json") or []
            if json_receipts:
                resolved, path_err = resolve_json_pointer_receipts(
                    sandbox, finding, json_receipts, report_path)
                if resolved:
                    receipt_updates.update({
                        "evidence_file": (
                            resolved[0]["evidence_file"] if len(resolved) == 1 else None),
                        "evidence_receipts": resolved,
                        "evidence_receipt_mode": "json-pointers",
                        "evidence_json": [
                            receipt for group in resolved
                            for receipt in group["evidence_json"]],
                        "evidence_quote": None,
                    })
                else:
                    problems.append(
                        path_err or "JSON pointer receipt did not match an evidence file")
            else:
                evidence, path_err = evidence_path(sandbox, evidence_name, report_path)
                if path_err or evidence is None:
                    problems.append(path_err or f"evidence_file {evidence_name!r} missing")
                else:
                    quote = finding.get("evidence_quote", "")
                    evidence_texts = (
                        load_text(evidence),
                        normalize(evidence.read_text(errors="replace")),
                    )
                    if quote and any(quote_in_text(quote, text) for text in evidence_texts):
                        receipt_updates["evidence_receipt_mode"] = "verbatim"
                    else:
                        matched, canonical = json_field_receipt(evidence, quote)
                        if matched:
                            receipt_updates.update({
                                "evidence_receipt_mode": "json-object-fields",
                                "evidence_quote": canonical,
                            })
                        else:
                            problems.append(
                                "evidence_quote is neither verbatim nor two exact JSON object fields")
        if verdict == "not_checkable" and not str(finding.get("explanation") or "").strip():
            problems.append("not_checkable outcome has no reason")
        if verdict == "changed_since_report":
            if not str(finding.get("reconstruction_attempt") or "").strip():
                problems.append("changed_since_report has no reconstruction attempt")
            if finding.get("current_value") in (None, ""):
                problems.append("changed_since_report has no current value")
            if not str(finding.get("current_as_of") or "").strip():
                problems.append("changed_since_report has no current as-of date")
            resolved_values = _resolved_receipt_values(finding, receipt_updates)
            declared = finding.get("current_value")
            if declared not in (None, "") and not any(
                values_equal(declared, item) for item in resolved_values
            ):
                problems.append("current_value does not match the receipt")
            path, payload = _load_evidence_payload(
                finding, receipt_updates, sandbox, report_path)
            pointers = _json_pointers(finding, receipt_updates)
            as_of = str(finding.get("current_as_of") or "").strip()
            dates = []
            if payload is not None:
                dates = _dates_on_same_record(payload, pointers, declared)
            if not dates and path is not None:
                dates = _csv_dates_for_value(path, declared)
            if as_of:
                if not dates:
                    problems.append(
                        "current_as_of is not on the same record as the current value")
                elif not _date_matches(as_of, dates):
                    problems.append("current_as_of does not match evidence date")
        support_problem = _verdict_receipt_problem(finding, receipt_updates)
        if support_problem:
            problems.append(support_problem)
        target = discarded if problems else validated
        target.append({**finding, **receipt_updates,
                       **({"problems": problems} if problems else {})})
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


def is_currency_claim(quote: str) -> bool:
    return bool(_CURRENCY_CUE.search(quote or ""))


def _norm_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(key).lower())


def _is_date_field_name(key: str) -> bool:
    raw = str(key or "")
    lower = raw.lower()
    compact = _norm_key(raw)
    if compact in {_norm_key(item) for item in _SKIP_DATE_KEYS}:
        return False
    if lower in _PREFERRED_DATE_KEYS or compact in {
        _norm_key(item) for item in _PREFERRED_DATE_KEYS
    }:
        return True
    if lower.endswith("_date") or lower.endswith("_as_of") or lower.endswith("asof"):
        return True
    return False


def _pointer_token(key: str) -> str:
    return str(key).replace("~", "~0").replace("/", "~1")


def _walk_json(value, prefix: str = ""):
    if isinstance(value, dict):
        for key, child in value.items():
            pointer = f"{prefix}/{_pointer_token(key)}"
            yield pointer, str(key), child
            yield from _walk_json(child, pointer)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            pointer = f"{prefix}/{index}"
            yield pointer, str(index), child
            yield from _walk_json(child, pointer)


def _evidence_date_hits(sandbox: pathlib.Path, report_path: pathlib.Path | None) -> list[dict]:
    hits = []
    if sandbox is None or not sandbox.is_dir():
        return hits
    preferred_norm = {_norm_key(item) for item in _PREFERRED_DATE_KEYS}
    for path in sorted(sandbox.rglob("*.json")):
        if path.name in _SKIP_EVIDENCE_NAMES:
            continue
        if "artifact" in path.parts:
            continue
        rel = str(path.relative_to(sandbox))
        resolved, err = evidence_path(sandbox, rel, report_path)
        if err or resolved is None:
            continue
        try:
            payload = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        for pointer, key, child in _walk_json(payload):
            if isinstance(child, (dict, list)):
                continue
            if not _is_date_field_name(key):
                continue
            day = parse_date(child)
            if day is None:
                continue
            hits.append({
                "file": rel.replace("\\", "/"),
                "pointer": pointer,
                "key": key,
                "value": child,
                "day": day,
                "preferred": _norm_key(key) in preferred_norm,
            })
    return hits


def apply_currency_staleness(
        validated: list, ledger: list, sandbox: pathlib.Path,
        report_path: pathlib.Path | None) -> tuple[list, list]:
    """Ground data-currency dates against evidence date fields.

    When a report as-of/current-through date differs from a supplied evidence
    date field, the claim becomes contradicted/staleness with a JSON pointer
    receipt. not_checkable is not kept for that claim.
    """
    hits = _evidence_date_hits(sandbox, report_path)
    if not hits:
        return validated, ledger
    out = list(validated)
    touched: set[str] = set()
    for claim in ledger:
        quote = str(claim.get("quote") or "")
        if not is_currency_claim(quote):
            continue
        report_day = parse_date(quote)
        if report_day is None:
            continue
        preferred = [row for row in hits if row.get("preferred")]
        pool = preferred or hits
        mismatch = [row for row in pool if row["day"] != report_day]
        match = [row for row in pool if row["day"] == report_day]
        cid = str(claim.get("id") or "")
        existing = [row for row in out if str(row.get("claim_id") or "") == cid]
        if mismatch:
            hit = mismatch[0]
            if any(
                row.get("verdict") == "contradicted"
                and row.get("basis") == "evidence"
                for row in existing
            ):
                continue
            replacement = {
                "id": (existing[0].get("id") if existing else f"STALE-{cid}"),
                "claim_id": cid,
                "type": "staleness",
                "basis": "evidence",
                "verdict": "contradicted",
                "severity": "high",
                "importance": claim.get("importance") or "material",
                "report_quote": quote,
                "evidence_file": hit["file"],
                "evidence_json": [{"pointer": hit["pointer"], "value": hit["value"]}],
                "evidence_receipt_mode": "json-pointers",
                "explanation": (
                    "The report data-currency date differs from the evidence date."
                ),
            }
            if existing:
                keep_id = existing[0].get("id")
                out = [
                    row for row in out
                    if str(row.get("claim_id") or "") != cid
                    or row.get("verdict") == "contradicted"
                ]
                replacement["id"] = keep_id
            out.append(replacement)
            touched.add(cid)
            continue
        if match and any(row.get("verdict") == "not_checkable" for row in existing):
            hit = match[0]
            replacement = {
                "id": existing[0].get("id"),
                "claim_id": cid,
                "type": "staleness",
                "basis": "evidence",
                "verdict": "confirmed",
                "importance": claim.get("importance") or "material",
                "report_quote": quote,
                "evidence_file": hit["file"],
                "evidence_json": [{"pointer": hit["pointer"], "value": hit["value"]}],
                "evidence_receipt_mode": "json-pointers",
                "explanation": (
                    "The report data-currency date matches the evidence date."
                ),
            }
            out = [
                row for row in out
                if not (
                    str(row.get("claim_id") or "") == cid
                    and row.get("verdict") == "not_checkable"
                )
            ]
            out.append(replacement)
            touched.add(cid)
    by_claim: dict[str, list] = {}
    for check in out:
        by_claim.setdefault(str(check.get("claim_id") or ""), []).append(check)
    rank = {
        "error": 0,
        "contradicted": 0,
        "changed_since_report": 1,
        "confirmed": 2,
        "not_checkable": 3,
    }
    for claim in ledger:
        cid = str(claim.get("id") or "")
        if cid not in touched:
            continue
        options = by_claim.get(cid) or []
        if not options:
            continue
        best = sorted(options, key=lambda row: rank.get(row.get("verdict"), 9))[0]
        claim["outcome"] = best.get("verdict")
        claim["check_id"] = best.get("id")
    return out, ledger


def attach_claim_outcomes(claims: list, checks: list) -> list:
    rank = {
        "error": 0,
        "contradicted": 0,
        "changed_since_report": 1,
        "confirmed": 2,
        "not_checkable": 3,
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
    if isinstance(doc, list):
        return doc, None
    if not isinstance(doc, dict):
        raise ValueError("checks file must be a list or an object")
    for key in ("checks", "findings", "validated"):
        if isinstance(doc.get(key), list):
            return doc[key], doc
    raise ValueError("checks file has no checks array")


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


def load_internal_outcomes(path: pathlib.Path | None) -> list:
    if path is None or not path.is_file():
        return []
    try:
        doc = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError, TypeError):
        return []
    rows = doc.get("internal_outcomes")
    return list(rows) if isinstance(rows, list) else []


def _claims_for_internal(ledger: list, outcome: dict) -> list:
    """Match only on exact inventory-id intersection. No quote fallback."""
    ids = set(_outcome_inventory_ids(outcome))
    if not ids:
        return []
    found = []
    for claim in ledger:
        claim_ids = set(claim_inventory_ids(claim))
        if not claim_ids:
            continue
        if claim_ids & ids:
            found.append(claim)
    return found


def _internal_check(outcome: dict, claim: dict, check_id: str) -> dict:
    verdict = str(outcome.get("verdict") or "confirmed")
    importance = str(claim.get("importance") or outcome.get("importance") or "material")
    return {
        "id": check_id,
        "claim_id": claim.get("id"),
        "type": outcome.get("type") or "internal",
        "basis": "report",
        "verdict": verdict,
        "severity": normalize_severity(
            outcome.get("severity"), contradicted=verdict == "contradicted",
            importance=importance),
        "importance": importance,
        "report_quote": outcome.get("report_quote") or claim.get("quote") or "",
        "report_quote_2": outcome.get("report_quote_2"),
        "location": outcome.get("location") or claim.get("location"),
        "explanation": outcome.get("explanation") or "Deterministic internal check.",
        "found_by": "internal",
        "inventory_ids": list(outcome.get("inventory_ids") or claim_inventory_ids(claim)),
    }


DETERMINISTIC_VERDICTS = frozenset({"confirmed", "contradicted"})
HOST_OVERRIDE_VERDICTS = frozenset({
    "confirmed", "contradicted", "not_checkable", "changed_since_report", "error",
})


def _outcome_inventory_ids(outcome: dict) -> list[str]:
    raw_ids = outcome.get("inventory_ids") or []
    if isinstance(raw_ids, str):
        raw_ids = [raw_ids]
    out = []
    seen = set()
    for value in raw_ids:
        item = str(value or "").strip()
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def is_deterministic_conflict(row: dict) -> bool:
    if not isinstance(row, dict):
        return False
    if row.get("reason") == "deterministic-conflict":
        return True
    return any(
        str(item).startswith("deterministic-conflict")
        for item in (row.get("problems") or [])
    )


def _proven_internal(row: dict, claim: dict | None,
                     by_iid: dict) -> tuple[str | None, dict] | None:
    ids = set(claim_inventory_ids(row))
    if claim is not None:
        ids.update(claim_inventory_ids(claim))
    if not ids:
        return None
    hits = [(iid, by_iid[iid]) for iid in ids if iid in by_iid]
    if not hits:
        return None
    hits.sort(key=lambda item: 0 if item[1].get("verdict") == "contradicted" else 1)
    return hits[0]


def attach_internal_outcomes(validated: list, ledger: list,
                             outcomes: list) -> tuple[list, list, list]:
    """Merge code findings. Host cannot reverse or downgrade them."""
    discarded: list = []
    if not outcomes:
        return validated, ledger, discarded
    by_iid: dict[str, dict] = {}
    for outcome in outcomes:
        verdict = str(outcome.get("verdict") or "")
        if verdict not in DETERMINISTIC_VERDICTS:
            continue
        for iid in _outcome_inventory_ids(outcome):
            prev = by_iid.get(iid)
            if prev is None or (
                    verdict == "contradicted"
                    and prev.get("verdict") != "contradicted"):
                by_iid[iid] = outcome
    claims_by_id = {str(row.get("id") or ""): row for row in ledger}
    kept: list = []
    for row in validated:
        claim = claims_by_id.get(str(row.get("claim_id") or ""))
        hit = _proven_internal(row, claim, by_iid)
        if hit is None:
            kept.append(row)
            continue
        iid, outcome = hit
        host_v = str(row.get("verdict") or "")
        int_v = str(outcome.get("verdict") or "")
        if host_v == int_v:
            kept.append(row)
            continue
        if host_v in HOST_OVERRIDE_VERDICTS:
            target = iid or str(row.get("claim_id") or "")
            discarded.append({
                **row,
                "reason": "deterministic-conflict",
                "problems": [
                    "deterministic-conflict: "
                    f"host {host_v} conflicts with internal {int_v} "
                    f"for inventory id {target}"
                ],
            })
            continue
        kept.append(row)

    used = {str(row.get("id") or "") for row in kept}
    next_n = 1
    touched: set[str] = set()

    def new_id() -> str:
        nonlocal next_n
        while f"INT{next_n}" in used:
            next_n += 1
        cid = f"INT{next_n}"
        used.add(cid)
        next_n += 1
        return cid

    for outcome in outcomes:
        verdict = str(outcome.get("verdict") or "")
        if verdict not in DETERMINISTIC_VERDICTS:
            continue
        for claim in _claims_for_internal(ledger, outcome):
            cid = str(claim.get("id") or "")
            existing = [
                row for row in kept if str(row.get("claim_id") or "") == cid]
            if any(row.get("verdict") == verdict for row in existing):
                touched.add(cid)
                continue
            kept = [
                row for row in kept if str(row.get("claim_id") or "") != cid]
            kept.append(_internal_check(outcome, claim, new_id()))
            touched.add(cid)
    by_claim: dict[str, list] = {}
    for check in kept:
        by_claim.setdefault(str(check.get("claim_id") or ""), []).append(check)
    rank = {
        "error": 0,
        "contradicted": 0,
        "changed_since_report": 1,
        "confirmed": 2,
        "not_checkable": 3,
    }
    for claim in ledger:
        cid = str(claim.get("id") or "")
        if cid not in touched:
            continue
        options = by_claim.get(cid) or []
        if not options:
            continue
        best = sorted(options, key=lambda row: rank.get(row.get("verdict"), 9))[0]
        claim["outcome"] = best.get("verdict")
        claim["check_id"] = best.get("id")
    return kept, ledger, discarded


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
            discarded_claims.append({**claim, "problems": problems})
        else:
            kept.append(claim)
    return kept


def apply_inventory_importance(ledger: list, validated: list, inventory: dict) -> None:
    """Keep host importance from claiming a supporting inventory item as material."""
    by_id = {
        str(item.get("id") or ""): item
        for item in (inventory.get("items") or [])
        if isinstance(item, dict)
    }
    for claim in ledger:
        ids = claim_inventory_ids(claim)
        imps = [
            by_id[iid].get("importance") for iid in ids if iid in by_id]
        if imps and all(item == "supporting" for item in imps):
            claim["importance"] = "supporting"
    by_claim = {str(row.get("id") or ""): row for row in ledger}
    for check in validated:
        claim = by_claim.get(str(check.get("claim_id") or ""))
        if claim and claim.get("importance") == "supporting":
            check["importance"] = "supporting"


def load_arithmetic_findings(path: pathlib.Path | None) -> list:
    if path is None:
        return []
    doc = json.loads(path.read_text())
    out = []
    for item in doc.get("findings") or []:
        if not isinstance(item, dict):
            continue
        if item.get("check_id") == "ari_total_footing" or (
                item.get("tier") == "D" and item.get("family") == "internal_arithmetic"):
            out.append(item)
    return out


def attach_arithmetic_claims(ledger: list, findings: list) -> list:
    """Each arithmetic error maps to one ledger claim. Add a row when none match."""
    if not findings:
        return ledger
    seen = {str(row.get("id") or "") for row in ledger}
    next_n = 1
    for finding in findings:
        detail = finding.get("detail") or {}
        stated = detail.get("stated")
        if stated in (None, ""):
            continue
        matched = None
        for claim in ledger:
            if quantities_equal(claim.get("quote"), stated):
                matched = claim
                break
            if quote_in_text(str(stated), str(claim.get("quote") or "")):
                matched = claim
                break
        if matched is not None:
            if matched.get("outcome") not in {"error", "contradicted"}:
                matched["outcome"] = "error"
                matched["check_id"] = finding.get("check_id")
            matched["found_by"] = matched.get("found_by") or "arithmetic"
            continue
        while f"AR{next_n}" in seen:
            next_n += 1
        cid = f"AR{next_n}"
        seen.add(cid)
        next_n += 1
        loc = str(finding.get("location") or "")
        parts = loc.split("/")
        label = parts[2] if len(parts) == 3 else "Total"
        quote = str(finding.get("statement") or f"{label} {stated}")
        ledger.append({
            "id": cid,
            "quote": quote,
            "importance": "material",
            "found_by": "arithmetic",
            "outcome": "error",
            "check_id": finding.get("check_id"),
            "location": loc,
        })
    return ledger


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

    grounded_claims, discarded_claims = validate_claims(text, proposed_claims)
    claim_ids = {row["id"] for row in grounded_claims}
    validated, discarded = validate_receipts(
        text, sandbox, proposed, claim_ids, args.report)
    ledger = attach_claim_outcomes(grounded_claims, validated)
    try:
        arith = load_arithmetic_findings(args.findings)
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"accept: {exc}", file=sys.stderr)
        return 2
    ledger = attach_arithmetic_claims(ledger, arith)
    validated, ledger = apply_currency_staleness(
        validated, ledger, sandbox, args.report)
    inventory = None
    internal_outcomes: list = []
    if args.findings is not None and args.findings.is_file():
        try:
            findings_doc = json.loads(args.findings.read_text())
            inventory = findings_doc.get("inventory")
            internal_outcomes = list(findings_doc.get("internal_outcomes") or [])
        except (OSError, json.JSONDecodeError, TypeError):
            inventory = None
            internal_outcomes = []
    if not isinstance(inventory, dict):
        inventory = inventory_for(args.report)
    validated, ledger, internal_conflicts = attach_internal_outcomes(
        validated, ledger, internal_outcomes)
    discarded.extend(internal_conflicts)
    ledger = apply_host_classifications(ledger, discarded_claims, inventory)
    apply_inventory_importance(ledger, validated, inventory)
    inventory_cover = cover(inventory, ledger)
    accepted_ids = {
        str(row.get("id") or "").strip() for row in validated if row.get("id")}
    presentation, presentation_problems = validate_presentation(
        checks_doc, text, accepted_ids)
    payload = {
        "checks": validated,
        "validated": validated,
        "discarded": discarded,
        "proposed": len(proposed),
        "grounded": len(validated),
        "claims": ledger,
        "discarded_claims": discarded_claims,
        "claims_in_ledger": len(ledger),
        "claims_reached_by_a_check": sum(
            1 for row in ledger if row.get("outcome") not in (None, "not_reached")
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
        f"accept: {len(validated)} grounded, {len(discarded)} discarded of {len(proposed)}; "
        f"ledger {payload['claims_reached_by_a_check']} of {payload['claims_in_ledger']}"
    )
    for row in discarded_claims:
        print(f"  DISCARDED CLAIM {row.get('id')}: {'; '.join(row.get('problems') or [])}")
    for row in discarded:
        print(f"  DISCARDED {row.get('id')}: {'; '.join(row.get('problems') or [])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
