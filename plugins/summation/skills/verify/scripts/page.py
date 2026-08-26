#!/usr/bin/env python3
"""Write the customer HTML page from host-authored grade.json.

This is an output utility. It does not classify claims, choose evidence,
or invent verdicts. It copies host fields, recomputes a declared
calculation when present, strips private paths, and serializes HTML.

Usage:
    python3 page.py --findings run/findings.json --grade run/grade.json \\
      --out-dir run/artifact [--evidence-dir run/evidence]
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import operator
import pathlib
import re
import sys
from datetime import datetime, timezone

SCRIPTS = pathlib.Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import render  # noqa: E402

_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}
_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]*$")


def _number(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_number(node.operand))
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_number(node.left), _number(node.right))
    raise ValueError("calculation expression is not restricted arithmetic")


def recompute(expression: str):
    text = str(expression or "").replace(",", "").replace("%", "").strip()
    if not text:
        raise ValueError("calculation expression is empty")
    tree = ast.parse(text, mode="eval")
    return _number(tree.body)


def _close(value) -> str:
    text = str(value or "").strip()
    if text and text[-1] not in ".!?":
        return text + "."
    return text


def _sources(evidence_dir: pathlib.Path | None) -> list[dict]:
    if evidence_dir is None or not evidence_dir.is_dir():
        return []
    rows = []
    for path in sorted(evidence_dir.iterdir()):
        if not path.is_file() or path.name.startswith("."):
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        rows.append({
            "id": f"SRC-{path.stem}",
            "kind": "supplied_file",
            "label": path.name,
            "evidence_file": path.name,
            "result_sha256": digest,
        })
    return rows


def _card_to_check(card: dict, source_ids: set[str]) -> dict:
    card_id = str(card.get("id") or "").strip()
    if not _ID_RE.fullmatch(card_id):
        raise SystemExit(f"page: card id {card_id!r} is invalid")
    verdict = str(card.get("verdict") or "").strip()
    label = str(card.get("label") or "").strip()
    quote = str(card.get("quote") or "").strip()
    location = str(card.get("location") or "Report").strip()
    explanation = _close(card.get("explanation"))
    source_id = str(card.get("source_id") or "").strip()
    basis = "evidence" if source_id else "report"
    if source_id and source_id not in source_ids:
        raise SystemExit(f"page: card {card_id} source_id is not a retained file")
    operands = list(card.get("operands") or [])
    if verdict == "not_checkable":
        operands = []
        source_id = ""
        basis = "report"
    receipt = {
        "report_operand": {
            "label": label,
            "value": card.get("report_value", quote),
            "location": location,
        },
        "decisive_operands": operands,
        "explanation": explanation,
    }
    calculation = card.get("calculation")
    if calculation is not None:
        if not isinstance(calculation, dict):
            raise SystemExit(f"page: card {card_id} calculation is not an object")
        expression = str(calculation.get("expression") or "")
        declared = calculation.get("result")
        actual = recompute(expression)
        declared_text = str(declared).replace(",", "").replace("$", "").replace("%", "")
        try:
            declared_num = float(declared_text)
        except (TypeError, ValueError) as exc:
            raise SystemExit(f"page: card {card_id} calculation result is not numeric") from exc
        if abs(actual - declared_num) > 1e-6:
            raise SystemExit(
                f"page: card {card_id} calculation {actual} does not match {declared}"
            )
        receipt["calculation"] = {
            "expression": expression,
            "result": declared,
        }
    if source_id:
        receipt["source_id"] = source_id
    check_type = "arithmetic" if calculation is not None else "semantic"
    return {
        "id": card_id,
        "claim_id": card_id,
        "type": check_type,
        "basis": basis,
        "verdict": verdict,
        "importance": "material",
        "severity": "high" if verdict == "contradicted" else None,
        "public_receipt": receipt,
    }


def _claim_from_card(card: dict) -> dict:
    card_id = str(card.get("id") or "").strip()
    return {
        "id": card_id,
        "quote": str(card.get("quote") or ""),
        "public_label": str(card.get("label") or ""),
        "importance": "material",
        "classification": "material_claim",
        "outcome": str(card.get("verdict") or ""),
        "check_id": card_id,
        "inventory_ids": list(card.get("inventory_ids") or []),
    }


def grade_to_artifact(findings: dict, grade: dict, *, sources: list[dict],
                      run_id: str, generated_at: str) -> tuple[dict, str]:
    cards = grade.get("cards")
    if not isinstance(cards, list) or not cards:
        raise SystemExit("page: grade.json needs a non-empty cards array")
    source_ids = {str(row["id"]) for row in sources}
    checks = [_card_to_check(card, source_ids) for card in cards]
    claims = [_claim_from_card(card) for card in cards]
    next_rows = grade.get("next") or []
    if not isinstance(next_rows, list) or not next_rows:
        raise SystemExit("page: grade.json needs a next array with one customer action")
    actions = []
    for index, row in enumerate(next_rows, start=1):
        if not isinstance(row, dict):
            raise SystemExit("page: next item is not an object")
        cited = list(row.get("card_ids") or ([checks[0]["id"]] if checks else []))
        actions.append({
            "id": f"A{index}",
            "kind": str(row.get("kind") or "review_before_share"),
            "text": _close(row.get("text")),
            "report_quote": str(row.get("quote") or cards[0].get("quote") or ""),
            "check_ids": cited,
        })
    confirmed_ids = [row["id"] for row in checks if row["verdict"] == "confirmed"]
    summary_ids = list(grade.get("confirmations") or confirmed_ids[:1] or [checks[0]["id"]])
    guidance = {
        "summary": _close(grade.get("summary")),
        "check_ids": summary_ids,
        "actions": actions,
        "limits": [],
    }
    raw = json.loads(json.dumps(findings))
    source = raw.setdefault("source", {})
    if not isinstance(source, dict):
        source = {}
        raw["source"] = source
    period = str(grade.get("report_period") or "").strip()
    report_date = str(grade.get("report_date") or "").strip()
    if period:
        source["period_label"] = period
    if report_date:
        source["report_date"] = report_date
    raw["claims"] = claims
    raw["sources"] = sources
    raw["verification"] = {
        "document": {"status": "complete", "detail": None},
        "semantic": {"status": "complete", "detail": None},
        "live_source": {"status": "not_run", "detail": None},
    }
    artifact = render.artifact_from_findings(
        raw, run_id=run_id, generated_at=generated_at,
        layer2=checks, guidance=guidance,
    )
    page = render.html_of(artifact, render_context=None)
    return artifact, page


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--findings", required=True, type=pathlib.Path)
    ap.add_argument("--grade", required=True, type=pathlib.Path)
    ap.add_argument("--out-dir", required=True, type=pathlib.Path)
    ap.add_argument("--evidence-dir", type=pathlib.Path, default=None)
    args = ap.parse_args()
    for path in (args.findings, args.grade):
        if not path.is_file():
            print(f"page: missing {path}", file=sys.stderr)
            return 2
    try:
        findings = json.loads(args.findings.read_text())
        grade = json.loads(args.grade.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"page: invalid input: {exc}", file=sys.stderr)
        return 2
    if not isinstance(findings, dict) or not isinstance(grade, dict):
        print("page: findings and grade must be objects", file=sys.stderr)
        return 2
    digest = str((findings.get("source") or {}).get("sha256") or "")
    run_id = f"sf-{digest[:6]}" if re.fullmatch(r"[0-9a-f]{64}", digest) else "sf-grade"
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        artifact, page = grade_to_artifact(
            findings, grade, sources=_sources(args.evidence_dir),
            run_id=run_id, generated_at=generated_at,
        )
    except (SystemExit, ValueError) as exc:
        print(f"page: {exc}", file=sys.stderr)
        return 2
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "grade-artifact.json").write_text(
        json.dumps(artifact, indent=2) + "\n")
    (args.out_dir / "grade-artifact.html").write_text(page)
    print(args.out_dir / "grade-artifact.json")
    print(args.out_dir / "grade-artifact.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
