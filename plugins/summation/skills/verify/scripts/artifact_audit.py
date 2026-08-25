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
COMPARATIVE_CLAIM = re.compile(
    r"\b(?:unchanged|increas\w*|decreas\w*|grew|rose|fell|prior|previous|"
    r"week[- ]over[- ]week|month[- ]over[- ]month|versus|vs\.?)\b",
    re.I,
)
GENERIC_VERDICT = re.compile(
    r"The report claim\s+[\"“].*?[\"”]\s+is (?:confirmed|contradicted)",
    re.I | re.S,
)
ERROR_OUTCOMES = frozenset({"contradicted", "error"})
CSR_OUTCOMES = frozenset({"changed_since_report"})
OK_OUTCOMES = frozenset({"confirmed", "used_for_internal_arithmetic"})
NC_OUTCOMES = frozenset({"not_checkable", "not_reached", None})
MATERIAL_OUTCOMES = ERROR_OUTCOMES | CSR_OUTCOMES | OK_OUTCOMES | {"not_checkable"}
RECEIPT_KEYS = (
    "report_quote", "evidence_quote", "evidence_file", "location",
    "evidence_location", "report_value", "current_value", "current_as_of", "report_date",
    "reconstruction_attempt",
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
        r'<div class="card [^"]+" data-kind="[^"]+">(.*?)</div>\s*(?=<div class="card|</section>|$)',
        page or "",
        re.S,
    )


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


def _comparison_proves_contradiction(check: dict) -> bool:
    comparison = check.get("comparison") if isinstance(check.get("comparison"), dict) else {}
    if not comparison:
        return False
    stated = parse_number(comparison.get("stated"))
    result = parse_number(comparison.get("result"))
    if stated is not None and result is not None and stated != result:
        return True
    if comparison.get("kind") == "ordered_list":
        values = []
        for item in comparison.get("operands") or []:
            number = parse_number(item.get("value") if isinstance(item, dict) else item)
            if number is not None:
                values.append(number)
        formula = str(comparison.get("formula") or "")
        if len(values) >= 2:
            desc = "highest" in formula
            ordered = values == sorted(values, reverse=desc)
            return not ordered
    if comparison.get("kind") == "percentage_points":
        stated_text = str(comparison.get("stated") or "")
        result_text = str(comparison.get("result") or "")
        if "percentage point" in result_text and "%" in stated_text and "point" not in stated_text:
            return True
    prior = parse_number(comparison.get("prior"))
    current = parse_number(comparison.get("current"))
    stated_text = str(comparison.get("stated") or "")
    if (
        prior is not None
        and current is not None
        and stated is not None
        and "%" in stated_text
        and "point" not in stated_text.lower()
    ):
        rel = None if prior == 0 else abs((current - prior) / prior) * Decimal(100)
        points = abs(current - prior)
        if rel is not None and abs(stated - points) <= Decimal("0.06") and abs(stated - rel) > Decimal("0.06"):
            return True
    return False


