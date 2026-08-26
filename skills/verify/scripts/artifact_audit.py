#!/usr/bin/env python3
"""Independent mechanical invariants for public verify artifacts."""
from __future__ import annotations

import copy
import html as html_lib
import json
import pathlib
import re
import sys


SCRIPTS = pathlib.Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import render  # noqa: E402
from receipt_math import calculation_problem  # noqa: E402


FORBIDDEN_KEYS = frozenset({
    "found_by", "verification_mode", "report_quote", "report_quote_2",
    "evidence_json", "evidence_quote", "date_receipt", "population_alignment",
    "numeric_comparison", "source_consideration",
    "used_for_internal_arithmetic", "arithmetic_inventory_ids",
})
_ABS_PATH = re.compile(
    r"(?:/Users/|/home/|/var/folders/|/private/tmp/|/tmp/|[A-Z]:\\)[^\s\"'<]+",
    re.I,
)
_JSON_POINTER = re.compile(r"(?<![A-Za-z0-9:])(?:/[A-Za-z0-9_~.-]+)+")
_RAW_OFFICE_TOKEN = re.compile(r"\b(?:slide|shape)\d+\b", re.I)
_TENANT_IDENTIFIER = re.compile(
    r"\b(?:tenant|organization|org)[ _-]?id\b\s*[:=]\s*[\"']?[A-Za-z0-9_-]+",
    re.I,
)
_CREDENTIAL = re.compile(
    r"\b(?:api[ _-]?key|access[ _-]?token|refresh[ _-]?token|client[ _-]?secret|"
    r"password|credential)\b\s*[:=]\s*[^\s,;}]+",
    re.I,
)
_BEARER = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", re.I)
_VISIBLE_PROTOCOL_TOKENS = (
    "safe_to_share", "share_with_caveats", "fix_first", "unable_to_grade",
    "live_tool", "supplied_file", "not_checkable", "changed_since_report",
    "not_run",
)


def _walk(value, path: str = "$", *, keys: bool = False):
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if keys:
                yield child_path, str(key)
            yield from _walk(child, child_path, keys=keys)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk(child, f"{path}[{index}]", keys=keys)
    elif isinstance(value, str):
        yield path, value


def _forbidden_key_problems(artifact: dict) -> list[str]:
    problems = []
    for path, key in _walk(artifact, keys=True):
        if key == "report_quote" and re.fullmatch(
            r"\$\.actions\[[0-9]+\]\.report_quote", path
        ):
            continue
        if key in FORBIDDEN_KEYS:
            problems.append(f"public artifact contains forbidden field {path}")
    return problems


def _privacy_problems(artifact: dict, page: str) -> list[str]:
    problems = []
    visible_page = re.sub(r"<[^>]+>", " ", html_lib.unescape(page))
    values = list(_walk(artifact)) + [("$html", visible_page)]
    for path, text in values:
        if _ABS_PATH.search(text):
            problems.append(f"private path at {path}")
        if _JSON_POINTER.search(text):
            problems.append(f"JSON pointer at {path}")
        if _RAW_OFFICE_TOKEN.search(text):
            problems.append(f"raw Office coordinate at {path}")
        if _TENANT_IDENTIFIER.search(text):
            problems.append(f"tenant identifier at {path}")
        if _CREDENTIAL.search(text) or _BEARER.search(text):
            problems.append(f"credential at {path}")
    return problems


def ledger_counts(artifact: dict) -> dict[str, int]:
    material = [
        row for row in artifact.get("claims") or []
        if isinstance(row, dict)
        and row.get("classification") != "supporting_provenance"
        and row.get("importance") != "supporting"
    ]
    return {
        "material": len(material),
        "supporting": len(artifact.get("claims") or []) - len(material),
        **{
            verdict: sum(row.get("outcome") == verdict for row in material)
            for verdict in sorted(render.DISPOSITIONS)
        },
    }


