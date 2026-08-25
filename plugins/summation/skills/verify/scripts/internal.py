"""Deterministic internal checks on a verify inventory. Standard library only.

Minimum families copied from summationai/alg coldverify:
- selection / declared sort (sel_declared_sort_violated)
- arithmetic / ratio consistency (ari)
- units / percent versus percentage points (uni_percent_vs_points)
- direction of a stated move (dir)
- period / display consistency (per)
"""
from __future__ import annotations

import re
import sys
from decimal import Decimal
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from html_arith import parse_number  # noqa: E402

RANK_DESC = re.compile(
    r"ranked from highest to lowest|highest to lowest|descending(?: order)?",
    re.I,
)
RANK_ASC = re.compile(
    r"ranked from lowest to highest|lowest to highest|ascending(?: order)?",
    re.I,
)
RANK_COMPLETE = re.compile(
    r"ranking is complete|follows the displayed|ranking is presented as final|"
    r"final for the quarter",
    re.I,
)
TOP_N = re.compile(r"\btop\s+(\d+)\b", re.I)
SOURCE_SNAP = re.compile(r"(?i)^source snapshot\b")
POINT_WORD = re.compile(
    r"percentage\s+points?|\bpoints?\b|\bppt\b|\bpps\b|\bbasis points?\b|\bbps\b",
    re.I,
)
PERCENT_WORD = re.compile(r"\bper\s?cent\b|\bpercent\b|%", re.I)
IMPROVE = re.compile(r"\bimproved\b|\bincreased\b|\bup\b|\bgrew\b|\brose\b", re.I)
DECLINE = re.compile(r"\bdeclined\b|\bdecreased\b|\bdown\b|\bfell\b|\bdropped\b", re.I)
CALC = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:on-time\s+deliveries)?\s*/\s*"
    r"(\d+(?:\.\d+)?)\s*(?:total(?:\s+deliveries)?)?\s*=\s*"
    r"(\d+(?:\.\d+)?)%?",
    re.I,
)
XLSX_LOC = re.compile(r"^(?P<sheet>.+)/(?P<col>[A-Z]+)(?P<row>\d+)$")
WEEK_ENDING = re.compile(r"week\s+end(?:ing|ed)", re.I)
MONEY_EPS = Decimal("0.02")
PCT_EPS = Decimal("0.06")


def _num(text: str) -> Decimal | None:
    return parse_number(text or "")


def _first_num(text: str) -> Decimal | None:
    direct = parse_number(text or "")
    if direct is not None:
        return direct
    for token in re.findall(r"\d[\d,]*(?:\.\d+)?", text or ""):
        parsed = parse_number(token)
        if parsed is not None:
            return parsed
    return None


def _is_percent(text: str) -> bool:
    return "%" in (text or "")


def _pct_text(value: Decimal, displayed: str | None = None) -> str:
    text = str(displayed or "").strip()
    if text.endswith("%"):
        return text
    quantized = value.quantize(Decimal("0.1"))
    return f"{quantized}%"


def _outcome(*, check_id: str, family: str, type_: str, verdict: str,
             inventory_ids: list[str], report_quote: str,
             report_quote_2: str | None = None, location: str | None = None,
             explanation: str, importance: str = "material",
             comparison: dict | None = None) -> dict:
    row = {
        "check_id": check_id,
        "family": family,
        "type": type_,
        "verdict": verdict,
        "basis": "report",
        "importance": importance,
        "severity": "high" if verdict == "contradicted" else None,
        "inventory_ids": list(inventory_ids),
        "report_quote": report_quote,
        "report_quote_2": report_quote_2,
        "location": location,
        "explanation": explanation,
        "found_by": "internal",
    }
    if comparison:
        row["comparison"] = comparison
    return row


def _xlsx_grid(items: list[dict]) -> dict:
    grid: dict[tuple[str, str, int], dict] = {}
    labels: dict[tuple[str, int], str] = {}
    for item in items:
        loc = str(item.get("location") or "")
        match = XLSX_LOC.match(loc)
        if not match:
            continue
        sheet, col, row = match.group("sheet"), match.group("col"), int(match.group("row"))
        grid[(sheet, col, row)] = item
        if col == "A":
            labels[(sheet, row)] = str(item.get("displayed") or "")
    return {"grid": grid, "labels": labels}


