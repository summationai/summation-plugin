"""Deterministic machine candidates from a verify inventory.

These routines expose only exact candidate facts: inventory ids, displayed
values, coordinates, arithmetic results, and mismatch flags. They never emit a
claim verdict, a public label, a public location, or customer-facing prose.
"""
from __future__ import annotations

from decimal import Decimal
import re
import sys
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
SOURCE_SNAP = re.compile(r"(?i)^source snapshot\b")
POINT_WORD = re.compile(
    r"percentage\s+points?|\bpoints?\b|\bppt\b|\bpps\b|\bbasis points?\b|\bbps\b",
    re.I,
)
PERCENT_WORD = re.compile(r"\bper\s?cent\b|\bpercent\b|%", re.I)
CALC = re.compile(
    r"(\d+(?:\.\d+)?)\s*[^/\d]{0,60}/\s*"
    r"(\d+(?:\.\d+)?)\s*[^=\d]{0,60}=\s*"
    r"(\d+(?:\.\d+)?)\s*%?",
    re.I,
)
XLSX_LOC = re.compile(r"^(?P<sheet>.+)/(?P<col>[A-Z]+)(?P<row>\d+)$")
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


def _decimal(value: Decimal | None):
    if value is None:
        return None
    return int(value) if value == value.to_integral() else float(value)


def _fact(item: dict, numeric: Decimal | None = None) -> dict:
    row = {
        "inventory_id": str(item.get("id") or ""),
        "displayed": str(item.get("displayed") or ""),
        "coordinate": item.get("location"),
    }
    if numeric is not None:
        row["numeric"] = _decimal(numeric)
    return row


def _candidate(candidate_id: str, family: str, inventory_ids: list,
               facts: dict) -> dict:
    ids = []
    seen = set()
    for value in inventory_ids:
        item = str(value or "").strip()
        if item and item not in seen:
            seen.add(item)
            ids.append(item)
    return {
        "candidate_id": candidate_id,
        "family": family,
        "inventory_ids": ids,
        "facts": facts,
        "found_by": "internal",
    }


def _xlsx_grid(items: list[dict]) -> tuple[dict, dict]:
    grid: dict[tuple[str, str, int], dict] = {}
    row_text: dict[tuple[str, int], str] = {}
    for item in items:
        match = XLSX_LOC.match(str(item.get("location") or ""))
        if not match:
            continue
        sheet = match.group("sheet")
        col = match.group("col")
        row = int(match.group("row"))
        grid[(sheet, col, row)] = item
        if col == "A":
            row_text[(sheet, row)] = str(item.get("displayed") or "")
    return grid, row_text


def _label_key(text: str) -> str:
    return re.sub(r"[^a-z]+", "", (text or "").lower())


def _sel_rank(items: list[dict]) -> list[dict]:
    out = []
    for index, declaration in enumerate(items):
        text = str(declaration.get("displayed") or "")
        descending = bool(RANK_DESC.search(text))
        ascending = bool(RANK_ASC.search(text))
        if not descending and not ascending:
            continue
        values: list[tuple[dict, Decimal]] = []
        for item in items[index + 1:]:
            shown = str(item.get("displayed") or "")
            if SOURCE_SNAP.search(shown):
                break
            value = _num(shown)
            if value is None or re.fullmatch(r"\d{4}-\d{2}-\d{2}", shown.strip()):
                continue
            values.append((item, value))
        if len(values) < 2:
            continue
        ordered = [value for _item, value in values]
        mismatch = ordered != sorted(ordered, reverse=descending)
        out.append(_candidate(
            "sel_declared_sort",
            "selection",
            [declaration.get("id"), *[item.get("id") for item, _value in values]],
            {
                "kind": "ordered_values",
                "direction": "descending" if descending else "ascending",
                "declaration": _fact(declaration),
                "values": [_fact(item, value) for item, value in values],
                "mismatch": mismatch,
            },
        ))
    return out


