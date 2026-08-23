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
from decimal import Decimal, InvalidOperation
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
})


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


def _json_dates(payload) -> list[str]:
    found = []
    for obj in _json_objects(payload):
        if not isinstance(obj, dict):
            continue
        for key, value in obj.items():
            if not isinstance(value, str) or not value.strip():
                continue
            if key.lower() in _DATE_KEYS or _DATE.search(value):
                found.append(value.strip())
    return found


def _date_matches(declared: str, candidates: list[str]) -> bool:
    want = declared.strip()
    want_day = _DATE.search(want)
    for item in candidates:
        if item == want:
            return True
        if want_day and want_day.group(0) in item:
            return True
    return False


def _resolved_receipt_values(finding: dict, receipt_updates: dict, sandbox: pathlib.Path) -> list:
    values = []
    for group in receipt_updates.get("evidence_receipts") or []:
        for item in group.get("evidence_json") or []:
            if isinstance(item, dict) and "value" in item:
                values.append(item["value"])
    for item in receipt_updates.get("evidence_json") or finding.get("evidence_json") or []:
        if isinstance(item, dict) and "value" in item:
            values.append(item["value"])
    quote = receipt_updates.get("evidence_quote") or finding.get("evidence_quote")
    if quote:
        parsed = parse_quantity(quote)
        if parsed is not None:
            values.append(parsed)
        values.extend(
            parse_quantity(token) for token in _QTOKEN.findall(str(quote))
            if parse_quantity(token) is not None
        )
    name = str(finding.get("evidence_file") or receipt_updates.get("evidence_file") or "")
    path = sandbox / name if name else None
    if path is not None and path.suffix.lower() == ".json" and path.is_file():
        try:
            payload = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            payload = None
        if payload is not None:
            finding["_evidence_payload"] = payload
    return values


def validate_claims(report: str, proposed: list) -> tuple[list, list]:
    grounded, discarded = [], []
    seen = set()
    for claim in proposed:
        problems = []
        cid = str(claim.get("id") or "").strip()
        quote = claim.get("quote", "")
        importance = claim.get("importance")
        if not cid:
            problems.append("claim has no id")
        elif cid in seen:
            problems.append(f"claim id {cid!r} is duplicated")
        if importance not in {"material", "supporting"}:
            problems.append("claim importance is missing or unknown")
        if not quote_in_text(str(quote), report):
            problems.append("claim quote not found in visible report text")
        row = {
            "id": cid,
            "quote": quote,
            "importance": importance if importance in {"material", "supporting"} else "material",
        }
        if problems:
            discarded.append({**row, "problems": problems})
        else:
            seen.add(cid)
            grounded.append(row)
    return grounded, discarded


def validate_receipts(report: str, sandbox: pathlib.Path, proposed: list,
                      claim_ids: set[str]) -> tuple[list, list]:
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
            finding["severity"] = finding.get("severity") or "medium"
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
            resolved_values = _resolved_receipt_values(finding, receipt_updates, sandbox)
            declared = finding.get("current_value")
            if declared not in (None, "") and not any(
                values_equal(declared, item) for item in resolved_values
            ):
                problems.append("current_value does not match the receipt")
            payload = finding.pop("_evidence_payload", None)
            name = str(finding.get("evidence_file") or receipt_updates.get("evidence_file") or "")
            path = sandbox / name if name else None
            if payload is None and path is not None and path.suffix.lower() == ".json" and path.is_file():
                try:
                    payload = json.loads(path.read_text())
                except (json.JSONDecodeError, OSError):
                    payload = None
            dates = _json_dates(payload) if payload is not None else []
            as_of = str(finding.get("current_as_of") or "").strip()
            if dates and as_of and not _date_matches(as_of, dates):
                problems.append("current_as_of does not match evidence date")
        target = discarded if problems else validated
        target.append({**finding, **receipt_updates,
                       **({"problems": problems} if problems else {})})
    return validated, discarded


def attach_claim_outcomes(claims: list, checks: list) -> list:
    rank = {
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
    if not checks:
        return "not_run"
    material = [row for row in claims if row.get("importance") == "material"]
    pool = material or claims
    if not pool:
        return "complete"
    if all(row.get("outcome") not in (None, "not_reached") for row in pool):
        return "complete"
    return "partial"


def validate_presentation(doc, report: str) -> tuple[dict | None, list[str]]:
    if not isinstance(doc, dict) or "presentation" not in doc:
        return None, []
    pres = doc.get("presentation")
    if pres is None:
        return None, []
    problems = []
    if not isinstance(pres, dict):
        return None, ["presentation is not an object"]
    summary = pres.get("summary")
    if summary is not None and not isinstance(summary, str):
        problems.append("presentation.summary is not a string")
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
            if not isinstance(item, dict):
                problems.append(f"presentation.{name}[{index}] is not an object")
                continue
            text = str(item.get("text") or "").strip()
            quote = str(item.get("report_quote") or "").strip()
            if not text or not quote:
                problems.append(f"presentation.{name}[{index}] is incomplete")
                continue
            if not quote_in_text(quote, report):
                problems.append(
                    f"presentation.{name}[{index}] report_quote not found in visible report text")
                continue
            bucket.append({
                "id": str(item.get("id") or f"{name[:1].upper()}{index + 1}"),
                "text": text,
                "report_quote": quote,
            })
    if problems:
        return None, problems
    return {
        "summary": str(summary or "").strip(),
        "actions": cleaned_actions,
        "limits": cleaned_limits,
    }, []


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
    doc = json.loads(path.read_text())
    if isinstance(doc, list):
        return doc
    if isinstance(doc, dict) and isinstance(doc.get("claims"), list):
        return doc["claims"]
    raise ValueError("claims file has no claims array")


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
    args = ap.parse_args()

    if not args.report.is_file():
        return _missing(args.report, "report")
    if not args.checks.is_file():
        return _missing(args.checks, "checks")
    if not args.claims.is_file():
        return _missing(args.claims, "claims")
    if args.report_text is not None and not args.report_text.is_file():
        return _missing(args.report_text, "report-text")

    try:
        proposed, checks_doc = load_checks(args.checks)
        proposed_claims = load_claims(args.claims)
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

    grounded_claims, discarded_claims = validate_claims(text, proposed_claims)
    claim_ids = {row["id"] for row in grounded_claims}
    validated, discarded = validate_receipts(text, sandbox, proposed, claim_ids)
    ledger = attach_claim_outcomes(grounded_claims, validated)
    presentation, presentation_problems = validate_presentation(checks_doc, text)
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