def _label_key(text: str) -> str:
    return re.sub(r"[^a-z]+", "", (text or "").lower())


def _rank_comparison(numbers: list[tuple[dict, Decimal]], labels: list[dict],
                     *, desc: bool) -> dict:
    operands = []
    for index, (item, _value) in enumerate(numbers):
        label = ""
        if index < len(labels):
            label = str(labels[index].get("displayed") or "").strip()
        displayed = str(item.get("displayed") or "").strip()
        operands.append({
            "label": label or f"item {index + 1}",
            "value": displayed,
            "location": item.get("location"),
        })
    result = ", ".join(
        f"{item['label']} {item['value']}".strip() for item in operands)
    return {
        "kind": "ordered_list",
        "formula": "highest to lowest" if desc else "lowest to highest",
        "result": result,
        "operands": operands,
    }


def _rank_pair_comparison(numbers: list[tuple[dict, Decimal]], labels: list[dict],
                          index: int) -> dict:
    item = numbers[index][0]
    label = (
        str(labels[index].get("displayed") or "").strip()
        if index < len(labels) else f"row {index + 1}"
    )
    value = str(item.get("displayed") or "").strip()
    return {
        "kind": "displayed_pair",
        "formula": "row label paired with displayed value",
        "result": f"position {index + 1}: {label} {value}".strip(),
        "operands": [
            {"label": "display position", "value": index + 1},
            {"label": "row label", "value": label,
             "location": labels[index].get("location") if index < len(labels) else None},
            {"label": "displayed value", "value": value,
             "location": item.get("location")},
        ],
    }


def _rank_structure_comparison(numbers: list[tuple[dict, Decimal]], text: str,
                               location) -> dict:
    return {
        "kind": "structure",
        "formula": "ranked row count",
        "result": len(numbers),
        "operands": [
            {"label": "ranked rows", "value": len(numbers)},
            {"label": "report statement", "value": text, "location": location},
        ],
    }


