#!/usr/bin/env python3
"""Format-agnostic invariants for a public grade-artifact JSON+HTML pair.

These checks are structural audit helpers, not artifact approval. They do not
name fixtures. Callers feed any public artifact; mutations of a structurally
valid artifact must fail the same rules.
"""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, InvalidOperation
from html import unescape
import json
import re

from receipt_math import calculation_problem

PRIVATE_SIDECARS = (
    "findings.json", "receipts.json", "checks.json", "claims.json",
    "grade-artifact.json", "report-visible.txt", "ledger.json",
    "source-findings.json", "provenance.json",
)
ABS_PATH = re.compile(
    r"(?:/Users/|/home/|/var/folders/|/private/tmp/|/tmp/)[^\s\"'<]+",
    re.I,
)
SLIDE_TOKEN = re.compile(r"\b(?:slide|shape)\d+\b", re.I)
WINDOWS_PATH = re.compile(r"\b[A-Z]:\\[^\s\"'<]+", re.I)
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
JSON_POINTER_VISIBLE = re.compile(r"(?:^|\s)(?:/[A-Za-z0-9_~.-]+)+(?=\s|$)")
GENERIC_VERDICT = re.compile(
    r"The report claim\s+[\"“].*?[\"”]\s+is (?:confirmed|contradicted)",
    re.I | re.S,
)
ERROR_OUTCOMES = frozenset({"contradicted", "error"})
CSR_OUTCOMES = frozenset({"changed_since_report"})
OK_OUTCOMES = frozenset({"confirmed"})
NC_OUTCOMES = frozenset({
    "not_checkable", "not_reached", "used_for_internal_arithmetic", None,
})
MATERIAL_OUTCOMES = ERROR_OUTCOMES | CSR_OUTCOMES | OK_OUTCOMES | {"not_checkable"}
TEMPORAL_KEYS = (
    "report_value", "current_value", "current_as_of", "report_date",
    "reconstruction_attempt",
)
VAGUE_OPERAND = re.compile(r"^(?:row|operand|item|value)(?:\s+\d+)?$", re.I)
VAGUE_SOURCE = re.compile(
    r"^(?:source|evidence|supplied evidence|recorded evidence|live data)$", re.I)
SOURCE_ID = re.compile(r"^[A-Za-z][A-Za-z0-9._-]*$")
ISO_TIME = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)


def material_claims(art: dict) -> list[dict]:
    return [
        row for row in (art.get("claims") or [])
        if isinstance(row, dict)
        and row.get("classification") != "supporting_provenance"
        and row.get("importance") != "supporting"
    ]


def _string_values(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from _string_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from _string_values(child)


def _is_json_pointer(value: str) -> bool:
    text = str(value or "").strip()
    return bool(re.fullmatch(r"(?:/[A-Za-z0-9_~.-]+)+", text))


def supporting_claims(art: dict) -> list[dict]:
    return [
        row for row in (art.get("claims") or [])
        if isinstance(row, dict) and (
            row.get("classification") == "supporting_provenance"
            or row.get("importance") == "supporting"
        )
    ]


def visible_text(page: str) -> str:
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", page or "", flags=re.I | re.S)
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return unescape(re.sub(r"\s+", " ", text))


def parse_number(value) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float, Decimal)):
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None
    text = str(value).replace(",", "").replace("$", "").replace("%", "").strip()
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return Decimal(match.group(0))
    except (InvalidOperation, ValueError):
        return None


def numbers_in(value) -> set[Decimal]:
    found: set[Decimal] = set()
    if value is None or isinstance(value, bool):
        return found
    if isinstance(value, (int, float, Decimal)):
        parsed = parse_number(value)
        if parsed is not None:
            found.add(parsed)
        return found
    if isinstance(value, dict):
        for item in value.values():
            found.update(numbers_in(item))
        return found
    if isinstance(value, list):
        for item in value:
            found.update(numbers_in(item))
        return found
    for match in re.findall(r"-?\$?-?\d[\d,]*(?:\.\d+)?", str(value)):
        parsed = parse_number(match)
        if parsed is not None:
            found.add(parsed)
    return found


