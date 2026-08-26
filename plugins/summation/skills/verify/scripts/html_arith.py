#!/usr/bin/env python3
"""Write raw report inventory without assigning HTML table semantics.

The host selects explicit operands and totals. ``receipt_math.py`` recomputes
only the calculation the host authors in a public receipt. No network.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import sys
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


def footing_findings(tables: list[list[list[str]]]) -> tuple[list[dict], int, list[dict]]:
    """Do not infer totals from labels; expose cells through inventory only."""
    del tables
    return [], 0, []


def findings_doc(report: pathlib.Path, findings: list[dict], *, html: bool,
                 arithmetic_checks: int = 0, intake_error: str | None = None,
                 arithmetic_uses: list[dict] | None = None
                 ) -> dict:
    scripts = pathlib.Path(__file__).resolve().parent
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    from inventory import inventory_for
    digest = hashlib.sha256(report.read_bytes()).hexdigest()
    d_count = sum(1 for item in findings if item.get("tier") == "D")
    inventory = inventory_for(report)
    by_cell = {
        (str(item.get("location") or ""), str(item.get("displayed") or "")): item
        for item in (inventory.get("items") or [])
        if isinstance(item, dict) and item.get("id")
    }
    uses = list(arithmetic_uses or [])
    uses_by_coordinate = {}
    for use in uses:
        if not isinstance(use, dict):
            continue
        inventory_ids = []
        for addend in use.get("addends") or []:
            if not isinstance(addend, dict):
                continue
            item = by_cell.get((
                str(addend.get("coordinate") or ""),
                str(addend.get("displayed") or ""),
            ))
            addend["inventory_id"] = item.get("id") if item else None
            if item:
                inventory_ids.append(item["id"])
        stated_item = by_cell.get((
            str(use.get("coordinate") or ""),
            str(use.get("stated_displayed") or ""),
        ))
        use["stated_inventory_id"] = stated_item.get("id") if stated_item else None
        if stated_item:
            inventory_ids.append(stated_item["id"])
        use["inventory_ids"] = list(dict.fromkeys(inventory_ids))
        uses_by_coordinate[str(use.get("coordinate") or "")] = use
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        use = uses_by_coordinate.get(str(finding.get("coordinate") or ""))
        if use is None:
            continue
        finding["inventory_ids"] = list(use.get("inventory_ids") or [])
        finding["detail"]["addends"] = [
            {
                "inventory_id": row.get("inventory_id"),
                "displayed": row.get("displayed"),
                "value": row.get("value"),
                "coordinate": row.get("coordinate"),
            }
            for row in use.get("addends") or []
            if isinstance(row, dict)
        ]
    complete = bool(inventory.get("complete")) and not intake_error
    if intake_error:
        inventory = {
            **inventory,
            "complete": False,
            "items": [],
            "reason": intake_error,
        }
    material_n = 0
    reader = inventory.get("reader") or (
        "html" if html else report.suffix.lower().lstrip("."))
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
        "arithmetic_uses": uses,
        "findings_truncated": False,
        "agentic_only": not complete,
        "agentic_scan_completed": complete,
        "extraction_method": None if not complete else f"{reader} extract.py",
        "intake_error": intake_error or inventory.get("reason"),
        "verification": {
            "document": {
                "status": "complete" if complete else "not_available",
                "detail": None,
            },
            "semantic": {
                "status": "not_run",
                "detail": None,
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
        findings, arithmetic_checks, arithmetic_uses = footing_findings(parser.tables)

    doc = findings_doc(
        args.report, findings, html=html, arithmetic_checks=arithmetic_checks,
        arithmetic_uses=arithmetic_uses if html else None)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(doc, indent=2) + "\n")
    print(f"html_arith: {len(findings)} footing finding(s) → {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