def _sel_rank(items: list[dict]) -> list[dict]:
    out: list[dict] = []
    for index, item in enumerate(items):
        shown = str(item.get("displayed") or "")
        desc = bool(RANK_DESC.search(shown))
        asc = bool(RANK_ASC.search(shown))
        if not desc and not asc:
            continue
        numbers: list[tuple[dict, Decimal]] = []
        labels: list[dict] = []
        summaries: list[dict] = []
        for follow in items[index + 1:]:
            text = str(follow.get("displayed") or "")
            if SOURCE_SNAP.search(text):
                break
            if RANK_COMPLETE.search(text):
                summaries.append(follow)
                continue
            value = _num(text)
            if value is not None and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text.strip()):
                numbers.append((follow, value))
                continue
            if value is None and text:
                if re.search(r"[.!?]", text) and len(text) > 48 and numbers:
                    break
                labels.append(follow)
        if len(numbers) < 2:
            continue
        violations = []
        for prev, cur in zip(numbers, numbers[1:]):
            if desc and cur[1] > prev[1]:
                violations.append((prev, cur))
            if asc and cur[1] < prev[1]:
                violations.append((prev, cur))
        comparison = _rank_comparison(numbers, labels, desc=desc)
        if violations:
            after = violations[0][1]
            quote2 = str(after[0].get("displayed") or "")
            if labels:
                after_id = after[0].get("id")
                after_i = next(
                    (i for i, row in enumerate(numbers) if row[0].get("id") == after_id),
                    None,
                )
                if after_i is not None and after_i < len(labels):
                    quote2 = str(labels[after_i].get("displayed") or quote2)
            out.append(_outcome(
                check_id="sel_declared_sort_violated",
                family="selection",
                type_="selection",
                verdict="contradicted",
                inventory_ids=[item.get("id")],
                report_quote=shown,
                report_quote_2=quote2,
                location=item.get("location"),
                explanation=(
                    "Displayed values do not follow the declared rank order."
                ),
                comparison=comparison,
            ))
            for row_index, (row, _value) in enumerate(numbers):
                out.append(_outcome(
                    check_id="sel_declared_sort_violated",
                    family="selection",
                    type_="selection",
                    verdict="confirmed",
                    inventory_ids=[row.get("id")],
                    report_quote=str(row.get("displayed") or ""),
                    location=row.get("location"),
                    explanation="The displayed value is present in the ranked list.",
                    comparison=_rank_pair_comparison(numbers, labels, row_index),
                ))
            for label_index, lab in enumerate(labels[:len(numbers)]):
                out.append(_outcome(
                    check_id="sel_declared_sort_violated",
                    family="selection",
                    type_="selection",
                    verdict="confirmed",
                    inventory_ids=[lab.get("id")],
                    report_quote=str(lab.get("displayed") or ""),
                    location=lab.get("location"),
                    explanation="The row label sits with a value in the ranked list.",
                    comparison=_rank_pair_comparison(numbers, labels, label_index),
                ))
            for summary in summaries:
                out.append(_outcome(
                    check_id="sel_declared_sort_violated",
                    family="selection",
                    type_="selection",
                    verdict="confirmed",
                    inventory_ids=[summary.get("id")],
                    report_quote=str(summary.get("displayed") or ""),
                    location=summary.get("location"),
                    explanation=(
                        "The closing ranking statement is present with the "
                        "displayed ordered values."
                    ),
                    comparison=_rank_structure_comparison(
                        numbers,
                        str(summary.get("displayed") or ""),
                        summary.get("location"),
                    ),
                ))
            top = TOP_N.search(shown) or TOP_N.search(
                str((items[index - 1].get("displayed") if index else "") or ""))
            if top and int(top.group(1)) == len(numbers) and index:
                title = items[index - 1]
                out.append(_outcome(
                    check_id="sel_declared_sort_violated",
                    family="selection",
                    type_="selection",
                    verdict="confirmed",
                    inventory_ids=[title.get("id")],
                    report_quote=str(title.get("displayed") or ""),
                    location=title.get("location"),
                    explanation="The displayed set size matches the stated top-N count.",
                    comparison={
                        "kind": "identity",
                        "formula": "stated top-N count versus displayed rows",
                        "stated": int(top.group(1)),
                        "result": len(numbers),
                        "operands": [
                            {"label": "stated top-N", "value": int(top.group(1)),
                             "location": title.get("location")},
                            {"label": "displayed ranked rows", "value": len(numbers)},
                        ],
                    },
                ))
            continue
        out.append(_outcome(
            check_id="sel_declared_sort_violated",
            family="selection",
            type_="selection",
            verdict="confirmed",
            inventory_ids=[item.get("id")],
            report_quote=shown,
            location=item.get("location"),
            explanation="Displayed values follow the declared rank order.",
            comparison=comparison,
        ))
        for row, _value in numbers:
            out.append(_outcome(
                check_id="sel_declared_sort_violated",
                family="selection",
                type_="selection",
                verdict="confirmed",
                inventory_ids=[row.get("id")],
                report_quote=str(row.get("displayed") or ""),
                location=row.get("location"),
                explanation="The displayed value is consistent with the declared rank order.",
                comparison=comparison,
            ))
        for lab in labels:
            out.append(_outcome(
                check_id="sel_declared_sort_violated",
                family="selection",
                type_="selection",
                verdict="confirmed",
                inventory_ids=[lab.get("id")],
                report_quote=str(lab.get("displayed") or ""),
                location=lab.get("location"),
                explanation="The row label sits with a value in the declared rank order.",
                comparison=comparison,
            ))
        for summary in summaries:
            out.append(_outcome(
                check_id="sel_declared_sort_violated",
                family="selection",
                type_="selection",
                verdict="confirmed",
                inventory_ids=[summary.get("id")],
                report_quote=str(summary.get("displayed") or ""),
                location=summary.get("location"),
                explanation="The ranking statement matches the displayed order.",
                comparison=comparison,
            ))
        top = TOP_N.search(shown) or TOP_N.search(
            str((items[index - 1].get("displayed") if index else "") or ""))
        if not top and index:
            top = TOP_N.search(str(items[index - 1].get("displayed") or ""))
        if top and int(top.group(1)) == len(numbers) and index:
            title = items[index - 1]
            out.append(_outcome(
                check_id="sel_declared_sort_violated",
                family="selection",
                type_="selection",
                verdict="confirmed",
                inventory_ids=[title.get("id")],
                report_quote=str(title.get("displayed") or ""),
                location=title.get("location"),
                explanation="The displayed set size matches the stated top-N count.",
                comparison=comparison,
            ))
    return out


