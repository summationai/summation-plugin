#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = [
#   "pypdf>=4.0",
#   "openpyxl>=3.1",
#   "python-pptx>=1.0",
# ]
# ///
"""Write visible report text and findings.json inventory. No OfficeCLI. No Poppler.

Usage:
    extract.py --report FILE --visible report-visible.txt --out findings.json
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

SCRIPTS = pathlib.Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from html_arith import findings_doc, footing_findings, _Tables  # noqa: E402
from inventory import inventory_for, visible_text_for  # noqa: E402
from internal import check_inventory  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--report", required=True, type=pathlib.Path)
    ap.add_argument("--visible", required=True, type=pathlib.Path)
    ap.add_argument("--out", required=True, type=pathlib.Path)
    args = ap.parse_args()
    if not args.report.is_file():
        print(f"extract: missing report {args.report}", file=sys.stderr)
        return 2

    visible, err = visible_text_for(args.report)
    html = args.report.suffix.lower() in {".html", ".htm"}
    findings: list[dict] = []
    arithmetic_checks = 0
    arithmetic_uses: list[dict] = []
    if html:
        parser = _Tables()
        parser.feed(args.report.read_text(errors="replace"))
        parser.close()
        findings, arithmetic_checks, arithmetic_uses = footing_findings(parser.tables)
        if not visible:
            visible, err = visible_text_for(args.report)

    if err and not visible:
        print(f"extract: {err}", file=sys.stderr)
        doc = findings_doc(
            args.report, [], html=False, arithmetic_checks=0,
            intake_error=err)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.visible.parent.mkdir(parents=True, exist_ok=True)
        args.visible.write_text("")
        args.out.write_text(json.dumps(doc, indent=2) + "\n")
        return 2

    args.visible.parent.mkdir(parents=True, exist_ok=True)
    args.visible.write_text(visible if visible.endswith("\n") else visible + "\n")
    doc = findings_doc(
        args.report, findings, html=html, arithmetic_checks=arithmetic_checks,
        arithmetic_uses=arithmetic_uses)
    inv = doc.get("inventory") or inventory_for(args.report)
    doc["internal_outcomes"] = check_inventory(inv, visible)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(doc, indent=2) + "\n")
    print(f"extract: {len(doc.get('inventory', {}).get('items') or [])} inventory item(s) → {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