def _ledger_problems(artifact: dict) -> list[str]:
    problems = []
    counts = ledger_counts(artifact)
    material_claims = [
        row for row in artifact.get("claims") or []
        if isinstance(row, dict)
        and row.get("classification") != "supporting_provenance"
        and row.get("importance") != "supporting"
    ]
    material_checks = [
        row for row in artifact.get("evidence_checks") or []
        if isinstance(row, dict) and row.get("importance") == "material"
    ]
    by_id = {str(row.get("id") or ""): row for row in material_checks}
    if len(by_id) != len(material_checks):
        problems.append("material check ids are duplicated")
    chosen = {str(row.get("check_id") or "") for row in material_claims}
    if chosen != set(by_id):
        problems.append("material claim and check ids do not reconcile")
    sources = {str(row.get("id") or "") for row in artifact.get("sources") or []}
    for claim in material_claims:
        check = by_id.get(str(claim.get("check_id") or ""))
        if check is None:
            continue
        if check.get("claim_id") != claim.get("id"):
            problems.append(f"claim {claim.get('id')} is linked to the wrong check")
        if check.get("verdict") != claim.get("outcome"):
            problems.append(f"claim {claim.get('id')} disposition does not match its check")
        receipt = check.get("public_receipt") or {}
        if ((receipt.get("report_operand") or {}).get("label")
                != claim.get("public_label")):
            problems.append(f"claim {claim.get('id')} public label does not match its receipt")
        if not render._publishable_receipt(
            receipt, verdict=check.get("verdict"), basis=check.get("basis"),
            source_ids=sources,
        ):
            problems.append(f"check {check.get('id')} public receipt is invalid")
        calculation = receipt.get("calculation")
        if calculation:
            math_problem = calculation_problem(
                calculation.get("expression"), calculation.get("result"),
                receipt.get("decisive_operands") or [],
            )
            if math_problem:
                problems.append(f"check {check.get('id')} {math_problem}")
    coverage = artifact.get("evidence_coverage") or {}
    expected = {
        "document_claims_total": counts["material"],
        "document_claims_reached": len(material_checks),
        "claim_outcomes_proposed": counts["material"],
        "material_claims_reviewed": counts["material"],
        "supporting_claims_reviewed": counts["supporting"],
        "confirmed": counts["confirmed"],
        "contradicted": counts["contradicted"],
        "not_checkable": counts["not_checkable"],
        "changed_since_report": counts["changed_since_report"],
        "validated_outcomes": len(material_checks),
        "evidence_files_supplied": len(artifact.get("sources") or []),
    }
    for key, value in expected.items():
        if coverage.get(key) != value:
            problems.append(f"coverage {key} does not match the material ledger")
    for basis in ("evidence", "report"):
        for verdict in render.DISPOSITIONS:
            key = f"{basis}_{verdict}"
            expected_value = sum(
                row.get("basis") == basis and row.get("verdict") == verdict
                for row in material_checks
            )
            if coverage.get(key) != expected_value:
                problems.append(f"coverage {key} does not match the material ledger")
    expected_score = (
        100.0 * counts["contradicted"] / counts["material"]
        if counts["material"] else None
    )
    score = artifact.get("score")
    if expected_score is None:
        if score is not None:
            problems.append("score exists without material claims")
    elif not isinstance(score, dict) or abs(float(score.get("value", -1)) - expected_score) > 1e-9:
        problems.append("score does not match contradicted material claims")
    expected_verdict = (
        "unable_to_grade" if not counts["material"]
        else "fix_first" if counts["contradicted"]
        else "share_with_caveats" if counts["not_checkable"] or counts["changed_since_report"]
        else "safe_to_share"
    )
    if artifact.get("verdict") != expected_verdict:
        problems.append("root verdict does not match the material ledger")
    if artifact.get("findings"):
        problems.append("machine findings entered public output")
    if artifact.get("diagnostics"):
        problems.append("machine diagnostics entered public output")
    expected_evidence_findings = [
        row for row in material_checks if row.get("verdict") == "contradicted"
    ]
    if artifact.get("evidence_findings") != expected_evidence_findings:
        problems.append("evidence findings do not match material contradictions")
    source_by_id = {
        str(row.get("id") or ""): row for row in artifact.get("sources") or []
        if isinstance(row, dict)
    }
    cited_ids = {
        str((row.get("public_receipt") or {}).get("source_id") or "")
        for row in material_checks if row.get("basis") == "evidence"
    } - {""}
    expected_cited = [
        source_by_id[source_id]["label"] for source_id in sorted(cited_ids)
        if source_id in source_by_id
    ]
    if coverage.get("evidence_files_cited") != expected_cited:
        problems.append("cited evidence sources do not match material receipts")
    expected_groups = [
        {"source_id": row["id"], "kind": row["kind"], "label": row["label"]}
        for row in artifact.get("sources") or []
    ]
    if coverage.get("provenance_groups") != expected_groups:
        problems.append("provenance groups do not match retained sources")
    if coverage.get("receipt_failures") != 0:
        problems.append("public artifact reports receipt failures")
    expected_independence = (
        "grouped_by_declared_provenance" if artifact.get("sources") else "not_assessed"
    )
    if coverage.get("source_independence") != expected_independence:
        problems.append("source independence token does not match retained sources")
    if artifact.get("source_result") is not None:
        problems.append("source_result entered output outside retained source metadata")
    actions = artifact.get("actions")
    if not isinstance(actions, list) or not actions:
        problems.append("accepted customer actions are missing")
    for name in ("decision_limits", "limitations"):
        if artifact.get(name):
            problems.append(f"{name} contains copy outside public receipts")
    if artifact.get("decision") is not None:
        problems.append("decision contains copy outside public receipts")
    if artifact.get("offer") != {"text": "", "accepted": None}:
        problems.append("offer contains copy outside public receipts")
    for name, row in (artifact.get("verification") or {}).items():
        if isinstance(row, dict) and row.get("detail") is not None:
            problems.append(f"verification.{name}.detail entered public output")
    expected_live_status = (
        "complete" if any(
            isinstance(row, dict) and row.get("kind") == "live_tool"
            for row in artifact.get("sources") or []
        ) else "not_run"
    )
    if (artifact.get("verification") or {}).get("live_source") != {
        "status": expected_live_status,
        "detail": None,
    }:
        problems.append(
            "verification.live_source does not match retained source metadata"
        )
    return problems