def _ari_xlsx(items: list[dict]) -> list[dict]:
    packed = _xlsx_grid(items)
    grid, labels = packed["grid"], packed["labels"]
    out: list[dict] = []
    columns: dict[tuple[str, str], dict[int, dict]] = {}
    for (sheet, col, row), item in grid.items():
        columns.setdefault((sheet, col), {})[row] = item
    for (sheet, col), rows in columns.items():
        if col == "A":
            continue
        by_key: dict[str, tuple[int, dict, Decimal]] = {}
        for row, item in rows.items():
            label = _label_key(labels.get((sheet, row), ""))
            value = _num(str(item.get("displayed") or ""))
            if value is None or not label:
                continue
            if "revenue" in label and "cost" not in label:
                by_key["revenue"] = (row, item, value)
            elif "costofgood" in label or label in {"cogs", "cost"}:
                by_key["cogs"] = (row, item, value)
            elif "grossprofit" in label or label == "profit":
                by_key["gp"] = (row, item, value)
            elif "grossmargin" in label or label == "margin":
                by_key["margin"] = (row, item, value)
        if {"revenue", "cogs", "gp"} <= set(by_key):
            rev, cogs, gp = by_key["revenue"], by_key["cogs"], by_key["gp"]
            computed = rev[2] - cogs[2]
            comparison = {
                "kind": "identity",
                "formula": "revenue minus cost of goods",
                "result": str(gp[1].get("displayed") or computed),
                "operands": [
                    {
                        "label": "revenue",
                        "value": str(rev[1].get("displayed") or rev[2]),
                        "location": rev[1].get("location"),
                    },
                    {
                        "label": "cost of goods",
                        "value": str(cogs[1].get("displayed") or cogs[2]),
                        "location": cogs[1].get("location"),
                    },
                    {
                        "label": "gross profit",
                        "value": str(gp[1].get("displayed") or gp[2]),
                        "location": gp[1].get("location"),
                    },
                ],
            }
            if abs(computed - gp[2]) <= MONEY_EPS:
                for key in ("revenue", "cogs", "gp"):
                    _row, item, _val = by_key[key]
                    out.append(_outcome(
                        check_id="ari_ratio_consistency",
                        family="internal_arithmetic",
                        type_="arithmetic",
                        verdict="confirmed",
                        inventory_ids=[item.get("id")],
                        report_quote=str(item.get("displayed") or ""),
                        location=item.get("location"),
                        explanation="Gross profit equals revenue minus cost of goods.",
                        comparison=comparison,
                    ))
            else:
                out.append(_outcome(
                    check_id="ari_ratio_consistency",
                    family="internal_arithmetic",
                    type_="arithmetic",
                    verdict="contradicted",
                    inventory_ids=[gp[1].get("id")],
                    report_quote=str(gp[1].get("displayed") or ""),
                    report_quote_2=str(rev[1].get("displayed") or ""),
                    location=gp[1].get("location"),
                    explanation="Gross profit does not equal revenue minus cost of goods.",
                    comparison=comparison,
                ))
        if {"revenue", "gp", "margin"} <= set(by_key) and by_key["revenue"][2] != 0:
            rev, gp, margin = by_key["revenue"], by_key["gp"], by_key["margin"]
            computed = (gp[2] / rev[2]) * Decimal(100)
            shown = margin[2]
            comparison = {
                "kind": "identity",
                "formula": "gross profit divided by revenue",
                "result": str(margin[1].get("displayed") or shown),
                "operands": [
                    {
                        "label": "gross profit",
                        "value": str(gp[1].get("displayed") or gp[2]),
                        "location": gp[1].get("location"),
                    },
                    {
                        "label": "revenue",
                        "value": str(rev[1].get("displayed") or rev[2]),
                        "location": rev[1].get("location"),
                    },
                    {
                        "label": "gross margin",
                        "value": str(margin[1].get("displayed") or shown),
                        "location": margin[1].get("location"),
                    },
                ],
            }
            # Inventory stores 40.0% as 40.0 after parse_number.
            if abs(computed - shown) <= PCT_EPS:
                out.append(_outcome(
                    check_id="ari_ratio_consistency",
                    family="internal_arithmetic",
                    type_="arithmetic",
                    verdict="confirmed",
                    inventory_ids=[margin[1].get("id")],
                    report_quote=str(margin[1].get("displayed") or ""),
                    location=margin[1].get("location"),
                    explanation="Gross margin equals gross profit divided by revenue.",
                    comparison=comparison,
                ))
            else:
                out.append(_outcome(
                    check_id="ari_ratio_consistency",
                    family="internal_arithmetic",
                    type_="arithmetic",
                    verdict="contradicted",
                    inventory_ids=[margin[1].get("id")],
                    report_quote=str(margin[1].get("displayed") or ""),
                    report_quote_2=str(gp[1].get("displayed") or ""),
                    location=margin[1].get("location"),
                    explanation="Gross margin does not equal gross profit divided by revenue.",
                    comparison=comparison,
                ))
    return out