def mentions(page: str, value) -> bool:
    if value in (None, "", [], {}):
        return True
    blob = page or ""
    visible = visible_text(blob)
    raw = str(value).strip()
    if not raw:
        return True
    if raw in blob or raw in visible:
        return True
    escaped = (
        raw.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        .replace('"', "&quot;")
    )
    if escaped in blob:
        return True
    number = parse_number(value)
    if number is not None:
        candidates = {
            str(number),
            f"{number:,}",
            f"{number:,.0f}" if number == number.to_integral() else "",
            f"{number:,.2f}",
            f"{int(number):,}" if number == number.to_integral() else "",
        }
        if any(item and item in visible for item in candidates):
            return True
    day = re.search(r"(\d{4})-(\d{2})-(\d{2})", raw)
    if day:
        year, month, day_n = day.groups()
        months = (
            "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December",
        )
        pretty = f"{months[int(month) - 1]} {int(day_n)}, {year}"
        if pretty in visible:
            return True
    return False


def tile_counts(page: str) -> dict[str, int]:
    found = re.findall(r'data-bucket="([^"]+)" data-count="([^"]+)"', page or "")
    out = {}
    for slug, count in found:
        if count != "not-run":
            out[slug] = int(count)
    return out


def _card_chunks(page: str) -> list[str]:
    return re.findall(
        r'<div class="card [^"]+"[^>]*>(.*?)</div>\s*(?=<div class="card|</section>|$)',
        page or "",
        re.S,
    )


def _card_identity_problems(art: dict, page: str) -> list[str]:
    problems = []
    checks = {
        str(row.get("id") or ""): row
        for row in (art.get("evidence_checks") or [])
        if isinstance(row, dict)
    }
    seen = set()
    openings = re.findall(r'<div class="card [^"]+"(?P<attrs>[^>]*)>', page or "")
    for index, attrs in enumerate(openings, 1):
        ids = re.findall(r'\bdata-card-id="([^"]*)"', attrs)
        dispositions = re.findall(r'\bdata-disposition="([^"]*)"', attrs)
        if len(ids) != 1:
            problems.append(f"material card {index} must have exactly one data-card-id")
            continue
        if len(dispositions) != 1:
            problems.append(
                f"material card {index} must have exactly one data-disposition")
            continue
        check_id = unescape(ids[0])
        disposition = unescape(dispositions[0])
        if check_id in seen:
            problems.append(f"material card id {check_id!r} is duplicated")
        seen.add(check_id)
        check = checks.get(check_id)
        if check is None:
            problems.append(f"material card id {check_id!r} has no accepted check")
            continue
        if check.get("importance") != "material":
            problems.append(f"material card id {check_id!r} is not a material check")
        if disposition != str(check.get("verdict") or ""):
            problems.append(
                f"material card {check_id!r} disposition does not match accepted verdict")
    return problems


def ledger_counts(art: dict) -> dict[str, int]:
    rows = material_claims(art)
    return {
        "errors": sum(1 for row in rows if row.get("outcome") in ERROR_OUTCOMES),
        "confirmed": sum(1 for row in rows if row.get("outcome") in OK_OUTCOMES),
        "today-differs": sum(1 for row in rows if row.get("outcome") in CSR_OUTCOMES),
        "not-checkable": sum(
            1 for row in rows
            if row.get("outcome") in NC_OUTCOMES
        ),
        "material": len(rows),
    }


def _operand_contract_problem(value, prefix: str) -> str | None:
    if not isinstance(value, dict):
        return f"{prefix} is not an object"
    if set(value) != {"label", "value", "location"}:
        return f"{prefix} does not have exactly label, value, and location"
    label = str(value.get("label") or "").strip()
    location = str(value.get("location") or "").strip()
    if not label or VAGUE_OPERAND.fullmatch(label):
        return f"{prefix}.label is missing or vague"
    if not location:
        return f"{prefix}.location is missing"
    if value.get("value") in (None, "") or isinstance(value.get("value"), bool):
        return f"{prefix}.value is missing"
    return None


def _substantive(value) -> bool:
    text = str(value or "").strip()
    return bool(
        len(re.findall(r"[A-Za-z0-9%$]+", text)) >= 6
        and re.search(r"[.!?]$", text)
    )


