#!/usr/bin/env python3
"""One report package in, one receipted grade artifact out.

HTML receives the deterministic Summation claim-ledger checks. Other readable
formats use a deterministic text adapter (OfficeCLI or Poppler) and a fresh
agentic scan; the artifact states that limitation instead of pretending the
same checks ran. Optional live-source checks always run read-only and fail
closed when explicitly requested.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
KIT = HERE.parent
EXCLUDE = ("layer2-findings", "grade-", "source-findings")
EVIDENCE_SUFFIXES = frozenset({".json", ".txt", ".sql", ".csv", ".yaml", ".yml"})
REPORT_ONLY_TYPES = frozenset({"internal", "logic", "arithmetic", "units", "selection"})
CUSTOMER_L1_CHECKS = frozenset({
    "ari_total_footing", "ari_total_footing_precision",
    "uni_percent_vs_points", "per_period_misaligned",
    "sel_order_violated", "gnd_ungrounded_claim",
})
L2_PLAN_TIMEOUT_SECONDS = 300
L2_BATCH_TIMEOUT_SECONDS = 300
L2_DECISION_TIMEOUT_SECONDS = 120
L2_TARGET_CHECKS_PER_BATCH = 16
L2_MAX_PARALLEL_BATCHES = 6
L2_SECTION_PLAN_TIMEOUT_SECONDS = 210
L2_SECTION_TARGET_CHARS = 2500
L2_MAX_PARALLEL_PLAN_SECTIONS = 6

CLAIM_TYPES = ["semantic", "staleness", "internal", "logic",
               "arithmetic", "units", "selection"]

CLAIM_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "type": {"enum": CLAIM_TYPES},
        "importance": {"enum": ["material", "supporting"]},
        "report_quote": {"type": "string"},
        "evidence_files": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["id", "type", "importance", "report_quote", "evidence_files"],
    "additionalProperties": False,
}

CHECK_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        **CLAIM_ITEM_SCHEMA["properties"],
        "basis": {"enum": ["evidence", "report"]},
        "verdict": {"enum": ["confirmed", "contradicted", "not_checkable"]},
        "severity": {"enum": ["high", "medium", "low"]},
        "evidence_file": {"type": "string"},
        "evidence_quote": {"type": "string"},
        "evidence_json": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"pointer": {"type": "string"}, "value": {}},
                "required": ["pointer", "value"],
                "additionalProperties": False,
            },
        },
        "report_quote_2": {"type": "string"},
        "explanation": {"type": "string"},
    },
    "required": ["id", "type", "importance", "report_quote", "basis",
                 "verdict", "explanation"],
    "additionalProperties": False,
}

GUIDANCE_ITEM_SCHEMA = {
    "type": "object",
    "properties": {"id": {"type": "string"}, "text": {"type": "string"},
                   "report_quote": {"type": "string"}},
    "required": ["id", "text", "report_quote"],
    "additionalProperties": False,
}

DECISION_SCHEMA = {
    "type": ["object", "null"],
    "properties": {
        "outcome": {"enum": ["supported", "mixed", "not_supported", "not_checkable"]},
        "text": {"type": "string"},
        "report_quote": {"type": "string"},
        "explanation": {"type": "string"},
        "supporting_check_ids": {"type": "array", "items": {"type": "string"}},
        "key_points": {
            "type": "array",
            "maxItems": 6,
            "items": {
                "type": "object",
                "properties": {
                    "check_id": {"type": "string"},
                    "text": {"type": "string"},
                },
                "required": ["check_id", "text"],
                "additionalProperties": False,
            },
        },
        "recommended_action_ids": {"type": "array", "items": {"type": "string"}},
        "key_limit_ids": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["outcome", "text", "report_quote", "explanation",
                 "supporting_check_ids", "key_points", "recommended_action_ids",
                 "key_limit_ids"],
    "additionalProperties": False,
}

L2_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "claims": {"type": "array", "items": CLAIM_ITEM_SCHEMA},
        "decision_seed": {"type": ["object", "null"],
                          "properties": {"text": {"type": "string"},
                                         "report_quote": {"type": "string"}},
                          "required": ["text", "report_quote"],
                          "additionalProperties": False},
        "actions": {"type": "array", "items": GUIDANCE_ITEM_SCHEMA},
        "limits": {"type": "array", "items": GUIDANCE_ITEM_SCHEMA},
        "no_material_claims_reason": {"type": "string"},
    },
    "required": ["claims", "decision_seed", "actions", "limits"],
    "additionalProperties": False,
}

L2_SCHEMA = {
    "type": "object",
    "properties": {"checks": {"type": "array", "items": CHECK_ITEM_SCHEMA}},
    "required": ["checks"],
    "additionalProperties": False,
}

L2_DECISION_SCHEMA = {
    "type": "object",
    "properties": {"decision": DECISION_SCHEMA},
    "required": ["decision"],
    "additionalProperties": False,
}

sys.path.insert(0, str(HERE))
sys.path.insert(0, str(KIT / "layer2"))
from artifact_text import ExtractedArtifact, extract, find_report  # noqa: E402
from receipts import load_text, normalize  # noqa: E402
from runtime import run_claude_json  # noqa: E402


L2_PLAN_PROMPT = """Inventory every material factual claim and conclusion in the visible report. A claim is material when reversing it would change the report's recommendation, requested action, stated risk, or a reader's interpretation of the result. Include every metric needed to establish or challenge those material conclusions. Do not inventory provenance metadata, environment labels, setup narration, or every metric row as a separate semantic claim unless it changes one of those conclusions. Do not stop after a sample or fixed number; there is no report-level claim limit.

Copy one exact visible report quote for each claim. For each claim, list every supplied evidence filename likely to address it; use an empty list for report-only checks. Also identify the report's central recommendation, concrete recommended actions, and stated limits. Give every action an A-prefixed ID and every limit an L-prefixed ID. Do not evaluate evidence yet. Output only the required JSON.

Treat visible footnotes, captions, table rows, and metric definitions as report content. Do not inventory tone, style, or scanner limitations. An empty claims array is allowed only when the report genuinely contains no material factual claim or conclusion; explain why in no_material_claims_reason.
"""

L2_PROMPT = """You are verifying an assigned batch from a complete material-claim inventory. Return exactly one check for every assigned claim ID. Do not add, omit, merge, or rename claims. Each check must have one outcome:
- confirmed: the cited evidence supports the report claim
- contradicted: the cited evidence conflicts with the report claim
- not_checkable: the supplied evidence does not establish the claim either way

Also include material report-only contradictions:
- internal: two parts of the report contradict each other
- logic: a conclusion is not supported by the report's own numbers
{format_checks}

Output ONLY this JSON shape:
{{"checks": [{{"id": "<assigned ID>", "type": "semantic|staleness|internal|logic|arithmetic|units|selection", "basis": "evidence|report", "verdict": "confirmed|contradicted|not_checkable", "importance": "material|supporting", "severity": "<high|medium|low, only for a contradiction>", "report_quote": "<assigned exact report quote>", "evidence_file": "<relative path for an evidence-based confirmation or contradiction>", "evidence_quote": "<exact text evidence, omit for JSON-pointer receipts>", "evidence_json": [{{"pointer": "/exact/JSON/Pointer", "value": "<exact parsed value>"}}], "report_quote_2": "<second exact report quote for a report-only check>", "explanation": "<one complete plain sentence>"}}]}}