def _uni_percent_points(items: list[dict]) -> list[dict]:
    percents = []
    notes = []
    for item in items:
        shown = str(item.get("displayed") or "")
        if shown.lower().startswith("note:") or IMPROVE.search(shown) or DECLINE.search(shown):
            if _first_num(shown) is not None:
                notes.append(item)
        if _is_percent(shown):
            value = _num(shown)
            if value is not None:
                percents.append((item, value))
    if len(percents) < 2 or not notes:
        return []
    out = []
    # Pair percents that share an xlsx row or that appear as two sequential percents.
    pairs = []
    by_row: dict[tuple[str, int], list] = {}
    for item, value in percents:
        loc = str(item.get("location") or "")
        match = XLSX_LOC.match(loc)
        if match:
            by_row.setdefault((match.group("sheet"), int(match.group("row"))), []).append(
                (item, value))
        else:
            pairs.append((item, value))
    for group in by_row.values():
        if len(group) >= 2:
            group = sorted(group, key=lambda row: str(row[0].get("location") or ""))
            pairs.extend([group[0], group[1]])
            old, new = group[0][1], group[1][1]
            point = new - old
            rel = None if old == 0 else (Decimal(100) * point / old)
            prior_text = _pct_text(old, str(group[0][0].get("displayed") or ""))
            current_text = _pct_text(new, str(group[1][0].get("displayed") or ""))
            point_abs = abs(point).quantize(Decimal("0.1"))
            direction = "increase" if point > 0 else "decrease"
            comparison = {
                "kind": "percentage_points",
                "prior": prior_text,
                "current": current_text,
                "result": f"{point_abs} percentage points",
                "direction": direction,
                "operands": [
                    {
                        "label": "prior margin",
                        "value": prior_text,
                        "location": group[0][0].get("location"),
                    },
                    {
                        "label": "current margin",
                        "value": current_text,
                        "location": group[1][0].get("location"),
                    },
                ],
            }
            for note in notes:
                text = str(note.get("displayed") or "")
                stated = _first_num(text)
                if stated is None:
                    continue
                says_points = bool(POINT_WORD.search(text))
                says_percent = bool(PERCENT_WORD.search(text)) and not says_points
                matches_points = abs(stated - abs(point)) <= PCT_EPS
                matches_rel = rel is not None and abs(stated - abs(rel)) <= PCT_EPS
                n_txt = (
                    str(stated.quantize(Decimal("1")))
                    if stated == stated.to_integral() else str(stated)
                )
                stated_display = (
                    f"{n_txt} percentage points" if says_points else f"{n_txt}%"
                )
                comparison = {
                    **comparison,
                    "stated": stated_display,
                }
                if matches_points and says_percent and not matches_rel:
                    out.append(_outcome(
                        check_id="uni_percent_vs_points",
                        family="units",
                        type_="units",
                        verdict="contradicted",
                        inventory_ids=[note.get("id")],
                        report_quote=text,
                        report_quote_2=str(group[1][0].get("displayed") or ""),
                        location=note.get("location"),
                        explanation=(
                            f"This is a {point_abs} percentage-point {direction}, "
                            f"not a {stated_display} relative {direction}."
                        ),
                        comparison=comparison,
                    ))
                elif (matches_points and says_points) or (
                        matches_rel and says_percent):
                    out.append(_outcome(
                        check_id="uni_percent_vs_points",
                        family="units",
                        type_="units",
                        verdict="confirmed",
                        inventory_ids=[note.get("id")],
                        report_quote=text,
                        location=note.get("location"),
                        explanation=(
                            f"The displayed move is a {point_abs} percentage-point "
                            f"{direction}, matching the note."
                        ),
                        comparison=comparison,
                    ))
                if IMPROVE.search(text) and point > 0:
                    out.append(_outcome(
                        check_id="dir_polarity_improved",
                        family="direction",
                        type_="internal",
                        verdict="confirmed",
                        inventory_ids=[note.get("id")],
                        report_quote=text,
                        location=note.get("location"),
                        explanation="The stated direction matches the displayed move.",
                    ))
                elif IMPROVE.search(text) and point < 0:
                    out.append(_outcome(
                        check_id="dir_polarity_improved",
                        family="direction",
                        type_="internal",
                        verdict="contradicted",
                        inventory_ids=[note.get("id")],
                        report_quote=text,
                        report_quote_2=str(group[1][0].get("displayed") or ""),
                        location=note.get("location"),
                        explanation="The stated direction does not match the displayed move.",
                    ))
                elif DECLINE.search(text) and point < 0:
                    out.append(_outcome(
                        check_id="dir_polarity_improved",
                        family="direction",
                        type_="internal",
                        verdict="confirmed",
                        inventory_ids=[note.get("id")],
                        report_quote=text,
                        location=note.get("location"),
                        explanation="The stated direction matches the displayed move.",
                    ))
    return out