def audit_json(art: dict) -> list[str]:
    problems = []
    if not isinstance(art, dict):
        return ["artifact is not an object"]
    blob = json.dumps(art, ensure_ascii=False, sort_keys=True, default=str)
    if ABS_PATH.search(blob):
        problems.append("absolute path in public JSON")
    if WINDOWS_PATH.search(blob):
        problems.append("Windows path in public JSON")
    for name in PRIVATE_SIDECARS:
        if name in blob:
            problems.append(f"private sidecar name {name} in public JSON")
    if SLIDE_TOKEN.search(blob):
        problems.append("raw slide/shape token in public JSON")
    if any(_is_json_pointer(value) for value in _string_values(art)):
        problems.append("raw JSON pointer in public JSON")
    if TENANT_IDENTIFIER.search(blob):
        problems.append("tenant identifier in public JSON")
    if CREDENTIAL.search(blob) or BEARER.search(blob):
        problems.append("credential in public JSON")
    material = material_claims(art)
    supporting = supporting_claims(art)
    ids = [row.get("id") for row in material]
    if len(ids) != len(set(ids)):
        problems.append("material claim ids are not unique")
    checks = list(art.get("evidence_checks") or [])
    check_ids = [row.get("id") for row in checks]
    if len(check_ids) != len(set(check_ids)):
        problems.append("public evidence check ids are not unique")
    if any(not SOURCE_ID.fullmatch(str(check_id or "")) for check_id in check_ids):
        problems.append("public evidence check id is not stable or public-safe")
    contradicted_checks = [
        row for row in checks if isinstance(row, dict)
        and row.get("verdict") == "contradicted"
    ]
    if (art.get("evidence_findings") or []) != contradicted_checks:
        problems.append("evidence_findings do not match contradicted public checks")
    sources = list(art.get("sources") or [])
    source_ids = [str(row.get("id") or "") for row in sources if isinstance(row, dict)]
    if len(source_ids) != len(set(source_ids)):
        problems.append("retained source ids are not unique")
    source_map = {
        str(row.get("id") or ""): row for row in sources if isinstance(row, dict)
    }
    for source in sources:
        if not isinstance(source, dict):
            problems.append("retained source is not an object")
            continue
        source_id = str(source.get("id") or "")
        kind = source.get("kind")
        allowed = {"id", "kind", "label", "evidence_file", "result_sha256", "retrieval"}
        if set(source) - allowed:
            problems.append(f"{source_id}: retained source has an unknown field")
        if not SOURCE_ID.fullmatch(source_id):
            problems.append(f"{source_id}: retained source id is invalid")
        if kind not in {"supplied_file", "live_tool"}:
            problems.append(f"{source_id}: retained source kind is invalid")
        label = str(source.get("label") or "").strip()
        filename = str(source.get("evidence_file") or "").strip()
        if not label or VAGUE_SOURCE.fullmatch(label):
            problems.append(f"{source_id}: retained source label is missing or vague")
        if (
            not filename
            or "/" in filename
            or "\\" in filename
            or filename in PRIVATE_SIDECARS
        ):
            problems.append(f"{source_id}: retained evidence filename is invalid")
        if not re.fullmatch(r"[0-9a-f]{64}", str(source.get("result_sha256") or "")):
            problems.append(f"{source_id}: retained source digest is invalid")
        if kind == "supplied_file" and source.get("retrieval") is not None:
            problems.append(f"{source_id}: static source carries live metadata")
        if kind == "live_tool":
            retrieval = source.get("retrieval")
            if not isinstance(retrieval, dict):
                problems.append(f"{source_id}: live source lacks retrieval metadata")
            elif set(retrieval) != {"retrieved_at", "tool", "arguments"}:
                problems.append(f"{source_id}: live retrieval metadata is incomplete")
            else:
                if not ISO_TIME.fullmatch(str(retrieval.get("retrieved_at") or "")):
                    problems.append(f"{source_id}: live retrieval time is invalid")
                if not str(retrieval.get("tool") or "").strip():
                    problems.append(f"{source_id}: live retrieval tool is missing")
                if not isinstance(retrieval.get("arguments"), dict):
                    problems.append(f"{source_id}: live retrieval arguments are invalid")
    finding_fingerprints = [
        (
            row.get("check_id"), row.get("location"), row.get("statement"),
            json.dumps(row.get("arithmetic"), sort_keys=True, default=str),
        )
        for row in (art.get("findings") or []) if isinstance(row, dict)
    ]
    if len(finding_fingerprints) != len(set(finding_fingerprints)):
        problems.append("public findings contain an exact duplicate")
    counts = ledger_counts(art)
    coverage = art.get("evidence_coverage") or {}
    if material:
        if int(coverage.get("document_claims_total") or 0) != counts["material"]:
            problems.append("coverage document_claims_total does not match material claims")
        if int(coverage.get("confirmed") or 0) != counts["confirmed"]:
            problems.append("coverage confirmed does not match material confirmed")
        if int(coverage.get("contradicted") or 0) != counts["errors"]:
            problems.append("coverage contradicted does not match material errors")
        if int(coverage.get("not_checkable") or 0) != counts["not-checkable"]:
            problems.append("coverage not_checkable does not match material not-checkable")
        if int(coverage.get("supporting_claims_reviewed") or 0) != len(supporting):
            problems.append("supporting provenance leaked into supporting_claims_reviewed mismatch")
        if int(coverage.get("material_claims_reviewed") or 0) != counts["material"]:
            problems.append("coverage material_claims_reviewed does not match material claims")
        reached = sum(
            row.get("outcome") not in (None, "not_reached") for row in material)
        if int(coverage.get("document_claims_reached") or 0) != reached:
            problems.append("coverage document_claims_reached does not match material ledger")
        if int(coverage.get("claim_outcomes_proposed") or 0) != counts["material"]:
            problems.append("claim_outcomes_proposed does not match material ledger")
        if int(coverage.get("validated_outcomes") or 0) != reached:
            problems.append("validated_outcomes does not match material ledger")
        if any(row.get("classification") == "supporting_provenance" and row.get("outcome") in MATERIAL_OUTCOMES
               and row.get("importance") == "material" for row in (art.get("claims") or [])):
            problems.append("supporting provenance marked material")
        score = art.get("score") or {}
        n = counts["material"]
        d = counts["errors"]
        if n and score.get("kind") == "tier_d_per_100_claims":
            expected = 100.0 * d / n
            try:
                actual = float(score.get("value"))
            except (TypeError, ValueError):
                actual = None
            if actual is None or abs(actual - expected) > 0.01:
                problems.append("score does not equal 100 * material errors / material claims")
        verdict = art.get("verdict")
        if d and verdict != "fix_first":
            problems.append("material errors exist but verdict is not fix_first")
    coverage_not = int(coverage.get("not_checkable") or 0)
    if supporting and coverage_not == counts["not-checkable"] + len(supporting):
        problems.append("supporting provenance entered material not_checkable totals")
    supplied = int(coverage.get("evidence_files_supplied") or 0)
    cited = coverage.get("evidence_files_cited") or []
    if supplied != len(sources):
        problems.append("evidence_files_supplied does not match retained sources")
    expected_groups = [
        {"source_id": row.get("id"), "kind": row.get("kind"), "label": row.get("label")}
        for row in sources if isinstance(row, dict)
    ]
    if (coverage.get("provenance_groups") or []) != expected_groups:
        problems.append("provenance_groups do not match retained sources")
    has_evidence_outcome = any(
        row.get("basis") == "evidence"
        and row.get("verdict") in {"confirmed", "contradicted", "changed_since_report"}
        for row in checks
    )
    if has_evidence_outcome and supplied == 0:
        problems.append("evidence outcomes exist but supplied evidence count is 0")
    if supplied == 0 and cited:
        problems.append("evidence cited but supplied count is 0")
    if supplied and len(cited) > supplied:
        problems.append("cited evidence files exceed supplied count")
    cited_source_ids = {
        str((row.get("public_receipt") or {}).get("source_id") or "")
        for row in checks
        if row.get("basis") == "evidence"
        and row.get("verdict") in {"confirmed", "contradicted", "changed_since_report"}
    }
    expected_cited = [
        str(source_map[source_id].get("label") or source_id)
        for source_id in sorted(cited_source_ids)
        if source_id in source_map
    ]
    if cited != expected_cited:
        problems.append("evidence_files_cited do not match receipt source links")
    evidence_checks = [row for row in checks if row.get("basis") == "evidence"]
    report_checks = [row for row in checks if row.get("basis") == "report"]
    expected_basis_counts = {
        "evidence_confirmed": sum(row.get("verdict") == "confirmed" for row in evidence_checks),
        "evidence_contradicted": sum(row.get("verdict") == "contradicted" for row in evidence_checks),
        "evidence_not_checkable": sum(row.get("verdict") == "not_checkable" for row in evidence_checks),
        "report_confirmed": sum(row.get("verdict") == "confirmed" for row in report_checks),
        "report_contradicted": sum(row.get("verdict") == "contradicted" for row in report_checks),
        "report_not_checkable": sum(row.get("verdict") == "not_checkable" for row in report_checks),
    }
    for key, expected in expected_basis_counts.items():
        if int(coverage.get(key) or 0) != expected:
            problems.append(f"coverage {key} does not match public checks")
    chosen_ids = {
        str(row.get("check_id") or "") for row in material
        if row.get("outcome") in {"confirmed", "contradicted", "changed_since_report", "not_checkable"}
    }
    public_ids = {str(row.get("id") or "") for row in checks}
    if chosen_ids != public_ids:
        problems.append("public evidence checks do not match the material outcome ledger")
    by_check = {str(row.get("id") or ""): row for row in checks}
    finding_ids = {str(row.get("check_id") or "") for row in (art.get("findings") or [])}
    for claim in material:
        outcome = claim.get("outcome")
        cid = str(claim.get("check_id") or "")
        if outcome in {"confirmed", "contradicted", "changed_since_report", "not_checkable"}:
            check = by_check.get(cid)
            if check is None or check.get("verdict") != outcome:
                problems.append(f"{claim.get('id')}: claim outcome has no matching public check")
        elif outcome == "error" and cid not in finding_ids:
            problems.append(f"{claim.get('id')}: machine error has no agent-authored public check")
    for check in checks:
        verdict = check.get("verdict")
        forbidden = {
            "comparison", "observed", "evidence_quote", "evidence_file",
            "evidence_json", "evidence_receipts", "current_source_kind",
        }
        leaked = sorted(forbidden & set(check))
        if leaked:
            problems.append(f"{check.get('id')}: raw receipt field {leaked[0]} is public")
        if verdict in {"confirmed", "contradicted", "changed_since_report"}:
            receipt = check.get("public_receipt")
            if not isinstance(receipt, dict):
                problems.append(f"{check.get('id')}: public_receipt is missing")
                continue
            allowed_receipt = {
                "report_operand", "decisive_operands", "explanation",
                "calculation", "source_id",
            }
            if set(receipt) - allowed_receipt:
                problems.append(f"{check.get('id')}: public_receipt has an unknown field")
            report_problem = _operand_contract_problem(
                receipt.get("report_operand"), "public_receipt.report_operand")
            if report_problem:
                problems.append(f"{check.get('id')}: {report_problem}")
            operands = receipt.get("decisive_operands")
            if not isinstance(operands, list) or not operands:
                problems.append(f"{check.get('id')}: decisive public operands are missing")
            else:
                for index, operand in enumerate(operands):
                    problem = _operand_contract_problem(
                        operand, f"public_receipt.decisive_operands[{index}]")
                    if problem:
                        problems.append(f"{check.get('id')}: {problem}")
            explanation = str(receipt.get("explanation") or "").strip()
            if not _substantive(explanation):
                problems.append(f"{check.get('id')}: public explanation is not substantive")
            calculation = receipt.get("calculation")
            if calculation is not None:
                if not isinstance(calculation, dict) or set(calculation) != {"expression", "result"}:
                    problems.append(f"{check.get('id')}: public calculation shape is invalid")
                else:
                    math_problem = calculation_problem(
                        calculation.get("expression"),
                        calculation.get("result"),
                        operands if isinstance(operands, list) else [],
                    )
                    if math_problem:
                        problems.append(f"{check.get('id')}: {math_problem}")
            if (
                check.get("basis") == "report"
                and calculation is None
                and isinstance(receipt.get("report_operand"), dict)
                and isinstance(operands, list)
                and operands
                and all(
                    parse_number(row.get("value")) == parse_number(
                        receipt["report_operand"].get("value")
                    )
                    if (
                        parse_number(row.get("value")) is not None
                        and parse_number(receipt["report_operand"].get("value")) is not None
                    )
                    else str(row.get("value")) == str(
                        receipt["report_operand"].get("value")
                    )
                    for row in operands if isinstance(row, dict)
                )
            ):
                problems.append(
                    f"{check.get('id')}: report receipt only repeats the report operand")
            source_id = str(receipt.get("source_id") or "")
            if check.get("basis") == "evidence" and source_id not in source_map:
                problems.append(f"{check.get('id')}: public source link is missing or unknown")
            if check.get("basis") == "report" and source_id:
                problems.append(f"{check.get('id')}: report receipt has an evidence source link")
        if verdict == "changed_since_report":
            report_n = parse_number(check.get("report_value"))
            current_n = parse_number(check.get("current_value"))
            if report_n is None or current_n is None:
                problems.append(f"{check.get('id')}: changed_since_report missing report or current value")
            elif report_n == current_n:
                problems.append(f"{check.get('id')}: changed_since_report values are equal")
            if not check.get("current_as_of"):
                problems.append(f"{check.get('id')}: changed_since_report missing current date")
            if not check.get("report_date") and not (art.get("source") or {}).get("report_date"):
                problems.append(f"{check.get('id')}: changed_since_report missing report date")
            if not check.get("reconstruction_attempt"):
                problems.append(f"{check.get('id')}: changed_since_report missing reconstruction attempt")
            receipt = check.get("public_receipt") or {}
            report_operand = receipt.get("report_operand") or {}
            decisive_values = [
                row.get("value") for row in receipt.get("decisive_operands") or []
                if isinstance(row, dict)
            ]
            if parse_number(report_operand.get("value")) != report_n:
                problems.append(
                    f"{check.get('id')}: temporal report value does not match report operand")
            if not any(parse_number(value) == current_n for value in decisive_values):
                problems.append(
                    f"{check.get('id')}: temporal current value is not a decisive operand")
        elif verdict == "not_checkable":
            if check.get("public_receipt") is not None:
                problems.append(f"{check.get('id')}: not_checkable has a public_receipt")
            if not str(check.get("report_quote") or "").strip():
                problems.append(f"{check.get('id')}: not_checkable report quote is missing")
            if not _substantive(check.get("explanation")):
                problems.append(f"{check.get('id')}: not_checkable explanation is not substantive")
    return problems