Rules:
- Quotes must be exact visible text. Never quote HTML/XML tags or attributes.
- For JSON evidence, evidence_quote may instead contain two or more exact key/value pairs from the same JSON object. The harness verifies object identity and labels that receipt as evidence fields.
- Prefer evidence_json for JSON files. Each JSON Pointer must resolve to the exact supplied value. One exact pointer is sufficient because the path identifies the value unambiguously; use multiple pointers when a claim combines values.
- For a table row, copy the visible cells in order separated by spaces.
- Treat visible footnotes, captions, and metric definitions as report content. Use them to interpret units, periods, populations, and formulas.
- Evidence-based confirmed and contradicted checks require an evidence file and evidence quote.
- Report-only contradicted checks require report_quote and report_quote_2.
- A not_checkable check requires an exact report quote and a specific reason; do not attach a fake receipt.
- Severity describes the impact of a contradiction. Omit it for confirmed and not_checkable outcomes.
- If the explanation uses report values that are absent from report_quote, put those exact values in report_quote_2.
- Do not flag tone, style, or scanner limitations as report defects.
- Write complete sentences. Never truncate an explanation.
"""

L2_DECISION_PROMPT = """Assess the report's central recommendation using the validated claim outcomes. Do not adopt the report's recommendation as your own without attribution. In customer-facing text, make the distinction explicit: state what the report supports, what it does not support, and the scope in which that assessment holds. The text must be one or two crisp sentences and no more than 45 words. The explanation must be at most two sentences and name concrete evidence facts, not check counts, pipeline stages, or internal IDs.

A supported assessment cites only confirmed check IDs that establish it. A mixed or unsupported assessment cites the relevant confirmed and contradicted IDs. Use the smallest sufficient support chain; do not cite metadata merely because it was checked. Write three to six key_points linked to those IDs. Each point must be a concrete customer fact of at most 22 words; include the most important support and blocker, never process language. An unrelated not_checkable claim does not erase a scoped assessment whose support chain is complete. Select three to five decision-critical action IDs and one to three key limit IDs for the opening view; all remaining receipted actions and limits remain available in details. Put IDs only in the machine fields. Never use the words "grade" or "believe" in customer-facing text. Output only the required JSON. Write concise, complete sentences.
"""

L2_RECEIPT_REPAIR_PROMPT = """Repair only the invalid evidence receipts below. Return exactly one check for every assigned ID. Do not change the ID, type, importance, or report quote. Read the supplied evidence and return exact JSON Pointers and values that establish the whole claim. A claim may use pointers from more than one approved evidence file. If the supplied files do not establish the claim, return not_checkable with a specific reason instead of inventing a path. Output only the required JSON.\n"""


def log(message: str) -> None:
    print(f"grade: {message}", flush=True)


def artifact_written_message(verdict: str, semantic_status: str, path: Path) -> str:
    return (
        f"artifact written: {verdict}; semantic review {semantic_status} "
        f"→ {path}"
    )


def run(command, **kwargs):
    return subprocess.run(command, capture_output=True, text=True, **kwargs)


def sandbox_fixture(source: Path, destination: Path) -> None:
    if source.is_file():
        shutil.copy2(source, destination / source.name)
        return
    for path in source.rglob("*"):
        if path.is_dir():
            continue
        name = path.name.lower()
        is_answer_key = path.suffix.lower() == ".json" and "answer" in name
        if is_answer_key or any(name.startswith(prefix) for prefix in EXCLUDE):
            continue
        target = destination / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


def _command_error(command: list[str], result: subprocess.CompletedProcess) -> str:
    detail = (result.stderr or result.stdout).strip()
    return f"{' '.join(command[1:])} failed: {detail[-500:] or 'no diagnostic'}"


def layer1(sandbox: Path, workdir: Path, report: Path) -> dict:
    """Run deterministic HTML checks and bind every stage to the run we created."""
    init_command = [
        "summation-flow", "init", "--input", str(sandbox),
        "--artifact", str(report.relative_to(sandbox)),
    ]
    initialized = run(init_command, cwd=workdir)
    if initialized.returncode != 0:
        return {"error": _command_error(init_command, initialized)}
    match = re.search(r"\bRun\s+(sf-[A-Za-z0-9_-]+)\b",
                      initialized.stdout + initialized.stderr)
    if not match:
        return {"error": "init succeeded but did not report its run id"}
    run_id = match.group(1)
    for command in (
        ["summation-flow", "parse", "--run", run_id],
        ["summation-flow", "fanout", "--run", run_id],
        ["summation-flow", "verify", "--cold", "--run", run_id],
    ):
        result = run(command, cwd=workdir)
        if result.returncode != 0:
            return {"error": _command_error(command, result), "run_id": run_id}
    findings_path = Path.home() / ".summation-flow" / "runs" / run_id / "artifacts" / "findings.json"
    if not findings_path.is_file():
        return {"error": f"run {run_id} produced no findings.json", "run_id": run_id}
    return {
        "mode": "deterministic",
        "run_id": run_id,
        "findings_path": str(findings_path),
        "raw": json.loads(findings_path.read_text()),
    }


def agentic_raw(artifact: ExtractedArtifact, *, scan_completed: bool,
                deterministic_error: str | None = None) -> dict:
    """Renderer input for formats that have no deterministic claim ledger yet."""
    raw = {
        "agentic_only": True,
        "agentic_scan_completed": scan_completed,
        "findings": [],
        "coverage": {
            "claims_in_ledger": 0,
            "claims_reached_by_a_check": 0,
            "extractor_checkable_fraction": 0.0,
            "engine_checkable_fraction": 0.0,
            "checks_registered": 0,
            "checks_with_findings": 0,
            "checks_found_nothing": 0,
            "checks_errored": 1 if deterministic_error else 0,
        },
        "headline": {},
        "source": {
            "path": artifact.path.name,
            "format": artifact.format,
            "sha256": artifact.sha256,
            "bytes": artifact.bytes,
        },
        "findings_truncated": False,
        "extraction_method": artifact.method,
    }
    if deterministic_error:
        raw["deterministic_error"] = deterministic_error
    return raw


def failed_source_result(profile: str, technical_error: str) -> dict:
    low = technical_error.casefold()
    if "timeout" in low or "deadline exceeded" in low:
        message = "The source catalog did not respond before the timeout."
    elif "no table" in low or "table name" in low or "source mapping" in low:
        message = "The report table did not match one visible table in this source."
    elif "freshness" in low:
        message = "The live source check could not create a safe freshness query."
    else:
        message = "The live source check did not complete."
    return {
        "status": "failed",
        "profile": profile,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tables": [],
        "confirmed": 0,
        "contradicted": 0,
        "not_run": 0,
        "checks": [],
        "error": message,
        "technical_error": technical_error,
    }


def unable_raw(path: Path, reason: str) -> dict:
    return {
        "findings": [],
        "coverage": {"claims_in_ledger": 0, "checks_errored": 1},
        "headline": {},
        "source": {"path": path.name, "format": path.suffix.lstrip(".") or "unknown"},
        "findings_truncated": False,
        "intake_error": reason,
    }


def _l2_prompt(artifact: ExtractedArtifact, deterministic_layer_ran: bool) -> str:
    if deterministic_layer_ran:
        checks = ("- Do not report arithmetic, unit, rounding, or period defects; "
                  "the deterministic ledger checks those separately.")
    else:
        checks = ("- arithmetic: displayed totals or derived figures do not agree\n"
                  "- units: percent versus percentage points, scale, or unit labels are wrong\n"
                  "- selection: a ranked/top-N list is not ordered or selected as claimed")
    return L2_PROMPT.format(format_checks=checks)


def _claim_batches(claims: list[dict], size: int = L2_TARGET_CHECKS_PER_BATCH):
    """Partition every claim exactly once; size controls calls, never coverage."""
    if size < 1:
        raise ValueError("Layer 2 claim batch size must be positive")
    return [claims[start:start + size] for start in range(0, len(claims), size)]


def _routed_claim_batches(claims: list[dict],
                          size: int = L2_TARGET_CHECKS_PER_BATCH):
    """Keep claims with the same candidate evidence together, without omission."""
    groups: dict[tuple[str, ...], list[dict]] = {}
    for claim in claims:
        key = tuple(sorted(str(path) for path in claim.get("evidence_files") or []))
        groups.setdefault(key, []).append(claim)
    batches = []
    for key in sorted(groups):
        batches.extend(_claim_batches(groups[key], size=size))
    return batches


def _report_sections(text: str, target_chars: int = L2_SECTION_TARGET_CHARS) -> list[str]:
    """Split report text at heading-like lines; preserve every non-empty line once."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return []

    def heading_like(line: str) -> bool:
        words = line.split()
        return (
            len(line) <= 90
            and len(words) <= 12
            and not line.endswith((".", "?", "!", ",", ";"))
        )

    sections: list[list[str]] = [[]]
    current_chars = 0
    for line in lines:
        if (sections[-1] and current_chars >= target_chars
                and (heading_like(line) or current_chars >= target_chars * 1.35)):
            sections.append([])
            current_chars = 0
        sections[-1].append(line)
        current_chars += len(line) + 1
    return ["\n".join(section) for section in sections if section]