def _ratio_comparison(left, right, computed, shown: str, stated_pct: str,
                      location) -> dict:
    result = f"{computed.quantize(Decimal('1')) if computed == computed.to_integral() else computed}%"
    return {
        "kind": "ratio",
        "formula": "on-time deliveries / total deliveries",
        "stated": stated_pct,
        "result": shown or f"{left} / {right} = {result}",
        "operands": [
            {"label": "on-time deliveries", "value": str(left), "location": location},
            {"label": "total deliveries", "value": str(right), "location": location},
        ],
    }


def _kpi_ratio(items: list[dict]) -> list[dict]:
    out = []
    calcs = []
    percents = []
    for item in items:
        shown = str(item.get("displayed") or "")
        match = CALC.search(shown)
        if match:
            left = Decimal(match.group(1))
            right = Decimal(match.group(2))
            stated = Decimal(match.group(3))
            calcs.append((item, left, right, stated, shown))
        if re.fullmatch(r"\d+(?:\.\d+)?%", shown.strip()):
            value = _num(shown)
            if value is not None:
                percents.append((item, value, shown))
    for item, left, right, stated, shown in calcs:
        if right == 0:
            continue
        computed = (left / right) * Decimal(100)
        calc_comparison = _ratio_comparison(
            left, right, computed, shown, f"{stated}%", item.get("location"))
        if abs(computed - stated) <= PCT_EPS:
            out.append(_outcome(
                check_id="ari_ratio_consistency",
                family="internal_arithmetic",
                type_="arithmetic",
                verdict="confirmed",
                inventory_ids=[item.get("id")],
                report_quote=shown,
                location=item.get("location"),
                explanation="The displayed quotient matches the stated percent.",
                comparison=calc_comparison,
            ))
            for other in items:
                text = str(other.get("displayed") or "")
                if other.get("id") == item.get("id"):
                    continue
                if text.lower().startswith("appendix") or "calculation" in text.lower():
                    out.append(_outcome(
                        check_id="ari_ratio_consistency",
                        family="internal_arithmetic",
                        type_="arithmetic",
                        verdict="confirmed",
                        inventory_ids=[other.get("id")],
                        report_quote=text,
                        report_quote_2=shown,
                        location=other.get("location"),
                        explanation="The appendix heading names the displayed calculation.",
                        comparison=calc_comparison,
                    ))
        else:
            out.append(_outcome(
                check_id="ari_ratio_consistency",
                family="internal_arithmetic",
                type_="arithmetic",
                verdict="contradicted",
                inventory_ids=[item.get("id")],
                report_quote=shown,
                location=item.get("location"),
                explanation="The displayed quotient does not match the stated percent.",
                comparison=calc_comparison,
            ))
        for pct_item, pct, pct_shown in percents:
            if pct_item.get("id") == item.get("id"):
                continue
            headline_comparison = _ratio_comparison(
                left, right, computed, shown, pct_shown, pct_item.get("location"))
            if abs(pct - computed) <= PCT_EPS:
                out.append(_outcome(
                    check_id="ari_ratio_consistency",
                    family="internal_arithmetic",
                    type_="arithmetic",
                    verdict="confirmed",
                    inventory_ids=[pct_item.get("id")],
                    report_quote=pct_shown,
                    report_quote_2=shown,
                    location=pct_item.get("location"),
                    explanation="The headline percent matches the displayed calculation.",
                    comparison=headline_comparison,
                ))
            else:
                out.append(_outcome(
                    check_id="ari_ratio_consistency",
                    family="internal_arithmetic",
                    type_="arithmetic",
                    verdict="contradicted",
                    inventory_ids=[pct_item.get("id")],
                    report_quote=pct_shown,
                    report_quote_2=shown,
                    location=pct_item.get("location"),
                    explanation="The headline percent does not match the displayed calculation.",
                    comparison=headline_comparison,
                ))
    return out