def _ari_xlsx(items: list[dict]) -> list[dict]:
    grid, labels = _xlsx_grid(items)
    columns: dict[tuple[str, str], dict[int, dict]] = {}
    for (sheet, col, row), item in grid.items():
        if col != "A":
            columns.setdefault((sheet, col), {})[row] = item
    out = []
    for (sheet, col), rows in columns.items():
        values: dict[str, tuple[dict, Decimal]] = {}
        for row, item in rows.items():
            key = _label_key(labels.get((sheet, row), ""))
            number = _num(str(item.get("displayed") or ""))
            if number is None:
                continue
            if "revenue" in key and "cost" not in key:
                values["revenue"] = (item, number)
            elif "costofgood" in key or key in {"cogs", "cost"}:
                values["cogs"] = (item, number)
            elif "grossprofit" in key or key == "profit":
                values["gross_profit"] = (item, number)
            elif "grossmargin" in key or key == "margin":
                values["gross_margin"] = (item, number)
        if {"revenue", "cogs", "gross_profit"} <= set(values):
            revenue, cogs, stated = (
                values["revenue"], values["cogs"], values["gross_profit"])
            computed = revenue[1] - cogs[1]
            out.append(_candidate(
                "ari_gross_profit",
                "internal_arithmetic",
                [revenue[0].get("id"), cogs[0].get("id"), stated[0].get("id")],
                {
                    "kind": "arithmetic",
                    "operation": "subtract",
                    "operands": [_fact(revenue[0], revenue[1]), _fact(cogs[0], cogs[1])],
                    "stated": _fact(stated[0], stated[1]),
                    "computed": _decimal(computed),
                    "mismatch": abs(computed - stated[1]) > MONEY_EPS,
                },
            ))
        if {"revenue", "gross_profit", "gross_margin"} <= set(values):
            revenue = values["revenue"]
            profit = values["gross_profit"]
            stated = values["gross_margin"]
            if revenue[1] != 0:
                computed = (profit[1] / revenue[1]) * Decimal(100)
                out.append(_candidate(
                    "ari_gross_margin",
                    "internal_arithmetic",
                    [profit[0].get("id"), revenue[0].get("id"), stated[0].get("id")],
                    {
                        "kind": "arithmetic",
                        "operation": "percent_ratio",
                        "operands": [_fact(profit[0], profit[1]), _fact(revenue[0], revenue[1])],
                        "stated": _fact(stated[0], stated[1]),
                        "computed": _decimal(computed),
                        "mismatch": abs(computed - stated[1]) > PCT_EPS,
                    },
                ))
    return out


def _uni_percent_points(items: list[dict]) -> list[dict]:
    percents: list[tuple[dict, Decimal]] = []
    notes: list[dict] = []
    for item in items:
        shown = str(item.get("displayed") or "")
        if shown.strip().endswith("%"):
            value = _num(shown)
            if value is not None:
                percents.append((item, value))
        if _first_num(shown) is not None and (
            POINT_WORD.search(shown) or PERCENT_WORD.search(shown)
        ) and not shown.strip().endswith("%"):
            notes.append(item)
    by_row: dict[tuple[str, int], list[tuple[dict, Decimal]]] = {}
    for item, value in percents:
        match = XLSX_LOC.match(str(item.get("location") or ""))
        if match:
            by_row.setdefault((match.group("sheet"), int(match.group("row"))), []).append(
                (item, value))
    out = []
    for group in by_row.values():
        if len(group) < 2:
            continue
        group = sorted(group, key=lambda pair: str(pair[0].get("location") or ""))
        prior, current = group[0], group[1]
        points = current[1] - prior[1]
        relative = None if prior[1] == 0 else (points / prior[1]) * Decimal(100)
        for note in notes:
            stated = _first_num(str(note.get("displayed") or ""))
            if stated is None:
                continue
            note_text = str(note.get("displayed") or "")
            says_points = bool(POINT_WORD.search(note_text))
            says_percent = bool(PERCENT_WORD.search(note_text)) and not says_points
            mismatch = False
            if says_points:
                mismatch = abs(abs(points) - stated) > PCT_EPS
            elif says_percent and relative is not None:
                mismatch = abs(abs(relative) - stated) > PCT_EPS
            out.append(_candidate(
                "uni_percent_points",
                "units",
                [prior[0].get("id"), current[0].get("id"), note.get("id")],
                {
                    "kind": "percentage_change",
                    "prior": _fact(prior[0], prior[1]),
                    "current": _fact(current[0], current[1]),
                    "statement": _fact(note, stated),
                    "computed_percentage_points": _decimal(points),
                    "computed_relative_percent": _decimal(relative),
                    "mismatch": mismatch,
                },
            ))
    return out


def _kpi_ratio(items: list[dict]) -> list[dict]:
    out = []
    for item in items:
        shown = str(item.get("displayed") or "")
        match = CALC.search(shown)
        if not match:
            continue
        numerator = Decimal(match.group(1))
        denominator = Decimal(match.group(2))
        stated = Decimal(match.group(3))
        if denominator == 0:
            continue
        computed = (numerator / denominator) * Decimal(100)
        out.append(_candidate(
            "ari_displayed_ratio",
            "internal_arithmetic",
            [item.get("id")],
            {
                "kind": "arithmetic",
                "operation": "percent_ratio",
                "displayed": _fact(item),
                "numerator": _decimal(numerator),
                "denominator": _decimal(denominator),
                "stated_percent": _decimal(stated),
                "computed": _decimal(computed),
                "mismatch": abs(computed - stated) > PCT_EPS,
            },
        ))
    return out


def check_inventory(inventory: dict, visible: str | None = None) -> list[dict]:
    """Return exact machine candidates; the host agent decides every meaning."""
    del visible
    items = list(inventory.get("items") or []) if isinstance(inventory, dict) else []
    if not items:
        return []
    candidates = [
        *_sel_rank(items),
        *_ari_xlsx(items),
        *_uni_percent_points(items),
        *_kpi_ratio(items),
    ]
    out = []
    seen = set()
    for row in candidates:
        key = (
            row.get("candidate_id"),
            tuple(row.get("inventory_ids") or []),
            str((row.get("facts") or {}).get("kind") or ""),
        )
        if key not in seen:
            seen.add(key)
            out.append(row)
    return out