def _merge_section_plans(section_plans: list[tuple[int, dict]]) -> dict:
    """Merge section inventories without a report-level cap or duplicate receipts."""
    claims: list[dict] = []
    claim_by_key: dict[tuple[str, str], dict] = {}
    actions: list[dict] = []
    limits: list[dict] = []
    seen_actions = set()
    seen_limits = set()
    decision_seed = None
    reasons = []
    for _, plan in sorted(section_plans):
        if decision_seed is None and plan.get("decision_seed"):
            decision_seed = plan["decision_seed"]
        reason = str(plan.get("no_material_claims_reason") or "").strip()
        if reason:
            reasons.append(reason)
        for claim in plan.get("claims") or []:
            key = (normalize(claim.get("report_quote") or ""), str(claim.get("type") or ""))
            existing = claim_by_key.get(key)
            if existing is not None:
                existing["evidence_files"] = sorted(set(
                    list(existing.get("evidence_files") or [])
                    + list(claim.get("evidence_files") or [])))
                if claim.get("importance") == "material":
                    existing["importance"] = "material"
                continue
            merged = {**claim, "id": f"C{len(claims) + 1}"}
            claims.append(merged)
            claim_by_key[key] = merged
        for candidate in plan.get("actions") or []:
            key = (normalize(candidate.get("text") or ""),
                   normalize(candidate.get("report_quote") or ""))
            if key in seen_actions:
                continue
            seen_actions.add(key)
            actions.append({**candidate, "id": f"A{len(actions) + 1}"})
        for candidate in plan.get("limits") or []:
            key = (normalize(candidate.get("text") or ""),
                   normalize(candidate.get("report_quote") or ""))
            if key in seen_limits:
                continue
            seen_limits.add(key)
            limits.append({**candidate, "id": f"L{len(limits) + 1}"})
    return {
        "claims": claims,
        "decision_seed": decision_seed,
        "actions": actions,
        "limits": limits,
        "no_material_claims_reason": " ".join(reasons),
    }


def _evidence_manifest(sandbox: Path, paths: list[Path]) -> list[dict]:
    manifest = []
    for path in paths:
        item = {"path": str(path.relative_to(sandbox)), "bytes": path.stat().st_size}
        if path.suffix.lower() == ".json":
            try:
                payload = json.loads(path.read_text())
            except json.JSONDecodeError:
                pass
            else:
                if isinstance(payload, dict):
                    item["top_level_keys"] = list(payload)[:80]
        manifest.append(item)
    return manifest


def _routing_tokens(text: str) -> set[str]:
    text = re.sub(r"(?<=\d),(?=\d)", "", str(text).casefold())
    tokens = set(re.findall(r"[a-z][a-z0-9_./-]*|\d+(?:\.\d+)?", text))
    expanded = set(tokens)
    for token in tokens:
        expanded.update(part for part in re.split(r"[_./-]+", token) if part)
        if re.fullmatch(r"\d+(?:\.\d+)?", token):
            number = float(token)
            expanded.update(
                f"{number:.{places}f}".rstrip("0").rstrip(".")
                for places in (0, 1, 2)
            )
    return expanded - {
        "a", "an", "and", "as", "at", "be", "by", "for", "from", "in",
        "is", "it", "of", "on", "or", "the", "this", "to", "was", "were",
        "with",
    }


def _route_claim_evidence(
        claims: list[dict], sandbox: Path, paths: list[Path]) -> list[dict]:
    """Route claims from report text to evidence content without an LLM transcription."""
    file_tokens = {
        str(path.relative_to(sandbox)): _routing_tokens(
            path.name + "\n" + path.read_text(errors="replace"))
        for path in paths
    }
    known = set(file_tokens)
    routed = []
    for claim in claims:
        tokens = _routing_tokens(claim.get("report_quote") or "")
        scores = {}
        for name, evidence_tokens in file_tokens.items():
            overlap = tokens & evidence_tokens
            scores[name] = sum(
                5 if any(char.isdigit() for char in token) else 1
                for token in overlap)
        best = max(scores.values(), default=0)
        threshold = max(2, int(best * 0.6)) if best else 0
        content_matches = {
            name for name, score in scores.items()
            if score and score >= threshold
        }
        planner_hints = {
            str(name) for name in claim.get("evidence_files") or []
            if str(name) in known
        }
        routed.append({
            **claim,
            "evidence_files": sorted(content_matches | planner_hints),
        })
    return routed


def _evidence_prompt_text(path: Path) -> str:
    text = path.read_text(errors="replace")
    if path.suffix.lower() == ".json":
        try:
            return json.dumps(json.loads(text), ensure_ascii=False,
                              separators=(",", ":"))
        except json.JSONDecodeError:
            return text
    return text


def evidence_files(sandbox: Path, report: Path) -> list[Path]:
    """Evidence given to Layer 2, excluding the primary report itself."""
    return [
        path for path in sorted(sandbox.rglob("*"))
        if path.is_file()
        and path != report
        and path.suffix.lower() in EVIDENCE_SUFFIXES
    ]


def evidence_provenance_groups(sandbox: Path, checks: list[dict]) -> list[dict]:
    """Conservatively group cited files by declared source lineage."""
    groups: dict[str, dict] = {}
    cited_names = set()
    for check in checks:
        if check.get("verdict") not in {"confirmed", "contradicted"}:
            continue
        if check.get("evidence_file"):
            cited_names.add(str(check["evidence_file"]))
        cited_names.update(
            str(receipt.get("evidence_file"))
            for receipt in check.get("evidence_receipts") or []
            if receipt.get("evidence_file"))
    for name in sorted(cited_names):
        path = sandbox / name
        raw = path.read_bytes()
        kind = "file"
        identity = sha256(raw).hexdigest()
        if path.suffix.lower() == ".json":
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                payload = None
            if isinstance(payload, dict):
                source = payload.get("source")
                if isinstance(source, dict) and source.get("commit"):
                    kind = "git-commit"
                    identity = str(source["commit"])
                elif payload.get("rollout_id"):
                    kind = "agent-session"
                    identity = str(payload["rollout_id"])
                elif isinstance(source, str) and source.strip():
                    kind = "declared-source"
                    identity = source.strip()
        key = f"{kind}:{identity}"
        group = groups.setdefault(key, {
            "kind": kind,
            "identity": identity,
            "files": [],
        })
        group["files"].append(name)
    return list(groups.values())