def _operands_match_report(check: dict) -> bool:
    report_nums = numbers_in(check.get("report_quote"))
    shown = numbers_in(check.get("observed")) | numbers_in(check.get("comparison"))
    shown |= numbers_in(check.get("evidence_quote"))
    comparison = check.get("comparison") if isinstance(check.get("comparison"), dict) else {}
    has_receipt = bool(
        check.get("observed")
        or check.get("evidence_quote")
        or comparison.get("operands")
        or comparison.get("result") is not None
    )
    if not report_nums or not shown:
        return has_receipt
    return bool(report_nums & shown)


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
            elif claim.get("location") and check.get("location") != claim.get("location"):
                problems.append(
                    f"{claim.get('id')}: public check location {check.get('location')!r} "
                    f"does not match claim location {claim.get('location')!r}")
        elif outcome == "error" and cid not in finding_ids:
            problems.append(f"{claim.get('id')}: error outcome has no matching public finding")
    for check in checks:
        if check.get("importance") == "supporting":
            continue
        verdict = check.get("verdict")
        if verdict in {"confirmed", "contradicted"}:
            comparison = check.get("comparison") if isinstance(check.get("comparison"), dict) else {}
            has_receipt = bool(
                check.get("observed")
                or check.get("evidence_quote")
                or comparison.get("operands")
                or comparison.get("result") is not None
            )
            if not has_receipt:
                problems.append(f"{check.get('id')}: confirmed/contradicted lacks shareable operands")
            if not check.get("report_quote"):
                problems.append(f"{check.get('id')}: confirmed/contradicted lacks report operand")
            if check.get("basis") == "report" and not comparison.get("operands"):
                problems.append(f"{check.get('id')}: report-only outcome lacks calculation operands")
            if check.get("basis") == "evidence" and not check.get("evidence_file"):
                problems.append(f"{check.get('id')}: evidence outcome lacks sanitized source label")
            if (COMPARATIVE_CLAIM.search(str(check.get("report_quote") or ""))
                    and len(check.get("observed") or []) < 2
                    and len(comparison.get("operands") or []) < 2
                    and not (
                        comparison.get("prior") is not None
                        and comparison.get("current") is not None
                    )):
                problems.append(f"{check.get('id')}: comparative claim lacks both decisive operands")
            if verdict == "confirmed" and not _operands_match_report(check) and not comparison.get("operands"):
                problems.append(f"{check.get('id')}: confirmed observed values do not match the report")
            if verdict == "confirmed" and _comparison_proves_contradiction(check):
                problems.append(f"{check.get('id')}: confirmed calculation proves a contradiction")
            if verdict == "contradicted":
                report_nums = numbers_in(check.get("report_quote"))
                shown = numbers_in(check.get("observed")) | numbers_in(check.get("evidence_quote"))
                differs = bool(shown) and bool(report_nums) and not (report_nums <= shown and shown <= report_nums)
                if shown and report_nums and report_nums == shown and not _comparison_proves_contradiction(check):
                    problems.append(f"{check.get('id')}: contradicted values are equal with no proving calculation")
                if not differs and not _comparison_proves_contradiction(check) and not shown:
                    if not comparison.get("operands"):
                        problems.append(f"{check.get('id')}: contradicted check has no differing operand or calculation")
        if verdict == "changed_since_report":
            report_n = parse_number(check.get("report_value"))
            current_n = parse_number(check.get("current_value"))
            if current_n is None and isinstance(check.get("comparison"), dict):
                current_n = parse_number(check["comparison"].get("current"))
            if report_n is None or current_n is None:
                problems.append(f"{check.get('id')}: changed_since_report missing report or current value")
            elif report_n == current_n:
                problems.append(f"{check.get('id')}: changed_since_report values are equal")
            if check.get("report_value") not in (None, "") and not (
                numbers_in(check.get("report_value"))
                & numbers_in(check.get("report_quote"))
            ):
                problems.append(f"{check.get('id')}: report value is not in the report quote")
            if not check.get("current_as_of"):
                problems.append(f"{check.get('id')}: changed_since_report missing current date")
            if not check.get("report_date") and not (art.get("source") or {}).get("report_date"):
                problems.append(f"{check.get('id')}: changed_since_report missing report date")
            if not check.get("reconstruction_attempt"):
                problems.append(f"{check.get('id')}: changed_since_report missing reconstruction attempt")
            if not check.get("evidence_file"):
                problems.append(f"{check.get('id')}: changed_since_report missing source label")
            if check.get("current_source_kind") not in {
                    "supplied_recorded_evidence", "live_query"}:
                problems.append(f"{check.get('id')}: changed_since_report missing source kind")
    return problems


def audit_html(art: dict, page: str) -> list[str]:
    problems = []
    if not page:
        return ["missing HTML"]
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
    supplied = int(cov.get("evidence_files_supplied") or 0)
    if supplied == 0 and re.search(r"Checked against the evidence supplied", page):
        problems.append("HTML claims supplied evidence while counts are zero")
    if supplied and re.search(r"Checked against the evidence supplied", page) is None:
        if "supplied evidence" not in visible.lower() and supplied > 0:
            if "Computed from the report" not in page and "supplied evidence" not in page:
                problems.append("HTML evidence copy does not match retained evidence metadata")
    for check in art.get("evidence_checks") or []:
        if check.get("importance") == "supporting":
            continue
        for key in RECEIPT_KEYS:
            value = check.get(key)
            if value in (None, "", [], {}):
                continue
            if key == "reconstruction_attempt" and check.get("verdict") != "changed_since_report":
                continue
            if not mentions(page, value):
                problems.append(f"{check.get('id')} public field {key} does not render in HTML")
        if check.get("verdict") in {"confirmed", "contradicted"}:
            if not mentions(visible, check.get("report_quote")):
                problems.append(f"{check.get('id')} report operand is not visible in HTML")
        if check.get("verdict") == "changed_since_report":
            report_number = parse_number(check.get("report_value"))
            current_number = parse_number(check.get("current_value"))
            if report_number is not None and not mentions(visible, report_number):
                problems.append(f"{check.get('id')} report-date value is not visible in HTML")
            if current_number is not None and not mentions(visible, current_number):
                problems.append(f"{check.get('id')} later value is not visible in HTML")
            card_candidates = [
                chunk for chunk in _card_chunks(page)
                if mentions(chunk, check.get("report_value"))
                and mentions(chunk, check.get("current_value"))
            ]
            card_visible = visible_text(card_candidates[0]) if card_candidates else visible
            kind = check.get("current_source_kind")
            if kind == "supplied_recorded_evidence":
                if "Supplied recorded evidence" not in card_visible:
                    problems.append(f"{check.get('id')} supplied evidence origin is not visible")
                if "actual live-query result" in card_visible:
                    problems.append(f"{check.get('id')} static evidence is described as a live query")
            elif kind == "live_query" and "Live query" not in card_visible:
                problems.append(f"{check.get('id')} live-query origin is not visible")
        comparison = check.get("comparison") if isinstance(check.get("comparison"), dict) else {}
        for item in comparison.get("operands") or []:
            if isinstance(item, dict) and not mentions(page, item.get("value")):
                problems.append(f"{check.get('id')} comparison operand does not render in HTML")
        for field in ("prior", "current", "stated", "result"):
            if comparison.get(field) not in (None, "", []) and not mentions(page, comparison.get(field)):
                problems.append(f"{check.get('id')} comparison.{field} does not render in HTML")
        for item in check.get("observed") or []:
            if isinstance(item, dict) and not mentions(page, item.get("value")):
                problems.append(f"{check.get('id')} observed value does not render in HTML")
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
    return problems


