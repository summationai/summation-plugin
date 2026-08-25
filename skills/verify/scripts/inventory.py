"""Machine claim inventory for the verify skill.

HTML: table cells via html_arith plus alg numparse over visible text.
PDF, xlsx, and pptx share this return shape. Those readers are not complete.
"""
from __future__ import annotations

import pathlib
import re
import sys
from html.parser import HTMLParser

SCRIPTS = pathlib.Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from html_arith import _Tables, is_total_label, parse_number  # noqa: E402
from numparse import iter_numbers  # noqa: E402

COMPLETED = frozenset({
    "confirmed", "contradicted", "not_checkable", "changed_since_report", "error",
})
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
READERS = {
    ".html": "html",
    ".htm": "html",
    ".md": "md",
    ".txt": "txt",
    ".pdf": "pdf",
    ".xlsx": "xlsx",
    ".xls": "xlsx",
    ".pptx": "pptx",
    ".ppt": "pptx",
}


def _visible_text(html: str) -> str:
    class _Text(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.parts: list[str] = []
            self._skip = 0

        def handle_starttag(self, tag, attrs):
            if tag.lower() in {"script", "style"}:
                self._skip += 1

        def handle_endtag(self, tag):
            if tag.lower() in {"script", "style"} and self._skip:
                self._skip -= 1

        def handle_data(self, data):
            if not self._skip:
                self.parts.append(data)

    parser = _Text()
    parser.feed(html)
    parser.close()
    return re.sub(r"\s+", " ", "".join(parser.parts))


def _material_token(tok) -> bool:
    shown = str(tok.value_displayed or "")
    if tok.currency_code or tok.unit in {"percent", "currency"}:
        return True
    if tok.scale not in {"ones", "unknown"}:
        return True
    if "," in shown:
        return True
    return False


def _html_items(path: pathlib.Path) -> list[dict]:
    raw = path.read_text(errors="replace")
    items: list[dict] = []
    seen: set[tuple] = set()

    def add(kind: str, displayed: str, location: str, importance: str) -> None:
        shown = re.sub(r"\s+", " ", displayed).strip()
        if not shown or DATE_RE.fullmatch(shown):
            return
        key = (kind, shown, location)
        if key in seen:
            return
        seen.add(key)
        items.append({
            "id": f"INV{len(items) + 1}",
            "kind": kind,
            "displayed": shown,
            "location": location,
            "importance": importance,
            "quote": shown,
        })

    tables = _Tables()
    tables.feed(raw)
    tables.close()
    for t_i, table in enumerate(tables.tables, start=1):
        header = table[0] if table else []
        for r_i, row in enumerate(table):
            if r_i == 0:
                continue
            row_label = row[0] if row else f"row {r_i}"
            kind = "table_total" if is_total_label(row_label) else "table_cell"
            for c_i, cell in enumerate(row):
                if c_i == 0:
                    continue
                if parse_number(cell) is None:
                    continue
                col = header[c_i] if c_i < len(header) and header[c_i] else f"column {c_i + 1}"
                add(kind, cell, f"table{t_i}/{row_label}/{col}", "material")

    captured = {item["displayed"] for item in items}
    visible = re.sub(r"(\d)([A-Za-z])", r"\1 \2", _visible_text(raw))
    for tok in iter_numbers(visible, mask_dates=True):
        shown = str(tok.value_displayed or "").strip()
        if not shown or shown in captured:
            continue
        if DATE_RE.search(shown):
            continue
        if _material_token(tok):
            add("prose_number", shown, "visible-text", "material")
            captured.add(shown)
    return items


def inventory_for(path: pathlib.Path) -> dict:
    """Same shape for every format. Only HTML is complete in this change."""
    suffix = path.suffix.lower()
    reader = READERS.get(suffix, suffix.lstrip(".") or "unknown")
    if reader == "html":
        items = _html_items(path)
        return {
            "reader": "html",
            "complete": True,
            "items": items,
            "reason": None,
        }
    return {
        "reader": reader,
        "complete": False,
        "items": [],
        "reason": f"no inventory reader for {reader}",
    }


def item_matches_claim(item: dict, claim: dict) -> bool:
    quote = str(claim.get("quote") or "")
    shown = str(item.get("displayed") or "")
    if not shown or not quote:
        return False
    if shown in quote:
        return True
    collapsed_q = quote.replace(",", "")
    collapsed_s = shown.replace(",", "")
    if collapsed_s and collapsed_s in collapsed_q:
        return True
    return False


def cover(inventory: dict, claims: list) -> dict:
    """Map material inventory items to claims and completed outcomes."""
    items = [
        item for item in (inventory.get("items") or [])
        if item.get("importance") == "material"
    ]
    missing = []
    accounted = 0
    completed = 0
    mapping = []
    for item in items:
        hit = None
        for claim in claims:
            if item_matches_claim(item, claim):
                hit = claim
                break
        if hit is None:
            missing.append({
                "id": item.get("id"),
                "displayed": item.get("displayed"),
                "location": item.get("location"),
            })
            continue
        accounted += 1
        outcome = hit.get("outcome")
        done = outcome in COMPLETED
        if done:
            completed += 1
        else:
            missing.append({
                "id": item.get("id"),
                "displayed": item.get("displayed"),
                "location": item.get("location"),
                "claim_id": hit.get("id"),
                "outcome": outcome,
            })
        mapping.append({
            "inventory_id": item.get("id"),
            "claim_id": hit.get("id"),
            "outcome": outcome,
        })
    n = len(items)
    return {
        "material": n,
        "accounted": accounted,
        "completed": completed,
        "missing": missing,
        "mapping": mapping,
        "extractor_fraction": (accounted / n) if n else 0.0,
        "engine_fraction": (completed / n) if n else 0.0,
        "inventory_complete": bool(inventory.get("complete")),
    }