def resolve_json_pointer_receipts(
        sandbox: Path, finding: dict, receipts: list[dict]) -> list[dict] | None:
    """Bind exact JSON pointers across one or more planner-approved files."""
    candidates = []
    for name in [finding.get("evidence_file"), *(finding.get("evidence_files") or [])]:
        name = str(name or "")
        if name and name not in candidates and (sandbox / name).is_file():
            candidates.append(name)
    grouped: dict[str, list[dict]] = {}
    for receipt in receipts:
        matched = None
        for name in candidates:
            ok, canonical = json_pointer_receipt(sandbox / name, [receipt])
            if ok:
                matched = (name, canonical[0])
                break
        if matched is None:
            return None
        name, canonical_receipt = matched
        grouped.setdefault(name, []).append(canonical_receipt)
    return [
        {"evidence_file": name, "evidence_json": grouped[name]}
        for name in candidates if name in grouped
    ]


def layer2(sandbox: Path, artifact: ExtractedArtifact, harness: str,
           model: str | None, claude_bin: str | None,
           deterministic_layer_ran: bool) -> dict:
    if harness != "claude-cli":
        return {"error": f"agentic harness {harness!r} is not wired for structured output"}
    supplied_evidence = evidence_files(sandbox, artifact.path)
    evidence_by_name = {
        str(path.relative_to(sandbox)): path for path in supplied_evidence}
    sections = _report_sections(artifact.text)
    if not sections:
        return {"error": "claim inventory found no report text"}
    layer_role = (
        "The rule-based document layer already checked every extracted numeric claim "
        "for applicable arithmetic, unit, period, selection, and grounding defects. "
        "Do not duplicate that ledger; inventory the complete decision-bearing semantic "
        "surface and the metrics needed to support it."
        if deterministic_layer_ran else
        "No rule-based document layer ran. Include material numeric claims needed for "
        "both internal and evidence-based verification."
    )
    global_context = "\n".join(artifact.text.splitlines()[:14])

    def plan_section(index: int, section: str):
        prompt = (
            L2_PLAN_PROMPT
            + f"\n{layer_role}\n"
            + "The global context is orientation only. Inventory claims only from the "
              "assigned report section. Return a decision seed only if this section "
              "contains the report's central recommendation. No evidence content or "
              "manifest is available during inventory; set evidence_files to [] for every "
              "claim. The harness routes evidence after the report inventory is complete.\n"
            + f"\n===== GLOBAL REPORT CONTEXT: {artifact.path.name} =====\n"
            + global_context
            + f"\n===== ASSIGNED REPORT SECTION {index + 1} OF {len(sections)} =====\n"
            + section
        )
        payload, metadata = run_claude_json(
            prompt, model=model,
            timeout=(L2_SECTION_PLAN_TIMEOUT_SECONDS
                     if len(sections) > 1 else L2_PLAN_TIMEOUT_SECONDS),
            claude_bin=claude_bin, schema=L2_PLAN_SCHEMA)
        return index, payload, metadata

    log(f"layer 2 inventory: {len(sections)} report sections")
    section_plans_by_index = {}
    plan_meta_by_index = {}
    pending = list(range(len(sections)))
    failures = []
    for attempt in (1, 2):
        failures = []
        with ThreadPoolExecutor(
                max_workers=min(L2_MAX_PARALLEL_PLAN_SECTIONS, len(pending))) as pool:
            futures = {
                pool.submit(plan_section, index, sections[index]): index
                for index in pending
            }
            for future in as_completed(futures):
                index = futures[future]
                try:
                    _, payload, metadata = future.result()
                    section_plans_by_index[index] = payload
                    plan_meta_by_index[index] = metadata
                    log(
                        f"layer 2 inventory: section {index + 1}/{len(sections)} "
                        f"complete ({len(payload.get('claims') or [])} claims)")
                except (RuntimeError, subprocess.TimeoutExpired, ValueError) as error:
                    failures.append((
                        index,
                        f"inventory section {index + 1}/{len(sections)} failed "
                        f"on attempt {attempt}: {error}",
                    ))
                    log(
                        f"layer 2 inventory: section {index + 1}/{len(sections)} "
                        f"failed on attempt {attempt}")
        pending = [index for index, _ in failures]
        if not pending:
            break
        log(f"layer 2 inventory: retrying {len(pending)} failed section(s)")
    plan_errors = [message for _, message in failures]
    section_plans = sorted(section_plans_by_index.items())
    if not section_plans:
        return {
            "error": "claim inventory failed for every report section",
            "batch_errors": plan_errors,
            "evidence_files": [str(path.relative_to(sandbox))
                               for path in supplied_evidence],
        }
    plan = _merge_section_plans(section_plans)
    plan_meta = [plan_meta_by_index[index] for index in sorted(plan_meta_by_index)]
    claims = _route_claim_evidence(
        plan.get("claims") or [], sandbox, supplied_evidence)
    plan["claims"] = claims
    if not isinstance(claims, list):
        return {"error": "claim inventory has no claims array"}
    report_text = normalize(artifact.text)
    seen_ids = set()
    for claim in claims:
        claim_id = str(claim.get("id") or "")
        quote = normalize(claim.get("report_quote") or "")
        if not claim_id or claim_id in seen_ids:
            return {"error": "claim inventory contains a missing or duplicate ID"}
        if not quote or quote not in report_text:
            return {"error": f"claim inventory quote for {claim_id} is not verbatim"}
        unknown_evidence = sorted(
            set(str(path) for path in claim.get("evidence_files") or [])
            - set(evidence_by_name))
        if unknown_evidence:
            return {"error": f"claim inventory {claim_id} names unknown evidence {unknown_evidence}"}
        seen_ids.add(claim_id)
    if not claims:
        reason = str(plan.get("no_material_claims_reason") or "").strip()
        if not reason:
            return {"error": "claim inventory returned no claims and no reason"}
        return {
            "proposed": [], "decision": None,
            "actions": plan.get("actions") or [], "limits": plan.get("limits") or [],
            "runtime": {"plan": plan_meta, "batches": [], "decision": None},
            "inventory_count": 0, "batch_errors": [],
            "evidence_files": [str(path.relative_to(sandbox))
                               for path in supplied_evidence],
        }

    def verify_batch(index: int, batch: list[dict]):
        routed_names = sorted({
            str(name) for claim in batch for name in claim.get("evidence_files") or []})
        evidence_parts = []
        for name in routed_names:
            evidence_parts += [
                f"\n===== EVIDENCE: {name} =====\n",
                _evidence_prompt_text(evidence_by_name[name]),
            ]
        prompt = (
            _l2_prompt(artifact, deterministic_layer_ran)
            + "\n===== ASSIGNED CLAIMS =====\n"
            + json.dumps(batch, indent=2, ensure_ascii=False)
            + f"\n===== REPORT: {artifact.path.name} =====\n"
            + artifact.text
            + "".join(evidence_parts)
        )
        try:
            payload, metadata = run_claude_json(
                prompt, model=model, timeout=L2_BATCH_TIMEOUT_SECONDS,
                claude_bin=claude_bin, schema=L2_SCHEMA)
        except (RuntimeError, subprocess.TimeoutExpired, ValueError) as error:
            raise RuntimeError(f"batch {index + 1} failed: {error}") from error
        checks = payload.get("checks")
        if not isinstance(checks, list):
            raise RuntimeError(f"batch {index + 1} returned no checks array")
        expected = {str(claim["id"]): claim for claim in batch}
        actual = {str(check.get("id") or ""): check for check in checks}
        if set(actual) != set(expected) or len(actual) != len(checks):
            missing = sorted(set(expected) - set(actual))
            extra = sorted(set(actual) - set(expected))
            raise RuntimeError(
                f"batch {index + 1} coverage mismatch; missing={missing}, extra={extra}")
        for claim_id, check in actual.items():
            claim = expected[claim_id]
            for key in ("type", "importance", "report_quote"):
                if check.get(key) != claim.get(key):
                    raise RuntimeError(
                        f"batch {index + 1} changed {key} for {claim_id}")
            check["evidence_files"] = list(claim.get("evidence_files") or [])
        return index, checks, metadata

    batches = _routed_claim_batches(claims)
    batch_results = {}
    batch_meta = {}
    batch_errors = list(plan_errors)
    log(f"layer 2 evidence: {len(batches)} routed batches")
    with ThreadPoolExecutor(max_workers=min(L2_MAX_PARALLEL_BATCHES, len(batches))) as pool:
        futures = {
            pool.submit(verify_batch, index, batch): index
            for index, batch in enumerate(batches)
        }
        for future in as_completed(futures):
            index = futures[future]
            try:
                _, checks, metadata = future.result()
                batch_results[index] = checks
                batch_meta[index] = metadata
                log(
                    f"layer 2 evidence: batch {index + 1}/{len(batches)} complete "
                    f"({len(checks)} outcomes)")
            except RuntimeError as error:
                batch_errors.append(str(error))
                log(f"layer 2 evidence: batch {index + 1}/{len(batches)} failed")

    checks = [check for index in sorted(batch_results)
              for check in batch_results[index]]
    repair_meta = []
    repair_errors = []
    _, invalid_receipts = validate_receipts(artifact, sandbox, checks)
    if invalid_receipts:
        log(f"layer 2 receipts: repairing {len(invalid_receipts)} invalid outcomes")
        routed_names = sorted({
            str(name)
            for check in invalid_receipts
            for name in ([check.get("evidence_file")]
                         + list(check.get("evidence_files") or []))
            if name and str(name) in evidence_by_name
        })
        repair_prompt = (
            L2_RECEIPT_REPAIR_PROMPT
            + "\n===== INVALID RECEIPTS =====\n"
            + json.dumps(invalid_receipts, indent=2, ensure_ascii=False)
            + f"\n===== REPORT: {artifact.path.name} =====\n"
            + artifact.text
            + "".join(
                f"\n===== EVIDENCE: {name} =====\n"
                + _evidence_prompt_text(evidence_by_name[name])
                for name in routed_names)
        )
        try:
            repaired_payload, metadata = run_claude_json(
                repair_prompt, model=model, timeout=L2_BATCH_TIMEOUT_SECONDS,
                claude_bin=claude_bin, schema=L2_SCHEMA)
            repaired = repaired_payload.get("checks")
            if not isinstance(repaired, list):
                raise RuntimeError("receipt repair returned no checks array")
            expected = {str(check["id"]): check for check in invalid_receipts}
            actual = {str(check.get("id") or ""): check for check in repaired}
            if set(actual) != set(expected) or len(actual) != len(repaired):
                raise RuntimeError("receipt repair changed claim coverage")
            for claim_id, check in actual.items():
                original = expected[claim_id]
                for key in ("type", "importance", "report_quote"):
                    if check.get(key) != original.get(key):
                        raise RuntimeError(
                            f"receipt repair changed {key} for {claim_id}")
                check["evidence_files"] = list(
                    original.get("evidence_files") or [])
            repaired_valid, _ = validate_receipts(
                artifact, sandbox, list(actual.values()))
            repaired_by_id = {
                str(check["id"]): check for check in repaired_valid}
            checks = [
                repaired_by_id.get(str(check.get("id")), check)
                for check in checks
            ]
            repair_meta.append(metadata)
            log(
                f"layer 2 receipts: recovered {len(repaired_valid)} of "
                f"{len(invalid_receipts)} outcomes")
        except (RuntimeError, subprocess.TimeoutExpired, ValueError) as error:
            repair_errors.append(f"receipt repair failed: {error}")
            log("layer 2 receipts: repair failed; validated outcomes are preserved")
    decision = None
    decision_meta = None
    decision_error = None
    seed = plan.get("decision_seed")
    if seed and checks:
        prevalidated, _ = validate_receipts(artifact, sandbox, checks)
        decision_prompt = (
            L2_DECISION_PROMPT
            + "\n===== REPORT DECISION SEED =====\n"
            + json.dumps(seed, indent=2, ensure_ascii=False)
            + "\n===== VALIDATED CLAIM OUTCOMES =====\n"
            + json.dumps(prevalidated, indent=2, ensure_ascii=False)
            + "\n===== RECEIPTED ACTION AND LIMIT CANDIDATES =====\n"
            + json.dumps({"actions": plan.get("actions") or [],
                          "limits": plan.get("limits") or []},
                         indent=2, ensure_ascii=False)
        )
        try:
            decision_payload, decision_meta = run_claude_json(
                decision_prompt, model=model, timeout=L2_DECISION_TIMEOUT_SECONDS,
                claude_bin=claude_bin, schema=L2_DECISION_SCHEMA)
            decision = decision_payload.get("decision")
        except (RuntimeError, subprocess.TimeoutExpired, ValueError) as error:
            decision_error = f"decision synthesis failed: {error}"

    return {
        "proposed": checks,
        "decision": decision,
        "actions": plan.get("actions") or [],
        "limits": plan.get("limits") or [],
        "runtime": {
            "plan": plan_meta,
            "batches": [batch_meta[index] for index in sorted(batch_meta)],
            "receipt_repair": repair_meta,
            "decision": decision_meta,
        },
        "inventory_count": len(claims),
        "inventory_sections_total": len(sections),
        "inventory_sections_completed": len(section_plans),
        "evidence_batches_total": len(batches),
        "evidence_batches_completed": len(batch_results),
        "batch_errors": batch_errors + repair_errors,
        "decision_error": decision_error,
        "evidence_files": [str(path.relative_to(sandbox))
                           for path in supplied_evidence],
    }