def _card_identity_problems(artifact: dict, page: str) -> list[str]:
    problems = []
    material_ids = {
        str(row.get("check_id") or "")
        for row in artifact.get("claims") or []
        if isinstance(row, dict)
        and row.get("classification") != "supporting_provenance"
        and row.get("importance") != "supporting"
    }
    expected = {
        str(row.get("id") or ""): str(row.get("verdict") or "")
        for row in artifact.get("evidence_checks") or []
        if isinstance(row, dict) and str(row.get("id") or "") in material_ids
    }
    tags = re.findall(r"<[^>]*\bdata-card-id=\"[^\"]*\"[^>]*>", page)
    found: dict[str, list[str]] = {}
    for tag in tags:
        ids = re.findall(r'\bdata-card-id="([^"]*)"', tag)
        dispositions = re.findall(r'\bdata-disposition="([^"]*)"', tag)
        if len(ids) != 1 or len(dispositions) != 1:
            problems.append("material card must have exactly one id and disposition")
            continue
        found.setdefault(html_lib.unescape(ids[0]), []).append(
            html_lib.unescape(dispositions[0]))
    if set(found) != set(expected):
        problems.append("rendered material card ids do not match accepted checks")
    for check_id, verdict in expected.items():
        values = found.get(check_id) or []
        if len(values) != 1:
            problems.append(f"material card {check_id} is missing or duplicated")
        elif values[0] != verdict:
            problems.append(f"material card {check_id} disposition does not match")
    return problems


def _visible_text(page: str) -> str:
    without_hidden_code = re.sub(
        r"<(?:style|script)[^>]*>.*?</(?:style|script)>",
        " ", page, flags=re.I | re.S,
    )
    return re.sub(r"\s+", " ", re.sub(
        r"<[^>]+>", " ", html_lib.unescape(without_hidden_code)))