def audit_html(art: dict, page: str) -> list[str]:
    problems = []
    if not page:
        return ["missing HTML"]
    problems.extend(_card_identity_problems(art, page))
    visible = visible_text(page)
    if ABS_PATH.search(page) or ABS_PATH.search(visible):
        problems.append("absolute path in public HTML")
    if WINDOWS_PATH.search(page) or WINDOWS_PATH.search(visible):
        problems.append("Windows path in public HTML")
    for name in PRIVATE_SIDECARS:
        if name in page:
            problems.append(f"private sidecar name {name} in public HTML")
    if SLIDE_TOKEN.search(page):
        problems.append("raw slide/shape token in public HTML")
    if JSON_POINTER_VISIBLE.search(visible):
        problems.append("raw JSON pointer in public HTML")
    if TENANT_IDENTIFIER.search(visible):
        problems.append("tenant identifier in public HTML")
    if CREDENTIAL.search(visible) or BEARER.search(visible):
        problems.append("credential in public HTML")
    if "Read these no as unverified" in page:
        problems.append("broken not-checkable lede")
    if GENERIC_VERDICT.search(page):
        problems.append("generic verdict stamp in HTML")
    if "No accepted check reached this claim." in page:
        used = [
            row for row in material_claims(art)
            if row.get("verification_mode") == "internal_arithmetic"
            or row.get("found_by") == "arithmetic"
        ]
        if used:
            problems.append("internal-arithmetic value listed as no check reached")
    counts = ledger_counts(art)
    tiles = tile_counts(page)
    if counts["material"]:
        for slug in ("errors", "confirmed", "today-differs", "not-checkable"):
            if slug in tiles and tiles[slug] != counts[slug]:
                problems.append(f"tile {slug}={tiles.get(slug)} does not match ledger {counts[slug]}")
        numeric = sum(tiles.get(slug, 0) for slug in ("errors", "confirmed", "today-differs", "not-checkable"))
        if numeric != counts["material"]:
            problems.append("stat tiles do not reconcile with the material ledger")
    cov = art.get("evidence_coverage") or {}
    source_map = {
        str(row.get("id") or ""): row
        for row in (art.get("sources") or []) if isinstance(row, dict)
    }
    for check in art.get("evidence_checks") or []:
        receipt = check.get("public_receipt")
        if isinstance(receipt, dict):
            operands = [receipt.get("report_operand"), *(receipt.get("decisive_operands") or [])]
            for index, operand in enumerate(operands):
                if not isinstance(operand, dict):
                    continue
                for field in ("label", "value", "location"):
                    if not mentions(page, operand.get(field)):
                        problems.append(
                            f"{check.get('id')} public operand {index}.{field} does not render in HTML")
            if not mentions(page, receipt.get("explanation")):
                problems.append(f"{check.get('id')} public explanation does not render in HTML")
            calculation = receipt.get("calculation")
            if isinstance(calculation, dict):
                for field in ("expression", "result"):
                    if not mentions(page, calculation.get(field)):
                        problems.append(
                            f"{check.get('id')} calculation.{field} does not render in HTML")
            source_id = str(receipt.get("source_id") or "")
            retained = source_map.get(source_id)
            if retained is not None:
                if not mentions(page, retained.get("label")):
                    problems.append(f"{check.get('id')} retained source label does not render")
                if retained.get("kind") == "supplied_file":
                    if "Supplied recorded evidence" not in visible:
                        problems.append(f"{check.get('id')} supplied evidence origin is not visible")
                elif retained.get("kind") == "live_tool" and "Actual live query" not in visible:
                    problems.append(f"{check.get('id')} live source origin is not visible")
        if check.get("verdict") == "changed_since_report":
            for key in TEMPORAL_KEYS:
                if not mentions(page, check.get(key)):
                    problems.append(f"{check.get('id')} temporal field {key} does not render in HTML")
    for card in _card_chunks(page):
        why = re.findall(r"<p>(.*?)</p>", card, re.S)
        if len(why) > 1 and "today-differs" not in card:
            texts = [re.sub(r"<[^>]+>", " ", item).strip() for item in why]
            if len(texts) != len(set(texts)):
                problems.append("duplicate explanation prose in a card")
        receipt = re.search(
            r'<div class="k">[^<]*</div><div class="q">(.*?)</div>\s*'
            r'<div class="k">[^<]*</div><div class="q">(.*?)</div>',
            card, re.S)
        if receipt and why:
            left = re.sub(r"<[^>]+>", " ", receipt.group(1))
            right = re.sub(r"<[^>]+>", " ", receipt.group(2))
            expl = re.sub(r"<[^>]+>", " ", why[0])
            if right.strip() and expl.strip() and right.strip() == expl.strip() == left.strip():
                problems.append("receipt echoes the claim as the calculation and the explanation")
    if not any(row.get("kind") == "live_tool" for row in source_map.values()):
        if "Actual live query" in visible:
            problems.append("static evidence is described as an actual live query")
    if not any(row.get("kind") == "supplied_file" for row in source_map.values()):
        if "Supplied recorded evidence" in visible:
            problems.append("live-only evidence is described as supplied recorded evidence")
    return problems


