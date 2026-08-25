#!/usr/bin/env python3
"""Deterministic HTML table footing. No summation-flow. No network.

Writes a findings.json that render.py can consume. Non-HTML files get an
agentic_only stub so the host agent plus accept.py still produce an artifact.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import sys
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser


class _Tables(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self._table: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in {"script", "style"}:
            self._skip += 1
            return
        if self._skip:
            return
        if tag == "table":
            self._table = []
        elif tag == "tr" and self._table is not None:
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in {"script", "style"} and self._skip:
            self._skip -= 1
            return
        if self._skip:
            return
        if tag in {"td", "th"} and self._cell is not None and self._row is not None:
            self._row.append(re.sub(r"\s+", " ", "".join(self._cell)).strip())
            self._cell = None
        elif tag == "tr" and self._row is not None and self._table is not None:
            if any(self._row):
                self._table.append(self._row)
            self._row = None
        elif tag == "table" and self._table is not None:
            if self._table:
                self.tables.append(self._table)
            self._table = None

    def handle_data(self, data):
        if self._skip or self._cell is None:
            return
        self._cell.append(data)


def parse_number(text: str) -> Decimal | None:
    raw = text.strip().replace(",", "").replace("$", "").replace("%", "")
    raw = raw.replace("(", "-").replace(")", "")
    if not raw or not re.fullmatch(r"-?\d+(?:\.\d+)?", raw):
        return None
    try:
        return Decimal(raw)
    except InvalidOperation:
        return None


def is_total_label(text: str) -> bool:
    return bool(re.search(r"\btotals?\b", text, flags=re.I))


def footing_findings(tables: list[list[list[str]]]) -> tuple[list[dict], int]:
    findings = []
    checked = 0
    for table_index, table in enumerate(tables, start=1):
        if len(table) < 3:
            continue
        header, *body = table
        last = body[-1]
        if not last or not is_total_label(last[0]):
            continue
        components = body[:-1]
        width = max(len(header), max((len(row) for row in body), default=0))
        for col in range(1, width):
            values = []
            for row in components:
                if col >= len(row):
                    values = []
                    break
                number = parse_number(row[col])
                if number is None:
                    values = []
                    break
                values.append(number)
            if not values or col >= len(last):
                continue
            shown = parse_number(last[col])
            if shown is None:
                continue
            checked += 1
            computed = sum(values, Decimal("0"))
            delta = shown - computed
            # Money with cents: 1 cent. Counts: exact.
            sample = values[0]
            cents = sample.as_tuple().exponent < 0 or shown.as_tuple().exponent < 0
            allowance = Decimal("0.01") if cents else Decimal("0")
            if abs(delta) <= allowance:
                continue
            col_name = header[col] if col < len(header) and header[col] else f"column {col + 1}"
            findings.append({
                "check_id": "ari_total_footing",
                "family": "internal_arithmetic",
                "severity": "high",
                "tier": "D",
                "statement": (
                    f"The “{last[0]}” row in {col_name} shows {last[col]}, "
                    f"but the rows above sum to {computed}."
                ),
                "location": f"table{table_index}/{last[0]}/{col_name}",
                "claim_ids": [f"t{table_index}c{col}"],
                "detail": {
                    "stated": float(shown),
                    "computed": float(computed),
                    "discrepancy": float(delta),
                    "addends": [
                        {
                            "label": str(components[index][0] if components[index] else f"row {index + 1}"),
                            "value": float(values[index]),
                        }
                        for index in range(len(values))
                    ],
                },
            })
    return findings, checked


def findings_doc(report: pathlib.Path, findings: list[dict], *, html: bool,
                 arithmetic_checks: int = 0) -> dict:
    scripts = pathlib.Path(__file__).resolve().parent
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    from inventory import inventory_for
    digest = hashlib.sha256(report.read_bytes()).hexdigest()
    d_count = sum(1 for item in findings if item.get("tier") == "D")
    inventory = inventory_for(report)
    material_n = sum(
        1 for item in inventory.get("items") or []
        if item.get("importance") == "material")
    return {
        "source": {
            "path": str(report.name),
            "format": report.suffix.lower().lstrip(".") or "unknown",
            "sha256": digest,
        },
        "inventory": inventory,
        "coverage": {
            "claims_in_ledger": 0,
            "claims_reached_by_a_check": 0,
            "extractor_checkable_fraction": 0.0,
            "engine_checkable_fraction": 0.0,
            "inventory_material": material_n,
            "checks_registered": arithmetic_checks if html else 0,
            "checks_with_findings": len(findings),
            "checks_found_nothing": max(arithmetic_checks - len(findings), 0) if html else 0,
            "checks_errored": 0,
        },
        "headline": {
            "tier_d_defects": d_count,
            "tier_d_per_100_claims": (
                (100.0 * d_count / arithmetic_checks) if arithmetic_checks else 0
            ),
        },
        "findings": findings,
        "findings_truncated": False,
        "agentic_only": not html,
        "agentic_scan_completed": True,
        "extraction_method": None if html else "host-agent visible text",
        "verification": {
            "document": {
                "status": "complete" if html else "not_available",
                "detail": (
                    "Table footing ran on HTML."
                    if html else
                    "Rule-based document checks are not available for this file format."
                ),
            },
            "semantic": {
                "status": "not_run",
                "detail": "Semantic review is supplied separately by the host agent.",
            },
            "live_source": {"status": "not_run", "detail": None},
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--report", required=True, type=pathlib.Path)
    ap.add_argument("--out", required=True, type=pathlib.Path)
    args = ap.parse_args()
    if not args.report.is_file():
        print(f"html_arith: missing report {args.report}", file=sys.stderr)
        return 2

    html = args.report.suffix.lower() in {".html", ".htm"}
    findings: list[dict] = []
    arithmetic_checks = 0
    if html:
        parser = _Tables()
        parser.feed(args.report.read_text(errors="replace"))
        parser.close()
        findings, arithmetic_checks = footing_findings(parser.tables)

    doc = findings_doc(
        args.report, findings, html=html, arithmetic_checks=arithmetic_checks)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(doc, indent=2) + "\n")
    print(f"html_arith: {len(findings)} footing finding(s) → {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
