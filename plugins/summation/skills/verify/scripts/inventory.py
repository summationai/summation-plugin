"""Machine claim inventory for the verify skill.

HTML: table cells via html_arith plus alg numparse over visible text.
Markdown, PDF, xlsx, and pptx use the same item shape and complete=True
when the reader obtained visible text.
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
TABLE_LOC_RE = re.compile(r"^table\d+$", re.I)
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


def _glued_to_identifier(text: str, tok) -> bool:
    start = int(getattr(tok, "start", 0) or 0)
    end = int(getattr(tok, "end", 0) or 0)
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    prev = text[start - 1] if start else ""
    nxt = text[end] if end < len(text) else ""
    if prev.isalnum() or prev == "_":
        return True
    if nxt.isalnum() or nxt == "_":
        return True
    return False


def _structural_numbering(text: str, tok) -> bool:
    """True for list/section markers such as '1. Title' or '(2)'."""
    shown = str(tok.value_displayed or "").strip()
    if re.fullmatch(r"\(?\d{1,3}\)", shown):
        return True
    start = int(getattr(tok, "start", 0) or 0)
    end = int(getattr(tok, "end", 0) or 0)
    nxt = text[end] if end < len(text) else ""
    unit = getattr(tok, "unit", None)
    if nxt != "." or unit not in {"unknown", None, ""}:
        return False
    if getattr(tok, "currency_code", None):
        return False
    if not shown.isdigit() or len(shown) > 3:
        return False
    prev = text[start - 1] if start else ""
    after = text[end + 1: end + 2]
    if prev and not prev.isspace():
        return False
    return bool(after.isupper())


def _material_token(tok, text: str = "") -> bool:
    """Keep load-bearing numbers. Drop dates, timestamps, and structural numbering."""
    shown = str(tok.value_displayed or "").strip()
    if not shown:
        return False
    if DATE_RE.search(shown):
        return False
    if text and _glued_to_identifier(text, tok):
        return False
    if text and _structural_numbering(text, tok):
        return False
    return True


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
        if _material_token(tok, visible):
            add("prose_number", shown, f"visible-text@{tok.start}", "material")
            captured.add(shown)
    return items


def _bag_add(items: list, seen: set, kind: str, displayed: str, location: str,
             importance: str = "material") -> None:
    shown = re.sub(r"\s+", " ", displayed).strip()
    if not shown:
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


def _md_items(path: pathlib.Path) -> list[dict]:
    items: list[dict] = []
    seen: set[tuple] = set()
    for index, raw in enumerate(path.read_text(errors="replace").splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            continue
        if line.lower().startswith("source snapshot"):
            continue
        shown = re.sub(r"^[-*]\s+", "", line).strip()
        if not shown:
            continue
        _bag_add(items, seen, "md_line", shown, f"line{index}", "material")
    return items


def visible_markdown(path: pathlib.Path) -> str:
    return path.read_text(errors="replace")


def _pdf_items(path: pathlib.Path) -> tuple[list[dict], str, str | None]:
    try:
        from pypdf import PdfReader
    except ImportError:
        return [], "", "pypdf is not installed"
    try:
        reader = PdfReader(str(path))
    except Exception as exc:  # noqa: BLE001 — fail closed on unreadable PDF
        return [], "", f"unreadable PDF: {exc}"
    items: list[dict] = []
    seen: set[tuple] = set()
    pages: list[str] = []
    skip = {"rank", "segment", "revenue ($k)", "revenue"}
    for page_i, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        pages.append(text)
        for line_i, raw in enumerate(text.splitlines(), start=1):
            shown = re.sub(r"\s+", " ", raw).strip()
            if not shown or shown.lower() in skip:
                continue
            if re.fullmatch(r"\d{1,2}", shown):
                continue
            importance = "supporting" if shown.lower().startswith("source snapshot") else "material"
            kind = "pdf_source" if importance == "supporting" else "pdf_line"
            _bag_add(items, seen, kind, shown, f"page{page_i}/line{line_i}", importance)
    visible = "\n".join(pages).strip()
    if not visible:
        return [], "", "no extractable PDF text"
    return items, visible, None


def _xlsx_display(cell) -> str | None:
    value = cell.value
    if value is None or value == "":
        return None
    fmt = str(cell.number_format or "General")
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, str):
        shown = re.sub(r"\s+", " ", value).strip()
        return shown or None
    if isinstance(value, (int, float)):
        if "%" in fmt:
            match = re.search(r"0\.(0+)%", fmt)
            places = len(match.group(1)) if match else 0
            return f"{float(value) * 100:.{places}f}%"
        if "0.00" in fmt:
            return f"{float(value):,.2f}"
        if "#,##0" in fmt:
            return f"{float(value):,.0f}"
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value)
    return str(value)


def _xlsx_items(path: pathlib.Path) -> tuple[list[dict], str, str | None]:
    try:
        from openpyxl import load_workbook
    except ImportError:
        return [], "", "openpyxl is not installed"
    try:
        book = load_workbook(path, data_only=False)
    except Exception as exc:  # noqa: BLE001
        return [], "", f"unreadable xlsx: {exc}"
    items: list[dict] = []
    seen: set[tuple] = set()
    lines: list[str] = []
    for sheet in book.worksheets:
        for row in sheet.iter_rows():
            for cell in row:
                shown = _xlsx_display(cell)
                if shown is None:
                    continue
                lines.append(f"{sheet.title}!{cell.coordinate} {shown}")
                numeric = isinstance(cell.value, (int, float)) and not isinstance(
                    cell.value, bool)
                note = shown.lower().startswith("note:")
                importance = "material" if numeric or note else "supporting"
                kind = "xlsx_note" if note else "xlsx_cell"
                _bag_add(
                    items, seen, kind, shown,
                    f"{sheet.title}/{cell.coordinate}", importance)
    visible = "\n".join(lines)
    if not visible:
        return [], "", "no visible xlsx cells"
    return items, visible, None


def _pptx_items(path: pathlib.Path) -> tuple[list[dict], str, str | None]:
    try:
        from pptx import Presentation
    except ImportError:
        return [], "", "python-pptx is not installed"
    try:
        deck = Presentation(str(path))
    except Exception as exc:  # noqa: BLE001
        return [], "", f"unreadable pptx: {exc}"
    items: list[dict] = []
    seen: set[tuple] = set()
    lines: list[str] = []
    for slide_i, slide in enumerate(deck.slides, start=1):
        for shape_i, shape in enumerate(slide.shapes, start=1):
            if not getattr(shape, "has_text_frame", False):
                continue
            text = re.sub(r"\s+", " ", shape.text_frame.text or "").strip()
            if not text:
                continue
            lines.append(text)
            _bag_add(
                items, seen, "pptx_shape", text,
                f"slide{slide_i}/shape{shape_i}")
    visible = "\n".join(lines)
    if not visible:
        return [], "", "no visible pptx text"
    return items, visible, None


def visible_text_for(path: pathlib.Path) -> tuple[str, str | None]:
    """Visible report text plus an error when extraction failed."""
    suffix = path.suffix.lower()
    reader = READERS.get(suffix, suffix.lstrip(".") or "unknown")
    if reader == "html":
        return _visible_text(path.read_text(errors="replace")), None
    if reader in {"md", "txt"}:
        return visible_markdown(path), None
    if reader == "pdf":
        _items, visible, err = _pdf_items(path)
        return visible, err
    if reader == "xlsx":
        _items, visible, err = _xlsx_items(path)
        return visible, err
    if reader == "pptx":
        _items, visible, err = _pptx_items(path)
        return visible, err
    return "", f"no visible-text reader for {reader}"


def inventory_for(path: pathlib.Path) -> dict:
    """Same shape for every supported format."""
    suffix = path.suffix.lower()
    reader = READERS.get(suffix, suffix.lstrip(".") or "unknown")
    if reader == "html":
        return {
            "reader": "html",
            "complete": True,
            "items": _html_items(path),
            "reason": None,
        }
    if reader in {"md", "txt"}:
        items = _md_items(path)
        return {
            "reader": reader,
            "complete": True,
            "items": items,
            "reason": None,
        }
    if reader == "pdf":
        items, _visible, err = _pdf_items(path)
        return {
            "reader": "pdf",
            "complete": err is None,
            "items": items if err is None else [],
            "reason": err,
        }
    if reader == "xlsx":
        items, _visible, err = _xlsx_items(path)
        return {
            "reader": "xlsx",
            "complete": err is None,
            "items": items if err is None else [],
            "reason": err,
        }
    if reader == "pptx":
        items, _visible, err = _pptx_items(path)
        return {
            "reader": "pptx",
            "complete": err is None,
            "items": items if err is None else [],
            "reason": err,
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


def claim_inventory_ids(claim: dict) -> list[str]:
    raw = claim.get("inventory_ids")
    if isinstance(raw, str):
        return [raw.strip()] if raw.strip() else []
    if isinstance(raw, list):
        out = []
        seen = set()
        for value in raw:
            item = str(value or "").strip()
            if item and item not in seen:
                seen.add(item)
                out.append(item)
        return out
    return []


def _row_label(item: dict) -> str:
    loc = str(item.get("location") or "")
    parts = loc.split("/")
    if len(parts) >= 2 and TABLE_LOC_RE.fullmatch(parts[0] or ""):
        return parts[1]
    return ""


def _quote_names_location(claim: dict, item: dict) -> bool:
    quote = str(claim.get("quote") or "")
    label = _row_label(item)
    if label and label in quote:
        return True
    loc = str(item.get("location") or "")
    return bool(loc) and loc in quote


def cover(inventory: dict, claims: list) -> dict:
    """Map material inventory items to claims by explicit inventory_ids.

    Each material item is consumed at most once. A claim that lists two items
    with the same displayed value covers both only when the quote names both
    locations.
    """
    items = [
        item for item in (inventory.get("items") or [])
        if item.get("importance") == "material"
    ]
    by_id = {str(item.get("id") or ""): item for item in items if item.get("id")}
    consumed: dict[str, dict] = {}
    missing = []
    accounted = 0
    completed = 0
    mapping = []
    for claim in claims:
        seen_shown: list[str] = []
        for iid in claim_inventory_ids(claim):
            if iid in consumed:
                continue
            item = by_id.get(iid)
            if item is None:
                continue
            if not item_matches_claim(item, claim):
                continue
            shown = str(item.get("displayed") or "")
            if shown in seen_shown and not _quote_names_location(claim, item):
                continue
            consumed[iid] = claim
            seen_shown.append(shown)
            accounted += 1
            outcome = claim.get("outcome")
            done = outcome in COMPLETED
            if done:
                completed += 1
            else:
                missing.append({
                    "id": item.get("id"),
                    "displayed": item.get("displayed"),
                    "location": item.get("location"),
                    "claim_id": claim.get("id"),
                    "outcome": outcome,
                })
            mapping.append({
                "inventory_id": item.get("id"),
                "claim_id": claim.get("id"),
                "outcome": outcome,
            })
    for item in items:
        iid = str(item.get("id") or "")
        if iid and iid not in consumed:
            missing.append({
                "id": item.get("id"),
                "displayed": item.get("displayed"),
                "location": item.get("location"),
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