def audit_public_artifact(art: dict, page: str) -> list[str]:
    return audit_json(art) + audit_html(art, page)


def mutate_remove_operands(art: dict) -> dict:
    clone = deepcopy(art)
    for check in clone.get("evidence_checks") or []:
        receipt = check.get("public_receipt")
        if isinstance(receipt, dict):
            receipt.pop("decisive_operands", None)
            break
    return clone


def mutate_swap_operands(art: dict) -> dict:
    clone = deepcopy(art)
    for check in clone.get("evidence_checks") or []:
        receipt = check.get("public_receipt") or {}
        operands = receipt.get("decisive_operands") or []
        if operands and isinstance(operands[0], dict):
            operands[0]["value"] = "999999"
            calculation = receipt.get("calculation")
            if isinstance(calculation, dict):
                calculation["result"] = "999999"
            break
    return clone


def mutate_vague_operand_label(art: dict) -> dict:
    clone = deepcopy(art)
    for check in clone.get("evidence_checks") or []:
        receipt = check.get("public_receipt") or {}
        operands = receipt.get("decisive_operands") or []
        if operands and isinstance(operands[0], dict):
            operands[0]["label"] = "row 1"
            break
    return clone


def mutate_remove_explanation(art: dict) -> dict:
    clone = deepcopy(art)
    for check in clone.get("evidence_checks") or []:
        receipt = check.get("public_receipt")
        if isinstance(receipt, dict):
            receipt.pop("explanation", None)
            break
    return clone


