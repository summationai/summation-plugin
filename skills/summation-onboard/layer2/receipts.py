#!/usr/bin/env python3
"""Receipt validation for Layer 2 findings.

The agent proposes findings; this harness verifies the receipts. A finding
survives only when its report quote appears verbatim in the report and its
evidence quote appears verbatim in the named evidence file. Comparison is
whitespace-normalized and case-preserving; HTML reports are tag-stripped first.

Usage:
    receipts.py --fixture <dir-with-report-and-layer2-findings.json> [--answers answers.json]

Exit codes: 0 all findings validated (and all planted defects caught when
--answers is given); 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

REPORT_SUFFIXES = (".html", ".md")


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def strip_tags(html: str) -> str:
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    return re.sub(r"<[^>]+>", " ", html)


def load_text(path: pathlib.Path) -> str:
    raw = path.read_text()
    if path.suffix == ".html":
        raw = strip_tags(raw)
    return normalize(raw)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixture", required=True)
    ap.add_argument("--answers")
    ap.add_argument("--out")
    args = ap.parse_args()

    fixture = pathlib.Path(args.fixture)
    findings_path = fixture / "layer2-findings.json"
    if not findings_path.exists():
        print(f"receipts: no layer2-findings.json in {fixture}")
        return 1
    doc = json.loads(findings_path.read_text())

    reports = [p for p in fixture.iterdir() if p.suffix in REPORT_SUFFIXES]
    if len(reports) != 1:
        print(f"receipts: expected exactly one report in {fixture}, found {len(reports)}")
        return 1
    report_text = load_text(reports[0])

    validated, discarded = [], []
    for f in doc.get("findings", []):
        problems = []
        rq = normalize(f.get("report_quote", ""))
        if not rq or rq not in report_text:
            problems.append("report_quote not found verbatim in the report")
        if f.get("type") == "internal":
            rq2 = normalize(f.get("report_quote_2", ""))
            if not rq2 or rq2 not in report_text:
                problems.append("report_quote_2 not found verbatim in the report")
        else:
            ev_name = f.get("evidence_file", "")
            ev_path = fixture / ev_name
            if not ev_path.exists():
                problems.append(f"evidence_file {ev_name!r} does not exist")
            else:
                eq = normalize(f.get("evidence_quote", ""))
                if not eq or eq not in load_text(ev_path):
                    problems.append("evidence_quote not found verbatim in the evidence file")
        if problems:
            discarded.append({"id": f.get("id"), "problems": problems})
        else:
            validated.append(f)

    print(f"receipts: {len(validated)} validated, {len(discarded)} discarded")
    for d in discarded:
        print(f"  DISCARDED {d['id']}: {'; '.join(d['problems'])}")

    caught, missed = [], []
    if args.answers:
        answers = json.loads(pathlib.Path(args.answers).read_text())
        planted = [
            d for d in answers.get("planted_defects", [])
            if d.get("family", "").startswith("content_")
        ]
        for defect in planted:
            shown = normalize(defect["shown"]).casefold()
            hit = any(
                shown in normalize(v["report_quote"]).casefold() for v in validated
            )
            (caught if hit else missed).append(defect["id"])
        print(f"receipts: planted defects caught {caught}, missed {missed}")

    if args.out:
        pathlib.Path(args.out).write_text(json.dumps({
            "validated": validated,
            "discarded": discarded,
            "planted_caught": caught,
            "planted_missed": missed,
        }, indent=1))

    return 0 if not discarded and not missed else 1


if __name__ == "__main__":
    sys.exit(main())