def _customer_html_problems(artifact: dict, page: str) -> list[str]:
    """Check the locked customer hierarchy without inventing claim meaning."""
    problems: list[str] = []
    visible = _visible_text(page)
    for token in _VISIBLE_PROTOCOL_TOKENS:
        if token in visible:
            problems.append(f"visible customer text contains protocol token {token}")
    for token in ("Layer 1", "Layer 2", "L1", "L2"):
        if re.search(rf"(?<![A-Za-z0-9]){re.escape(token)}(?![A-Za-z0-9])", visible, re.I):
            problems.append(f"visible customer text contains internal token {token}")

    filename = str((artifact.get("source") or {}).get("path") or "")
    expected_title = f"<title>Verification: {html_lib.escape(filename)}</title>"
    if expected_title not in page:
        problems.append("customer title does not name the report filename")
    if "Summation <span>/ Verify</span>" not in page:
        problems.append("Summation / Verify header is missing")
    root_verdict = str(artifact.get("verdict") or "")
    try:
        root_label = render._root_headline(
            root_verdict, artifact.get("evidence_coverage"))
    except SystemExit:
        root_label = None
    if root_label is None or root_label not in visible:
        problems.append("plain-English root verdict is missing")
    root_chip = render.ROOT_CHIP_LABELS.get(root_verdict)
    if root_chip is None or not re.search(
        rf'<span class="chip [^"]+">{re.escape(root_chip)}</span>', page
    ):
        problems.append("verdict-specific customer chip is missing")
    if page.count('class="stats"') != 1:
        problems.append("customer scoreboard is missing or duplicated")
    if page.count('class="next"') != 1:
        problems.append("customer Next block is missing or duplicated")
    else:
        next_match = re.search(r'<div class="next">(.*?)</div>', page, re.S)
        for action in artifact.get("actions") or []:
            text = html_lib.escape(str(action.get("text") or ""))
            if next_match is None or text not in next_match.group(1):
                problems.append("customer Next block omits an accepted action")
                break
    if "Technical scope" not in visible:
        problems.append("technical scope is missing")
    if page.count('<details class="technical-detail"') != 1:
        problems.append("Technical detail disclosure is missing or duplicated")
    if 'class="sources"' in page:
        problems.append("page-level source list must not render")
    if re.search(r"https?://", page, re.I):
        problems.append("customer page contains a network asset or link")
    if re.search(r"\b(?:animation|transition)\s*:", page, re.I):
        problems.append("customer page contains motion CSS")
    if "@media(max-width:40rem)" not in page:
        problems.append("40rem customer breakpoint is missing")
    if "@media print" not in page or not re.search(
        r"\.material-card,.stats\{[^}]*break-inside:avoid", page
    ):
        problems.append("print card and scoreboard integrity rule is missing")

    claims_by_check = {
        str(row.get("check_id") or ""): row
        for row in artifact.get("claims") or []
        if isinstance(row, dict)
        and row.get("classification") != "supporting_provenance"
        and row.get("importance") != "supporting"
    }
    sources = {
        str(row.get("id") or ""): row
        for row in artifact.get("sources") or [] if isinstance(row, dict)
    }
    summary_ids = {
        str(value) for value in (
            (artifact.get("presentation") or {}).get("check_ids") or [])
    }
    details_at = page.find('<details class="technical-detail"')
    for check in artifact.get("evidence_checks") or []:
        if not isinstance(check, dict):
            continue
        check_id = str(check.get("id") or "")
        claim = claims_by_check.get(check_id)
        if claim is None:
            continue
        pattern = re.compile(
            rf'<article class="material-card"[^>]*\bdata-card-id="{re.escape(html_lib.escape(check_id))}"[^>]*>(.*?)</article>',
            re.S,
        )
        matches = list(pattern.finditer(page))
        if len(matches) != 1:
            continue
        match = matches[0]
        card = match.group(0)
        receipt = check.get("public_receipt") or {}
        report_operand = receipt.get("report_operand") or {}
        expected_text = [
            claim.get("quote"), report_operand.get("label"),
            report_operand.get("value"), report_operand.get("location"),
            receipt.get("explanation"),
        ]
        for operand in receipt.get("decisive_operands") or []:
            expected_text.extend([
                operand.get("label"), operand.get("value"), operand.get("location")])
        for value in expected_text:
            shown = html_lib.escape(render._display(value))
            if shown not in card:
                problems.append(f"material card {check_id} omits an accepted receipt field")
                break
        label = render.DISPOSITION_LABELS.get(str(check.get("verdict") or ""))
        if label is None or f'<span class="tag">{html_lib.escape(label)}</span>' not in card:
            problems.append(f"material card {check_id} has no exact visible disposition badge")
        expected_prominence = "prominent"
        if (
            check.get("verdict") == "not_checkable"
            or check.get("verdict") == "confirmed" and check_id not in summary_ids
        ):
            expected_prominence = "technical"
        if f'data-prominence="{expected_prominence}"' not in card:
            problems.append(f"material card {check_id} is in the wrong customer group")
        if expected_prominence == "technical":
            if details_at < 0 or match.start() < details_at:
                problems.append(f"technical receipt {check_id} is outside Technical detail")
            if check.get("verdict") == "not_checkable":
                compact = re.search(
                    r'<section class="outcome-section compact-outcomes" '
                    r'data-outcome-section="not_checkable">(.*?)</section>',
                    page, re.S,
                )
                expected_compact = (
                    html_lib.escape(str(claim.get("quote") or "")),
                    html_lib.escape(str(receipt.get("explanation") or "")),
                )
                if compact is None or any(
                    value not in compact.group(1) for value in expected_compact
                ):
                    problems.append(
                        f"not-checkable outcome {check_id} is missing from the compact list")
        else:
            section = re.search(
                rf'<section class="outcome-section" data-outcome-section="{re.escape(str(check.get("verdict") or ""))}">(.*?)</section>',
                page, re.S,
            )
            if section is None or f'data-card-id="{html_lib.escape(check_id)}"' not in section.group(1):
                problems.append(f"prominent card {check_id} is outside its outcome section")
        source_id = str(receipt.get("source_id") or "")
        source_rows = card.count('class="card-source"')
        if source_id:
            source = sources.get(source_id)
            if source_rows != 1 or source is None:
                problems.append(f"evidence card {check_id} has no single local source row")
            elif any(
                html_lib.escape(str(value)) not in card for value in (
                    source.get("label"), source.get("evidence_file"),
                    render.SOURCE_KIND_LABELS.get(str(source.get("kind") or ""), ""),
                )
            ):
                problems.append(f"evidence card {check_id} source row is incomplete")
            elif source.get("kind") == "live_tool" and html_lib.escape(str(
                (source.get("retrieval") or {}).get("retrieved_at") or ""
            )) not in card:
                problems.append(f"live evidence card {check_id} omits retrieval time")
        elif source_rows:
            problems.append(f"report-basis card {check_id} has an undeclared source row")
    return list(dict.fromkeys(problems))