def validate_receipts(artifact: ExtractedArtifact, sandbox: Path,
                      proposed: list[dict]) -> tuple[list, list]:
    report_text = normalize(artifact.text)

    def in_report(quote: str) -> bool:
        normalized = normalize(quote)
        return bool(normalized) and normalized in report_text

    validated, discarded = [], []
    for finding in proposed:
        finding = {
            **finding,
            "basis": finding.get("basis") or (
                "report" if finding.get("type") in REPORT_ONLY_TYPES else "evidence"),
            "verdict": finding.get("verdict") or "contradicted",
            "importance": finding.get("importance") or "material",
        }
        if finding["verdict"] == "contradicted":
            finding["severity"] = finding.get("severity") or "medium"
        else:
            finding["severity"] = None
        problems = []
        receipt_updates = {}
        if not in_report(finding.get("report_quote", "")):
            problems.append("report_quote not verbatim in visible report text")
        second = finding.get("report_quote_2")
        finding_type = finding.get("type")
        basis = finding.get("basis")
        verdict = finding.get("verdict")
        if second and basis == "report" and not in_report(second):
            problems.append("report_quote_2 not verbatim in visible report text")
        elif second and basis != "report":
            # Semantic and staleness findings are receipted by evidence_file and
            # evidence_quote. Ignore a model's misplaced second evidence excerpt
            # rather than misrepresenting it as words from the report.
            receipt_updates["report_quote_2"] = None
        if basis == "report" and verdict == "contradicted" and not second:
            problems.append("report-only contradiction has no second report receipt")
        if basis == "evidence" and verdict in {"confirmed", "contradicted"}:
            evidence_name = str(finding.get("evidence_file") or "")
            evidence = sandbox / evidence_name if evidence_name else None
            json_receipts = finding.get("evidence_json") or []
            if json_receipts:
                resolved = resolve_json_pointer_receipts(
                    sandbox, finding, json_receipts)
                if resolved:
                    receipt_updates.update({
                        "evidence_file": (
                            resolved[0]["evidence_file"] if len(resolved) == 1 else None),
                        "evidence_receipts": resolved,
                        "evidence_receipt_mode": "json-pointers",
                        "evidence_json": [
                            receipt for group in resolved
                            for receipt in group["evidence_json"]],
                        "evidence_quote": None,
                    })
                else:
                    problems.append(
                        "one or more JSON Pointer receipts did not match the approved evidence files")
            elif not evidence_name or evidence is None or not evidence.exists():
                problems.append(f"evidence_file {evidence_name!r} missing")
            else:
                quote = normalize(finding.get("evidence_quote", ""))
                evidence_texts = (
                    load_text(evidence),
                    normalize(evidence.read_text(errors="replace")),
                )
                if quote and any(quote in text for text in evidence_texts):
                    receipt_updates["evidence_receipt_mode"] = "verbatim"
                else:
                    matched, canonical = json_field_receipt(evidence, quote)
                    if matched:
                        receipt_updates.update({
                            "evidence_receipt_mode": "json-object-fields",
                            "evidence_quote": canonical,
                        })
                    else:
                        problems.append(
                            "evidence_quote is neither verbatim nor two exact fields from one JSON object")
        if verdict == "not_checkable" and not str(finding.get("explanation") or "").strip():
            problems.append("not_checkable outcome has no reason")
        target = discarded if problems else validated
        target.append({**finding, **receipt_updates,
                       **({"problems": problems} if problems else {})})
    return validated, discarded


