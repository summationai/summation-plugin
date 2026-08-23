#!/usr/bin/env python3
"""Keep or drop proposed checks by grounding them in the report and evidence.

A check survives when its quotes and pointers resolve. A bad row is discarded.
The run continues. Exit 0 when receipts.json was written.

Usage:
    accept.py --report <file> --checks checks.json --out receipts.json
              [--evidence-dir DIR] [--report-text visible.txt]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

EVIDENCE_SUFFIXES = frozenset({
    ".json", ".jsonl", ".txt", ".sql", ".csv", ".yaml", ".yml", ".md", ".html",
})
REPORT_ONLY_TYPES = frozenset({"internal", "logic", "arithmetic", "units", "selection"})
FALLBACK_VERDICTS = frozenset({
    "confirmed", "contradicted", "not_checkable", "changed_since_report",
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
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return FALLBACK_VERDICTS


KNOWN_VERDICTS = load_known_verdicts()
EVIDENCE_RECEIPT_VERDICTS = frozenset({
    "confirmed", "contradicted", "changed_since_report",
}) & KNOWN_VERDICTS


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


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
        if actual != receipt.get("value"):
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
        if all(key in obj and obj[key] == expected for key, expected in fragment.items()):
            return True, json.dumps(fragment, ensure_ascii=False, separators=(", ", ": "))
    return False, None


def resolve_json_pointer_receipts(
        sandbox: pathlib.Path, finding: dict, receipts: list) -> list | None:
    candidates = []
    for name in [finding.get("evidence_file"), *(finding.get("evidence_files") or [])]:
        name = str(name or "")
        if name and name not in candidates and (sandbox / name).is_file():
            candidates.append(name)
    grouped: dict[str, list] = {}
    for receipt in receipts:
        matched = None
        for name in candidates:
            ok, canonical = json_pointer_receipt(sandbox / name, [receipt])
            if ok:
                matched = (name, canonical[0])
                break
        if matched is None:
            return None
        name, canonical_receipt = matched
        grouped.setdefault(name, []).append(canonical_receipt)
    return [
        {"evidence_file": name, "evidence_json": grouped[name]}
        for name in candidates if name in grouped
    ]


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


def validate_receipts(report: str, sandbox: pathlib.Path, proposed: list) -> tuple[list, list]:
    def in_report(quote: str) -> bool:
        normalized = normalize(quote)
        return bool(normalized) and normalized in report

    validated, discarded = [], []
    for finding in proposed:
        problems = []
        receipt_updates = {}
        verdict = finding.get("verdict")
        if verdict not in KNOWN_VERDICTS:
            problems.append("verdict is missing or unknown")
        finding = {
            **finding,
            "basis": finding.get("basis") or (
                "report" if finding.get("type") in REPORT_ONLY_TYPES else "evidence"),
            "importance": finding.get("importance") or "material",
        }
        if verdict == "contradicted":
            finding["severity"] = finding.get("severity") or "medium"
        else:
            finding["severity"] = None
        if not in_report(finding.get("report_quote", "")):
            problems.append("report_quote not found in visible report text")
        second = finding.get("report_quote_2")
        basis = finding.get("basis")
        if second and basis == "report" and not in_report(second):
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
            evidence = sandbox / evidence_name if evidence_name else None
            json_receipts = finding.get("evidence_json") or []
            if json_receipts:
                resolved = resolve_json_pointer_receipts(sandbox, finding, json_receipts)
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
                    problems.append("JSON pointer receipt did not match an evidence file")
            elif not evidence_name or evidence is None or not evidence.exists():
                problems.append(f"evidence_file {evidence_name!r} missing")
            else:
                quote = normalize(finding.get("evidence_quote", ""))
                evidence_texts = (
                    load_text(evidence),
                    normalize(evidence.read_text(errors="replace")),
                )
                if quote and any(quote in text for text in evidence_texts):
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
        target = discarded if problems else validated
        target.append({**finding, **receipt_updates,
                       **({"problems": problems} if problems else {})})
    return validated, discarded


def load_checks(path: pathlib.Path) -> list:
    doc = json.loads(path.read_text())
    if isinstance(doc, list):
        return doc
    if not isinstance(doc, dict):
        raise ValueError("checks file must be a list or an object")
    for key in ("checks", "findings", "validated"):
        if isinstance(doc.get(key), list):
            return doc[key]
    raise ValueError("checks file has no checks array")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--report", required=True, type=pathlib.Path)
    ap.add_argument("--checks", required=True, type=pathlib.Path)
    ap.add_argument("--out", required=True, type=pathlib.Path)
    ap.add_argument("--evidence-dir", type=pathlib.Path, default=None)
    ap.add_argument("--report-text", type=pathlib.Path, default=None)
    args = ap.parse_args()

    if not args.report.is_file():
        print(f"accept: missing report {args.report}", file=sys.stderr)
        return 2
    if not args.checks.is_file():
        print(f"accept: missing checks {args.checks}", file=sys.stderr)
        return 2

    try:
        proposed = load_checks(args.checks)
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"accept: {exc}", file=sys.stderr)
        return 2

    sandbox = args.evidence_dir if args.evidence_dir is not None else args.report.parent
    text = report_text(args.report, args.report_text)
    if not text:
        print(
            "accept: no visible report text. Write report-visible.txt and pass --report-text.",
            file=sys.stderr,
        )
        return 2

    validated, discarded = validate_receipts(text, sandbox, proposed)
    payload = {
        "checks": validated,
        "validated": validated,
        "discarded": discarded,
        "proposed": len(proposed),
        "grounded": len(validated),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"accept: {len(validated)} grounded, {len(discarded)} discarded of {len(proposed)}")
    for row in discarded:
        print(f"  DISCARDED {row.get('id')}: {'; '.join(row.get('problems') or [])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
