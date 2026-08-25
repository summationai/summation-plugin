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
    "evidence_json", "evidence_quote", "date_receipt",
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
    for name in ("actions", "decision_limits", "limitations"):
        if artifact.get(name):
            problems.append(f"{name} contains copy outside public receipts")
    if artifact.get("decision") is not None:
        problems.append("decision contains copy outside public receipts")
    if artifact.get("offer") != {"text": "", "accepted": None}:
        problems.append("offer contains copy outside public receipts")
    for name, row in (artifact.get("verification") or {}).items():
        if isinstance(row, dict) and row.get("detail") is not None:
            problems.append(f"verification.{name}.detail entered public output")
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


def audit_public_artifact(artifact: dict, page: str) -> list[str]:
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
    try:
        expected_page = render.html_of(artifact)
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


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: artifact_audit.py grade-artifact.json grade-artifact.html", file=sys.stderr)
        return 2
    artifact = json.loads(pathlib.Path(sys.argv[1]).read_text())
    page = pathlib.Path(sys.argv[2]).read_text()
    problems = audit_public_artifact(artifact, page)
    for problem in problems:
        print(problem)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