def validate_guidance(artifact: ExtractedArtifact, payload: dict,
                      checks: list[dict]) -> tuple[dict, list[str]]:
    """Receipt-check the customer decision, actions, and limits."""
    report_text = normalize(artifact.text)
    problems: list[str] = []
    machine_id = re.compile(r"\b[CAL]\d+\b")

    def valid_item(item, label: str):
        if not isinstance(item, dict):
            problems.append(f"{label} is not an object")
            return None
        quote = normalize(item.get("report_quote", ""))
        if not quote or quote not in report_text:
            problems.append(f"{label} report_quote not verbatim in visible report text")
            return None
        if not str(item.get("text") or "").strip():
            problems.append(f"{label} has no customer text")
            return None
        return item

    def valid_guidance_items(name: str, prefix: str) -> list[dict]:
        valid: list[dict] = []
        seen: set[str] = set()
        for index, candidate in enumerate(payload.get(name) or []):
            label = f"{name[:-1]} {index + 1}"
            item = valid_item(candidate, label)
            if item is None:
                continue
            item_id = str(item.get("id") or "").upper()
            if not re.fullmatch(rf"{prefix}\d+", item_id):
                problems.append(f"{label} has no valid {prefix}-prefixed ID")
                continue
            if item_id in seen:
                problems.append(f"{label} repeats ID {item_id}")
                continue
            seen.add(item_id)
            valid.append({**item, "id": item_id})
        return valid

    decision = payload.get("decision")
    if decision is not None:
        decision = valid_item(decision, "decision")
    actions = valid_guidance_items("actions", "A")
    limits = valid_guidance_items("limits", "L")

    by_id = {str(check.get("id")): check for check in checks}
    if decision:
        support_ids = [str(item) for item in decision.get("supporting_check_ids") or []]
        unknown_support = [item for item in support_ids if item not in by_id]
        if unknown_support:
            problems.append("decision names an unknown claim check")
            decision = None
        elif decision.get("outcome") == "supported":
            support = [by_id[item] for item in support_ids]
            if not support or any(check.get("verdict") != "confirmed" for check in support):
                problems.append("supported decision lacks a complete confirmed support chain")
                decision = None
    if decision:
        action_ids = {str(item["id"]) for item in actions}
        limit_ids = {str(item["id"]) for item in limits}
        support_ids = [str(item) for item in decision.get("supporting_check_ids") or []]
        key_points = []
        for index, point in enumerate(decision.get("key_points") or []):
            if not isinstance(point, dict):
                problems.append(f"key point {index + 1} is not an object")
                continue
            check_id = str(point.get("check_id") or "")
            point_text = str(point.get("text") or "").strip()
            if check_id not in by_id or check_id not in support_ids:
                problems.append(f"key point {index + 1} names an unsupported check")
                continue
            if not point_text or machine_id.search(point_text):
                problems.append(f"key point {index + 1} has invalid customer text")
                continue
            key_points.append({"check_id": check_id, "text": point_text})
        recommended = [
            str(item).upper() for item in decision.get("recommended_action_ids") or []]
        key_limits = [str(item).upper() for item in decision.get("key_limit_ids") or []]
        if any(item not in action_ids for item in recommended):
            problems.append("decision names an unknown recommended action")
            recommended = [item for item in recommended if item in action_ids]
        if any(item not in limit_ids for item in key_limits):
            problems.append("decision names an unknown key limit")
            key_limits = [item for item in key_limits if item in limit_ids]
        public_text = str(decision.get("text") or "")
        public_explanation = str(decision.get("explanation") or "")
        if machine_id.search(public_text) or machine_id.search(public_explanation):
            problems.append("decision customer prose exposed internal IDs")
            fallback_explanations = {
                "supported": (
                    "Validated checks support this scoped decision; the actions and limits "
                    "below define its boundary."),
                "mixed": (
                    "Validated checks support part of this decision and establish the "
                    "caveats below."),
                "not_supported": "Validated checks do not support this decision.",
                "not_checkable": "The available checks did not establish this decision.",
            }
            if machine_id.search(public_text):
                public_text = str(decision.get("report_quote") or "")
            public_explanation = fallback_explanations.get(
                str(decision.get("outcome")),
                "The validated checks establish the scoped result shown here.")
        decision = {
            **decision,
            "text": public_text,
            "explanation": public_explanation,
            "key_points": key_points,
            "recommended_action_ids": recommended,
            "key_limit_ids": key_limits,
        }
    return {"decision": decision, "actions": actions, "limits": limits}, problems