def mutate_remove_source_link(art: dict) -> dict:
    clone = deepcopy(art)
    for check in clone.get("evidence_checks") or []:
        if check.get("basis") != "evidence":
            continue
        receipt = check.get("public_receipt")
        if isinstance(receipt, dict):
            receipt.pop("source_id", None)
            break
    return clone


def mutate_confirmed_calculation_to_contradiction(art: dict) -> dict:
    clone = deepcopy(art)
    for check in clone.get("evidence_checks") or []:
        if check.get("verdict") != "confirmed":
            continue
        receipt = check.get("public_receipt") or {}
        operands = receipt.get("decisive_operands") or []
        if len(operands) == 1:
            operands.append(deepcopy(operands[0]))
        if len(operands) >= 2:
            operands[0]["value"] = 12
            operands[1]["value"] = 1
            receipt["calculation"] = {"expression": "12 + 1", "result": 12}
        break
    return clone


def mutate_equalize_csr(art: dict) -> dict:
    clone = deepcopy(art)
    for check in clone.get("evidence_checks") or []:
        if check.get("verdict") == "changed_since_report":
            number = parse_number(check.get("report_value"))
            check["current_value"] = number if number is not None else check.get("report_value")
            break
    return clone


def mutate_remove_csr_report_value(art: dict) -> dict:
    clone = deepcopy(art)
    for check in clone.get("evidence_checks") or []:
        if check.get("verdict") == "changed_since_report":
            check.pop("report_value", None)
            break
    return clone