def audit_public_artifact(artifact: dict, page: str, *,
                          render_context: dict | None = None) -> list[str]:
    problems = []
    try:
        render.validate_artifact(artifact)
    except Exception as exc:  # jsonschema errors are evidence, not control flow here
        problems.append(f"schema validation failed: {exc}")
    except SystemExit as exc:
        problems.append(f"schema validation failed: {exc}")
    if artifact.get("schema_version") != render.SCHEMA_VERSION:
        problems.append("artifact schema version is not public-receipt-v1")
    problems.extend(_forbidden_key_problems(artifact))
    problems.extend(_ledger_problems(artifact))
    problems.extend(_privacy_problems(artifact, page))
    problems.extend(_card_identity_problems(artifact, page))
    problems.extend(_customer_html_problems(artifact, page))
    try:
        expected_page = render.html_of(
            artifact, render_context=render_context)
    except Exception as exc:
        problems.append(f"canonical HTML could not be serialized: {exc}")
    except SystemExit as exc:
        problems.append(f"canonical HTML could not be serialized: {exc}")
    else:
        if page != expected_page:
            problems.append("HTML is not the exact generic serialization of the artifact")
    return list(dict.fromkeys(problems))


def _mutate(artifact: dict) -> dict:
    return copy.deepcopy(artifact)


def mutate_remove_operands(artifact: dict) -> dict:
    out = _mutate(artifact)
    out["evidence_checks"][0]["public_receipt"]["decisive_operands"] = []
    return out


def mutate_swap_operands(artifact: dict) -> dict:
    out = _mutate(artifact)
    rows = out["evidence_checks"][0]["public_receipt"]["decisive_operands"]
    if len(rows) > 1:
        rows[0], rows[1] = rows[1], rows[0]
    else:
        rows[0]["value"] = "mutated value"
    return out