def audit_public_artifact(art: dict, page: str) -> list[str]:
    return audit_json(art) + audit_html(art, page)


def mutate_remove_operands(art: dict) -> dict:
    clone = deepcopy(art)
    for check in clone.get("evidence_checks") or []:
        if check.get("verdict") in {"confirmed", "contradicted"}:
            check.pop("observed", None)
            check.pop("evidence_quote", None)
            comparison = check.get("comparison")
            if isinstance(comparison, dict):
                comparison.pop("operands", None)
                comparison.pop("result", None)
                comparison.pop("prior", None)
                comparison.pop("current", None)
            break
    return clone


def mutate_swap_operands(art: dict) -> dict:
    clone = deepcopy(art)
    for check in clone.get("evidence_checks") or []:
        if check.get("verdict") == "confirmed":
            observed = check.get("observed") or []
            if observed and isinstance(observed[0], dict):
                observed[0]["value"] = "999999"
                break
            comparison = check.get("comparison")
            if isinstance(comparison, dict) and comparison.get("operands"):
                comparison["operands"][0]["value"] = "999999"
                comparison["result"] = "999999"
                break
    return clone


def mutate_confirmed_calculation_to_contradiction(art: dict) -> dict:
    clone = deepcopy(art)
    for check in clone.get("evidence_checks") or []:
        if check.get("verdict") == "confirmed":
            check["comparison"] = {
                "kind": "identity",
                "stated": 12,
                "result": 13,
                "operands": [
                    {"label": "report", "value": 12},
                    {"label": "calculated", "value": 13},
                ],
            }
            break
    return clone


def mutate_equalize_csr(art: dict) -> dict:
    clone = deepcopy(art)
    for check in clone.get("evidence_checks") or []:
        if check.get("verdict") == "changed_since_report":
            number = parse_number(check.get("report_value"))
            check["current_value"] = number if number is not None else check.get("report_value")
            comparison = check.get("comparison")
            if isinstance(comparison, dict):
                comparison["current"] = check["current_value"]
            break
    return clone


def mutate_remove_csr_report_value(art: dict) -> dict:
    clone = deepcopy(art)
    for check in clone.get("evidence_checks") or []:
        if check.get("verdict") == "changed_since_report":
            check.pop("report_value", None)
            comparison = check.get("comparison")
            if isinstance(comparison, dict):
                comparison.pop("stated", None)
            break
    return clone


def mutate_hide_report_quote_2(art: dict) -> dict:
    clone = deepcopy(art)
    for check in clone.get("evidence_checks") or []:
        if check.get("report_quote_2"):
            check.pop("report_quote_2", None)
            comparison = check.get("comparison")
            if isinstance(comparison, dict):
                comparison.pop("operands", None)
                comparison.pop("result", None)
            check.pop("observed", None)
            check.pop("evidence_quote", None)
            break
    return clone


def mutate_duplicate_findings(art: dict) -> dict:
    clone = deepcopy(art)
    findings = list(clone.get("findings") or [])
    if findings:
        clone["findings"] = findings + findings
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
        if check.get("verdict") == "changed_since_report":
            check.pop("current_value", None)
            check.pop("reconstruction_attempt", None)
            check.pop("evidence_file", None)
            check.pop("current_as_of", None)
            comparison = check.get("comparison")
            if isinstance(comparison, dict):
                comparison.pop("current", None)
            break
        if check.get("verdict") in {"confirmed", "contradicted"}:
            check.pop("observed", None)
            check.pop("comparison", None)
            check.pop("evidence_quote", None)
            break
    return clone


def mutate_inject_paths(art: dict) -> dict:
    clone = deepcopy(art)
    checks = list(clone.get("evidence_checks") or [])
    if checks:
        checks[0] = dict(checks[0])
        checks[0]["explanation"] = "See /Users/eric/secret/findings.json for details."
        clone["evidence_checks"] = checks
    skipped = dict(clone.get("checks") or {})
    skipped["skipped_note"] = "Outcome counts come from coverage in findings.json."
    clone["checks"] = skipped
    return clone


def mutate_inject_json_pointer(art: dict) -> dict:
    clone = deepcopy(art)
    checks = list(clone.get("evidence_checks") or [])
    if checks:
        checks[0] = dict(checks[0])
        checks[0]["evidence_location"] = "/secret/raw_pointer"
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
    for check in clone.get("evidence_checks") or []:
        if check.get("verdict") == "changed_since_report":
            check["current_source_kind"] = "live_query"
            break
    return clone