def _json_objects(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _json_objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from _json_objects(child)


def json_field_receipt(evidence: Path, quote: str) -> tuple[bool, str | None]:
    """Validate a compact JSON fragment against one object in the evidence."""
    if evidence.suffix.lower() != ".json" or not quote:
        return False, None
    candidate = quote.strip().rstrip(",")
    # Models sometimes mark omitted fields between two exact pairs. The marker
    # carries no evidence; remove it, then still require every pair to match one
    # parsed object below.
    candidate = re.sub(r",\s*(?:\.{3}|…)+\s*", ", ", candidate)
    if not candidate.startswith("{"):
        candidate = "{" + candidate
    if not candidate.endswith("}"):
        candidate += "}"
    try:
        fragment = json.loads(candidate)
        payload = json.loads(evidence.read_text())
    except (json.JSONDecodeError, OSError):
        return False, None
    if not isinstance(fragment, dict) or len(fragment) < 2:
        return False, None
    for obj in _json_objects(payload):
        if all(key in obj and obj[key] == expected for key, expected in fragment.items()):
            return True, json.dumps(fragment, ensure_ascii=False, separators=(", ", ": "))
    return False, None


def _json_pointer(payload, pointer: str):
    if pointer == "":
        return payload
    if not pointer.startswith("/"):
        raise KeyError(pointer)
    current = payload
    for raw in pointer[1:].split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            current = current[int(token)]
        elif isinstance(current, dict):
            current = current[token]
        else:
            raise KeyError(pointer)
    return current


def json_pointer_receipt(evidence: Path, receipts: list[dict]) -> tuple[bool, list[dict] | None]:
    """Validate unambiguous JSON Pointer/value receipts against parsed evidence."""
    if evidence.suffix.lower() != ".json" or not receipts:
        return False, None
    try:
        payload = json.loads(evidence.read_text())
    except (json.JSONDecodeError, OSError):
        return False, None
    canonical = []
    for receipt in receipts:
        if not isinstance(receipt, dict):
            return False, None
        pointer = str(receipt.get("pointer") or "")
        try:
            actual = _json_pointer(payload, pointer)
        except (KeyError, IndexError, ValueError, TypeError):
            return False, None
        if actual != receipt.get("value"):
            return False, None
        canonical.append({"pointer": pointer, "value": actual})
    return True, canonical


def _render(raw_path: Path, out: Path, *, run_id: str,
            layer2_path: Path | None,
            source_path: Path | None) -> subprocess.CompletedProcess:
    command = [sys.executable, str(KIT / "grade_artifact" / "render.py"),
               "--findings", str(raw_path), "--out-dir", str(out),
               "--run-id", run_id]
    if layer2_path:
        command += ["--layer2", str(layer2_path)]
    if source_path:
        command += ["--source", str(source_path)]
    return run(command)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--l2-harness", default="claude-cli")
    parser.add_argument("--l2-model", default="sonnet")
    parser.add_argument("--claude-bin", default=None)
    parser.add_argument("--skip-layer2", action="store_true")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--source-profile", default=None,
                        help="explicit sum-api profile for live read-only checks")
    source.add_argument("--mcp-session", default=None,
                        help="explicit connected mcpc session for direct live checks")
    parser.add_argument("--mcp-tool", action="append", default=[],
                        help="approved read-only MCP tool; repeat as needed")
    parser.add_argument("--mcpc", default=None,
                        help="path to mcpc for direct MCP source checks")
    parser.add_argument("--sum-api", default=None,
                        help="path to the sum-api helper used for live checks")
    args = parser.parse_args()
    if args.mcp_session and not args.mcp_tool:
        parser.error("--mcp-session requires at least one --mcp-tool")
    if args.source_profile and args.mcp_tool:
        parser.error("--mcp-tool requires --mcp-session")

    source_input = Path(args.input).resolve()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        sandbox = temp / "fixture"
        sandbox.mkdir()
        sandbox_fixture(source_input, sandbox)
        log(f"sandboxed {source_input.name} (answer keys and prior findings excluded)")

        intake_error = None
        try:
            report = find_report(sandbox)
            artifact = extract(report)
            log(f"read {report.name} via {artifact.method}")
        except (ValueError, RuntimeError) as error:
            intake_error = str(error)
            files = [path for path in sandbox.iterdir() if path.is_file()]
            report = files[0] if len(files) == 1 else sandbox / "unknown"
            artifact = None
            log(f"unable to read report: {intake_error}")

        workdir = temp / "run"
        workdir.mkdir()
        document_stage = {"status": "complete", "detail": None}
        if artifact and artifact.format in {"html", "htm"}:
            l1 = layer1(sandbox, workdir, report)
            if "error" in l1:
                log(f"LAYER 1 FAILED: {l1['error']}")
                document_stage = {
                    "status": "failed",
                    "detail": "The rule-based document checks did not complete.",
                }
                l1_error = l1["error"]
                l1 = {
                    "mode": "agentic-fallback",
                    "run_id": l1.get("run_id") or "document-check-failed",
                    "error": l1_error,
                    "raw": agentic_raw(
                        artifact, scan_completed=not args.skip_layer2,
                        deterministic_error=l1_error),
                }
                deterministic = False
            else:
                deterministic = True
                material = [finding for finding in l1["raw"].get("findings", [])
                            if finding.get("severity") in ("high", "catastrophic")
                            and finding.get("check_id") in CUSTOMER_L1_CHECKS]
                log(f"layer 1 ({l1['run_id']}): {len(material)} material defect(s)")
        elif artifact:
            deterministic = False
            document_stage = {
                "status": "not_available",
                "detail": f"Deterministic document checks are not available for {artifact.format.upper()} files.",
            }
            l1 = {"mode": "agentic-only", "run_id": "agentic",
                  "raw": agentic_raw(artifact, scan_completed=not args.skip_layer2)}
            raw_path = temp / "agentic-findings.json"
            raw_path.write_text(json.dumps(l1["raw"], indent=2))
            l1["findings_path"] = str(raw_path)
            log(f"layer 1: no deterministic {artifact.format.upper()} ledger; agentic scan is labeled")
        else:
            deterministic = False
            document_stage = {
                "status": "failed",
                "detail": "The report text could not be read.",
            }
            l1 = {"mode": "unable", "run_id": "unable",
                  "raw": unable_raw(report, intake_error or "unreadable report")}
            raw_path = temp / "unable-findings.json"
            raw_path.write_text(json.dumps(l1["raw"], indent=2))
            l1["findings_path"] = str(raw_path)

        claim_checks, validated, discarded = [], [], []
        guidance = {"decision": None, "actions": [], "limits": []}
        guidance_problems: list[str] = []
        l2_inventory_count = 0
        l2_inventory_sections_total = 0
        l2_inventory_sections_completed = 0
        l2_evidence_batches_total = 0
        l2_evidence_batches_completed = 0
        l2_batch_errors: list[str] = []
        l2_decision_error = None
        l2_runtime, supplied_evidence = None, []
        semantic_stage = {
            "status": "skipped" if args.skip_layer2 else "not_run",
            "detail": "The semantic review was skipped." if args.skip_layer2 else None,
        }
        if artifact and not args.skip_layer2:
            log("layer 2: reading the report against supplied evidence")
            l2 = layer2(sandbox, artifact, args.l2_harness, args.l2_model,
                        args.claude_bin, deterministic)
            supplied_evidence = list(l2.get("evidence_files") or [])
            l2_runtime = l2.get("runtime")
            l2_inventory_count = int(l2.get("inventory_count") or 0)
            l2_inventory_sections_total = int(
                l2.get("inventory_sections_total") or 0)
            l2_inventory_sections_completed = int(
                l2.get("inventory_sections_completed") or 0)
            l2_evidence_batches_total = int(l2.get("evidence_batches_total") or 0)
            l2_evidence_batches_completed = int(
                l2.get("evidence_batches_completed") or 0)
            l2_batch_errors = list(l2.get("batch_errors") or [])
            l2_decision_error = l2.get("decision_error")
            if "error" in l2:
                log(f"LAYER 2 FAILED: {l2['error']}")
                semantic_stage = {
                    "status": "failed",
                    "detail": (
                        "The semantic review did not produce claim-level outcomes. "
                        "No positive or negative evidence conclusion is available."
                    ),
                }
                if l1.get("mode") in {"agentic-only", "agentic-fallback"}:
                    l1["raw"]["agentic_scan_completed"] = False
            else:
                claim_checks, discarded = validate_receipts(
                    artifact, sandbox, l2["proposed"])
                guidance, guidance_problems = validate_guidance(
                    artifact, l2, claim_checks)
                validated = [
                    check for check in claim_checks
                    if check.get("verdict") == "contradicted"
                ]
                confirmed = sum(
                    check.get("verdict") == "confirmed" for check in claim_checks)
                not_checkable = sum(
                    check.get("verdict") == "not_checkable" for check in claim_checks)
                checked_files = {
                    str(check.get("evidence_file")) for check in claim_checks
                    if check.get("evidence_file")
                    and check.get("verdict") in {"confirmed", "contradicted"}
                }
                detail_parts = [
                    f"{len(claim_checks)} claim-level outcome"
                    f"{'s' if len(claim_checks) != 1 else ''}: "
                    f"{confirmed} confirmed, {len(validated)} contradicted, "
                    f"and {not_checkable} not checkable."
                ]
                if supplied_evidence:
                    detail_parts.append(
                        f"{len(checked_files)} of {len(supplied_evidence)} supplied evidence "
                        f"file{'s were' if len(supplied_evidence) != 1 else ' was'} cited "
                        "by a validated outcome."
                    )
                semantic_stage = {
                    "status": ("partial" if discarded or guidance_problems
                               or l2_batch_errors or l2_decision_error else "complete"),
                    "detail": " ".join(detail_parts)
                              + (f" {len(discarded)} proposed outcome"
                                 f"{'s were' if len(discarded) != 1 else ' was'} discarded "
                                 "because the receipt could not be validated."
                                 if discarded else "")
                              + (f" {len(guidance_problems)} decision, action, or limit "
                                 f"receipt{'s were' if len(guidance_problems) != 1 else ' was'} "
                                 "discarded."
                                 if guidance_problems else ""),
                }
                unverified = max(0, l2_inventory_count - len(l2["proposed"]))
                if unverified:
                    semantic_stage["detail"] += (
                        f" {unverified} inventoried claim"
                        f"{'s have' if unverified != 1 else ' has'} no batch outcome."
                    )
                if l2_decision_error:
                    semantic_stage["detail"] += " The decision synthesis did not complete."
                if l2_inventory_sections_total:
                    semantic_stage["detail"] += (
                        f" {l2_inventory_sections_completed} of "
                        f"{l2_inventory_sections_total} report sections were inventoried."
                    )
                if l2_evidence_batches_total:
                    semantic_stage["detail"] += (
                        f" {l2_evidence_batches_completed} of "
                        f"{l2_evidence_batches_total} evidence batches completed."
                    )
                log(f"layer 2: {len(l2['proposed'])} proposed · "
                    f"{len(claim_checks)} receipted outcomes · "
                    f"{len(discarded)} discarded")

        source = None
        source_path = None
        if args.source_profile or args.mcp_session:
            source_label = args.source_profile or args.mcp_session
            if not artifact:
                log("LAYER 3 FAILED: live source requested for an unreadable report")
                return 2
            provider = "sum-api" if args.source_profile else "mcp"
            log(f"layer 3: planning and running direct read-only checks on {source_label} via {provider}")
            command = [sys.executable, str(HERE / "sourcecheck.py"),
                       "--input", str(sandbox), "--out", str(out),
                       "--model", args.l2_model]
            if args.source_profile:
                command += ["--profile", args.source_profile]
            else:
                command += ["--mcp-session", args.mcp_session]
                for tool in args.mcp_tool:
                    command += ["--mcp-tool", tool]
                if args.mcpc:
                    command += ["--mcpc", args.mcpc]
            if args.claude_bin:
                command += ["--claude-bin", args.claude_bin]
            if args.sum_api and args.source_profile:
                command += ["--sum-api", args.sum_api]
            checked = run(command)
            source_path = out / "source-findings.json"
            if source_path.is_file():
                source = json.loads(source_path.read_text())
            else:
                detail = (checked.stderr or checked.stdout).strip()[-500:]
                source = failed_source_result(source_label, detail)
                source["provider"] = provider
                source_path.write_text(json.dumps(source, indent=2) + "\n")
            if checked.returncode != 0 or source.get("status") == "failed":
                log(f"LAYER 3 FAILED: {source.get('error')}")
                log("preserving the document and semantic grade with the live-source limit")
            elif source.get("status") == "not_applicable":
                log(f"layer 3: {source.get('error')}")
            elif source.get("status") == "partial":
                log(f"layer 3 incomplete: {source.get('error')}")
            else:
                log(f"layer 3: {source['confirmed']} confirmed · "
                    f"{source['contradicted']} contradicted · {source['not_run']} not run")

        layer2_path = None
        if claim_checks or guidance["decision"] or guidance["actions"] or guidance["limits"]:
            layer2_path = temp / "layer2-checks.json"
            layer2_path.write_text(json.dumps({
                "checks": claim_checks,
                **guidance,
            }))
        render_raw = json.loads(json.dumps(l1["raw"]))
        render_raw["verification"] = {
            "document": document_stage,
            "semantic": semantic_stage,
        }
        render_raw["evidence_files"] = supplied_evidence
        render_raw["evidence_review"] = {
            "outcomes_proposed": l2_inventory_count,
            "outcomes_validated": len(claim_checks),
            "receipt_failures": len(discarded),
            "provenance_groups": evidence_provenance_groups(
                sandbox, claim_checks),
        }
        render_raw_path = temp / "render-findings.json"
        render_raw_path.write_text(json.dumps(render_raw, indent=2) + "\n")
        rendered = _render(render_raw_path, out, run_id=l1["run_id"],
                           layer2_path=layer2_path, source_path=source_path)
        if rendered.returncode != 0:
            log(f"ARTIFACT RENDER FAILED: {(rendered.stderr or rendered.stdout).strip()[-500:]}")
            return 2
        artifact_doc = json.loads((out / "grade-artifact.json").read_text())
        defects = [finding for finding in l1["raw"].get("findings", [])
                   if finding.get("severity") in ("high", "catastrophic")
                   and finding.get("check_id") in CUSTOMER_L1_CHECKS]
        summary = {
            "grade_version": "grade-summary/v2",
            "input": source_input.name,
            "extraction": ({"format": artifact.format, "method": artifact.method,
                            "sha256": artifact.sha256} if artifact else
                           {"format": report.suffix.lstrip("."), "method": None,
                            "error": intake_error}),
            "layer1": {"mode": l1.get("mode", "deterministic"),
                       "run_id": l1.get("run_id"), "defects": len(defects),
                       "findings": l1["raw"].get("findings", []),
                       "error": l1.get("error")},
            "layer2": {"checks": claim_checks, "validated": validated,
                       "discarded": discarded,
                       "guidance": guidance,
                       "guidance_problems": guidance_problems,
                       "inventory_count": l2_inventory_count,
                       "inventory_sections_total": l2_inventory_sections_total,
                       "inventory_sections_completed": l2_inventory_sections_completed,
                       "evidence_batches_total": l2_evidence_batches_total,
                       "evidence_batches_completed": l2_evidence_batches_completed,
                       "batch_errors": l2_batch_errors,
                       "decision_error": l2_decision_error,
                       "runtime": l2_runtime,
                       "evidence_files": supplied_evidence,
                       "status": semantic_stage["status"]},
            "layer3_source": ({key: source.get(key) for key in
                               ("status", "error", "provider", "profile",
                                "source_identity", "generated_at",
                                "tables", "confirmed", "contradicted", "not_run")}
                              if source else None),
            "artifact_rendered": True,
            "verdict_hint": artifact_doc["verdict"],
        }
        (out / "grade-summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        log(artifact_written_message(
            artifact_doc["verdict"], semantic_stage["status"],
            out / "grade-artifact.html"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