def mutate_hide_report_quote_2(art: dict) -> dict:
    clone = deepcopy(art)
    for check in clone.get("evidence_checks") or []:
        receipt = check.get("public_receipt")
        if isinstance(receipt, dict):
            receipt.pop("report_operand", None)
            break
    return clone


def mutate_duplicate_findings(art: dict) -> dict:
    clone = deepcopy(art)
    checks = list(clone.get("evidence_checks") or [])
    extra = [row for row in checks if row.get("verdict") == "contradicted"]
    if extra:
        clone["evidence_checks"] = checks + extra
    if clone.get("score"):
        clone["score"] = dict(clone["score"])
        clone["score"]["value"] = 0
    return clone


def mutate_alter_score(art: dict) -> dict:
    clone = deepcopy(art)
    score = dict(clone.get("score") or {"kind": "tier_d_per_100_claims", "value": 0})
    score["value"] = 0 if score.get("value") else 99
    clone["score"] = score
    return clone


def mutate_alter_counts(art: dict) -> dict:
    clone = deepcopy(art)
    coverage = dict(clone.get("evidence_coverage") or {})
    coverage["confirmed"] = int(coverage.get("confirmed") or 0) + 3
    coverage["contradicted"] = 0
    coverage["not_checkable"] = int(coverage.get("not_checkable") or 0) + 2
    clone["evidence_coverage"] = coverage
    return clone