def _period_display(items: list[dict]) -> list[dict]:
    out = []
    weeks = [item for item in items if WEEK_ENDING.search(str(item.get("displayed") or ""))]
    if len(weeks) >= 2:
        week_comparison = {
            "kind": "identity",
            "result": "paired week-ending columns",
            "operands": [
                {
                    "label": "period",
                    "value": str(item.get("displayed") or ""),
                    "location": item.get("location"),
                }
                for item in weeks
            ],
        }
        for item in weeks:
            out.append(_outcome(
                check_id="per_period_display",
                family="period",
                type_="semantic",
                verdict="confirmed",
                inventory_ids=[item.get("id")],
                report_quote=str(item.get("displayed") or ""),
                location=item.get("location"),
                explanation="Paired week-ending columns are displayed together.",
                importance=str(item.get("importance") or "supporting"),
                comparison=week_comparison,
            ))
    periods = []
    for item in items:
        shown = str(item.get("displayed") or "")
        match = re.search(r"\b(Q[1-4]\s+\d{4}|Q[1-4])\b", shown, re.I)
        if match:
            periods.append((item, match.group(1).upper()))
    if len(periods) >= 2:
        token = periods[0][1]
        if all(token in row[1] or row[1] in token for row in periods):
            period_comparison = {
                "kind": "identity",
                "result": token,
                "operands": [
                    {
                        "label": "period",
                        "value": row[1],
                        "location": row[0].get("location"),
                    }
                    for row in periods
                ],
            }
            for item, _token in periods:
                if item.get("importance") != "material":
                    continue
                if _num(str(item.get("displayed") or "")) is not None:
                    continue
                out.append(_outcome(
                    check_id="per_period_display",
                    family="period",
                    type_="semantic",
                    verdict="confirmed",
                    inventory_ids=[item.get("id")],
                    report_quote=str(item.get("displayed") or ""),
                    location=item.get("location"),
                    explanation="Displayed period labels are consistent with each other.",
                    comparison=period_comparison,
                ))
    return out


def check_inventory(inventory: dict, visible: str | None = None) -> list[dict]:
    """Return confirmed/contradicted outcomes tied to inventory ids."""
    del visible
    items = list(inventory.get("items") or []) if isinstance(inventory, dict) else []
    if not items:
        return []
    out: list[dict] = []
    out.extend(_sel_rank(items))
    out.extend(_ari_xlsx(items))
    out.extend(_uni_percent_points(items))
    out.extend(_kpi_ratio(items))
    out.extend(_period_display(items))
    # One outcome per inventory id: contradicted wins.
    best: dict[str, dict] = {}
    for row in out:
        for iid in row.get("inventory_ids") or []:
            prev = best.get(iid)
            if prev is None or (
                    row.get("verdict") == "contradicted"
                    and prev.get("verdict") != "contradicted"):
                best[iid] = {**row, "inventory_ids": [iid]}
    return list(best.values())