def mutate_vague_operand_label(artifact: dict) -> dict:
    out = _mutate(artifact)
    out["evidence_checks"][0]["public_receipt"]["decisive_operands"][0]["label"] = "row 2"
    return out


def mutate_remove_explanation(artifact: dict) -> dict:
    out = _mutate(artifact)
    out["evidence_checks"][0]["public_receipt"]["explanation"] = ""
    return out


def mutate_remove_source_link(artifact: dict) -> dict:
    out = _mutate(artifact)
    out["evidence_checks"][0]["public_receipt"].pop("source_id", None)
    return out


def mutate_confirmed_calculation_to_contradiction(artifact: dict) -> dict:
    out = _mutate(artifact)
    receipt = out["evidence_checks"][0]["public_receipt"]
    receipt["calculation"] = {"expression": "12 + 1", "result": 99}
    return out


def mutate_remove_report_operand(artifact: dict) -> dict:
    out = _mutate(artifact)
    out["evidence_checks"][0]["public_receipt"].pop("report_operand", None)
    return out


def mutate_duplicate_findings(artifact: dict) -> dict:
    out = _mutate(artifact)
    out["findings"] = [{
        "check_id": "machine", "family": "internal", "tier": "D",
        "severity": "high", "statement": "machine statement",
        "location": None, "claim_ids": [],
    }]
    return out


def mutate_alter_evidence_findings(artifact: dict) -> dict:
    out = _mutate(artifact)
    out["evidence_findings"] = []
    return out


def mutate_alter_score(artifact: dict) -> dict:
    out = _mutate(artifact)
    out["score"]["value"] += 1
    return out


def mutate_alter_counts(artifact: dict) -> dict:
    out = _mutate(artifact)
    out["evidence_coverage"]["confirmed"] += 1
    return out


def mutate_falsify_evidence_counts(artifact: dict) -> dict:
    out = _mutate(artifact)
    out["evidence_coverage"]["evidence_confirmed"] += 1
    return out


def mutate_demote_evidence(artifact: dict) -> dict:
    out = _mutate(artifact)
    out["evidence_checks"][0]["basis"] = "report"
    return out


def mutate_inject_paths(artifact: dict) -> dict:
    out = _mutate(artifact)
    out["evidence_checks"][0]["public_receipt"]["explanation"] += " /private/tmp/raw.json"
    return out


def mutate_inject_json_pointer(artifact: dict) -> dict:
    out = _mutate(artifact)
    out["evidence_checks"][0]["public_receipt"]["report_operand"]["location"] = "/metrics/value"
    return out


def mutate_inject_slide_token(artifact: dict) -> dict:
    out = _mutate(artifact)
    out["evidence_checks"][0]["public_receipt"]["report_operand"]["location"] = "slide2/shape3"
    return out


def mutate_inject_tenant_identifier(artifact: dict) -> dict:
    out = _mutate(artifact)
    out["sources"][0]["label"] = "tenant_id=customer-123"
    return out


def mutate_inject_credential(artifact: dict) -> dict:
    out = _mutate(artifact)
    out["sources"][0]["label"] = "api_key=secret"
    return out


def mutate_static_evidence_to_live(artifact: dict) -> dict:
    out = _mutate(artifact)
    out["sources"][0]["kind"] = "live_tool"
    return out


def mutate_inject_verification_detail(artifact: dict) -> dict:
    out = _mutate(artifact)
    out["verification"]["document"]["detail"] = "Machine-authored detail."
    return out


def mutate_static_source_claims_live_complete(artifact: dict) -> dict:
    out = _mutate(artifact)
    out["verification"]["live_source"] = {"status": "complete", "detail": None}
    return out


def main() -> int:
    if len(sys.argv) not in {3, 4}:
        print(
            "usage: artifact_audit.py grade-artifact.json grade-artifact.html "
            "[accepted-receipts.json]",
            file=sys.stderr,
        )
        return 2
    artifact = json.loads(pathlib.Path(sys.argv[1]).read_text())
    page = pathlib.Path(sys.argv[2]).read_text()
    context = (
        json.loads(pathlib.Path(sys.argv[3]).read_text())
        if len(sys.argv) == 4 else None
    )
    problems = audit_public_artifact(
        artifact, page, render_context=context)
    for problem in problems:
        print(problem)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