def mutate_falsify_evidence_counts(art: dict) -> dict:
    clone = deepcopy(art)
    coverage = dict(clone.get("evidence_coverage") or {})
    coverage["evidence_files_supplied"] = 0
    coverage["evidence_files_cited"] = []
    clone["evidence_coverage"] = coverage
    return clone


def mutate_demote_evidence(art: dict) -> dict:
    clone = deepcopy(art)
    for check in clone.get("evidence_checks") or []:
        if check.get("verdict") in {
            "confirmed", "contradicted", "changed_since_report"
        }:
            check.pop("public_receipt", None)
            break
    return clone


def mutate_inject_paths(art: dict) -> dict:
    clone = deepcopy(art)
    checks = list(clone.get("evidence_checks") or [])
    if checks:
        checks[0] = dict(checks[0])
        receipt = dict(checks[0].get("public_receipt") or {})
        receipt["explanation"] = "See /Users/eric/secret/findings.json for exact details."
        checks[0]["public_receipt"] = receipt
        clone["evidence_checks"] = checks
    return clone


def mutate_inject_json_pointer(art: dict) -> dict:
    clone = deepcopy(art)
    checks = list(clone.get("evidence_checks") or [])
    if checks:
        checks[0] = dict(checks[0])
        receipt = dict(checks[0].get("public_receipt") or {})
        operand = dict(receipt.get("report_operand") or {})
        operand["location"] = "/secret/raw_pointer"
        receipt["report_operand"] = operand
        checks[0]["public_receipt"] = receipt
        clone["evidence_checks"] = checks
    return clone


def mutate_inject_slide_token(art: dict) -> dict:
    clone = deepcopy(art)
    claims = list(clone.get("claims") or [])
    if claims:
        claims[0] = dict(claims[0])
        claims[0]["location"] = "slide2/shape9"
        clone["claims"] = claims
    return clone


def mutate_inject_tenant_identifier(art: dict) -> dict:
    clone = deepcopy(art)
    clone["run_id"] = "tenant_id=customer-42"
    return clone


def mutate_inject_credential(art: dict) -> dict:
    clone = deepcopy(art)
    clone["limitations"] = list(clone.get("limitations") or []) + [
        "client_secret=do-not-publish"
    ]
    return clone


def mutate_static_evidence_to_live(art: dict) -> dict:
    clone = deepcopy(art)
    for source in clone.get("sources") or []:
        if source.get("kind") == "supplied_file":
            source["kind"] = "live_tool"
            break
    return clone
