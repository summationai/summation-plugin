#!/usr/bin/env python3
"""Check report claims against a live Summation source, read-only and receipted."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from artifact_text import extract, find_report  # noqa: E402
from mcp_source import (  # noqa: E402
    McpSourceError,
    approved_tools,
    call_tool,
    normalized_payload,
    resolve_json_pointer,
    resolve_mcpc,
    response_sha256,
    session_identity,
    write_raw_receipt,
)
from runtime import resolve_sum_api, run_claude_json  # noqa: E402


PROMPT = """You plan read-only source checks for an existing report. The report's visible text and the schemas of source tables it explicitly names are below.

For each material claim the source can verify, return:
- id: S1, S2, ...
- kind: freshness or claim
- quote: exact visible report text
- sql: one DuckDB SELECT returning one row
- expected: returned alias -> value implied by the report

If this source cannot check a material claim, return no checks and explain why in uncheckable_reason. Name the authoritative source type needed in suggested_source (for example GitHub, Slack, Granola, Datadog, or a named warehouse). Do not pretend that a visible table is authoritative for code, meeting, or monitoring claims.

Freshness is mandatory only if the report explicitly says latest, last as-of, current, current through a date, or similar. In that case, the FIRST check must query MAX of the relevant date column. When possible, that same check should return the current headline counts at the latest date. Do not produce a freshness check otherwise: a report about one named historical period is not claiming that period is the latest. Never hard-code what the live source should return; expected values come only from the report.

Time alignment is mandatory. A dated report describes the state at its stated report or snapshot date unless a claim names another period. Scope SQL to the claim's effective period when the schema supports it. A current table value from after the report date does not contradict a historical snapshot. If the source cannot reconstruct the same period, a current-only query may show that the source has changed, but it must not be treated as proof that the historical claim was wrong.

Rules:
- SELECT only. One statement, one row. Aggregate as needed.
- Use snake_case columns exactly as shown.
- Skip opinions, plans, and claims the schemas cannot answer.
- Check every material claim the visible source schema can answer. Do not stop after a sample or fixed number.
- Output ONLY JSON:
{"checks": [{"id":"S1","kind":"freshness|claim","quote":"...","sql":"SELECT ...","expected":{"alias":123}}], "uncheckable_reason":"...", "suggested_source":"..."}
"""

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "checks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "kind": {"enum": ["freshness", "claim"]},
                    "quote": {"type": "string"},
                    "sql": {"type": "string"},
                    "expected": {"type": "object"},
                },
                "required": ["id", "kind", "quote", "sql", "expected"],
                "additionalProperties": False,
            },
        },
        "uncheckable_reason": {"type": "string"},
        "suggested_source": {"type": "string"},
    },
    "required": ["checks"],
    "additionalProperties": False,
}

MCP_PROMPT = """You plan direct, read-only checks of an existing report against an approved live MCP source. The report text and exact approved tool schemas are below.

Return a check for every material report claim this source can verify. Do not stop after a sample or a fixed number. For each check return:
- id: S1, S2, ...
- kind: freshness or claim
- quote: exact visible report text
- tool: one approved read-only MCP tool name
- arguments: arguments satisfying that tool's input schema
- expected: result alias -> value implied by the report

Time alignment is mandatory. Scope arguments to the claim's effective period when the tool supports it. A current result from after a dated report is a current observation, not proof for or against its historical snapshot.

If the approved tools cannot check a material claim, return no checks and explain why in uncheckable_reason. Name the authoritative source type or tool needed in suggested_source.

Rules:
- Use only the approved tools shown below.
- One MCP tool call per check.
- Expected values come only from the report. Never invent the source result.
- Skip opinions, plans, and claims these tools cannot answer.
- Output only JSON.
"""

MCP_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "checks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "kind": {"enum": ["freshness", "claim"]},
                    "quote": {"type": "string"},
                    "tool": {"type": "string"},
                    "arguments": {"type": "object"},
                    "expected": {"type": "object"},
                },
                "required": ["id", "kind", "quote", "tool", "arguments", "expected"],
                "additionalProperties": False,
            },
        },
        "uncheckable_reason": {"type": "string"},
        "suggested_source": {"type": "string"},
    },
    "required": ["checks"],
    "additionalProperties": False,
}

MCP_RESULT_PROMPT = """Map values from one raw MCP tool result to the requested result aliases for a report claim.

Return a JSON Pointer into the supplied normalized payload for every requested alias. A pointer must resolve to the exact raw value; do not copy or rewrite values. You are not given the report's expected values and must not decide whether the source agrees. If the response explicitly shows that the requested record is absent, set missing to true. Otherwise omit aliases that cannot be mapped.

Output only JSON:
{"missing": false, "paths": {"alias": "/path/to/value"}}
"""

MCP_RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "missing": {"type": "boolean"},
        "paths": {"type": "object", "additionalProperties": {"type": "string"}},
    },
    "required": ["missing", "paths"],
    "additionalProperties": False,
}


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(message: str) -> None:
    print(f"sourcecheck: {message}", flush=True)


def sql_query(sum_api: Path, profile: str, sql: str, *, timeout: int = 120,
              limit: int = 50) -> dict:
    result = subprocess.run(
        ["uv", "run", str(sum_api), "--profile", profile, "sql", sql,
         "--limit", str(limit)], capture_output=True, text=True, timeout=timeout)
    output = result.stdout
    start = output.find("{")
    if result.returncode != 0 or start < 0:
        return {"error": (output + result.stderr)[-500:]}
    try:
        return json.loads(output[start:])
    except json.JSONDecodeError:
        return {"error": output[-500:]}


def sql_query_with_retry(sum_api: Path, profile: str, sql: str, *,
                         timeout: int = 120, limit: int = 50) -> dict:
    response = sql_query(sum_api, profile, sql, timeout=timeout, limit=limit)
    if "error" in response:
        log("read-only source query did not return a result; retrying once")
        response = sql_query(sum_api, profile, sql, timeout=timeout, limit=limit)
    return response


def rows_of(response: dict) -> list[dict]:
    rows = (((response.get("data") or {}).get("result")) or {}).get("rows") or []
    unpacked = []
    for row in rows:
        columns = row.get("columns")
        if isinstance(columns, dict):
            unpacked.append(columns)
        elif isinstance(columns, list):
            unpacked.append({item.get("columnName"): item.get("columnValue")
                             for item in columns})
    return unpacked


def snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def match_named_tables(report_text: str, names: list[str]) -> dict[str, str]:
    """Map visible report identifiers to catalog tables without guessing.

    Exact names win. A shortened name can match one catalog table only when it
    is a unique underscore-delimited suffix of that table.
    """
    matches: dict[str, str] = {}
    for name in names:
        if re.search(
            rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])",
            report_text, re.I,
        ):
            matches[name] = name

    identifiers = sorted(set(re.findall(
        r"\b[A-Za-z][A-Za-z0-9_]{7,}\b", report_text)),
        key=len, reverse=True)
    for alias in identifiers:
        if alias.count("_") < 2:
            continue
        candidates = [
            name for name in names
            if name not in matches
            and name.casefold().endswith("_" + alias.casefold())
        ]
        if len(candidates) == 1:
            matches[candidates[0]] = alias
    return matches


def report_table_identifiers(report_text: str) -> list[str]:
    """Return visible identifiers that can plausibly name a source table."""
    return sorted({
        token.casefold() for token in re.findall(
            r"\b[A-Za-z][A-Za-z0-9_]{7,}\b", report_text)
        if "_" in token
    })[:40]


def discover_tables(sum_api: Path, profile: str,
                    report_text: str) -> dict[str, list[str]]:
    identifiers = report_table_identifiers(report_text)
    if not identifiers:
        return {}
    clauses = []
    for identifier in identifiers:
        escaped = identifier.replace("'", "''")
        clauses.append(
            f"(lower(table_name) = '{escaped}' OR "
            f"lower(table_name) LIKE '%{escaped}')")
    discovery_sql = (
        "SELECT DISTINCT table_name FROM information_schema.tables WHERE "
        + " OR ".join(clauses)
        + " ORDER BY table_name")
    response = sql_query_with_retry(sum_api, profile, discovery_sql, limit=500)
    if "error" in response:
        raise RuntimeError(f"table discovery failed: {response['error']}")
    names = []
    for row in rows_of(response):
        normalized = {snake(key): value for key, value in row.items()}
        table = normalized.get("table_name")
        if table:
            names.append(str(table))
    matches = match_named_tables(report_text, names)
    tables = {}
    for table, alias in matches.items():
        if alias != table:
            log(f"matched report table {alias} to visible table {table}")
        escaped = table.replace("'", "''")
        columns = sql_query(
            sum_api, profile,
            f"SELECT column_name FROM information_schema.columns WHERE table_name = '{escaped}'",
            limit=500)
        if "error" in columns:
            raise RuntimeError(f"schema lookup for {table} failed: {columns['error']}")
        tables[table] = [
            {snake(key): value for key, value in row.items()}.get("column_name")
            for row in rows_of(columns)
        ]
    return tables


def plan_checks(report_text: str, tables: dict[str, list[str]], *,
                model: str | None, claude_bin: str | None,
                force_freshness: bool = False,
                snapshot_date: date | None = None) -> tuple[list[dict], dict]:
    schemas = "\n".join(
        f"TABLE {table}: columns {', '.join(str(col) for col in columns if col)}"
        for table, columns in tables.items())
    retry_instruction = (
        "\nRETRY REQUIREMENT: This report makes a freshness claim. "
        "The first check must have kind freshness and must query MAX of the relevant date column.\n"
        if force_freshness else "")
    snapshot_instruction = (
        f"\nREPORT SNAPSHOT DATE: {snapshot_date.isoformat()}. "
        "Use the same effective period for comparisons whenever the source permits it.\n"
        if snapshot_date else "")
    payload, metadata = run_claude_json(
        PROMPT + retry_instruction + snapshot_instruction
        + "\n===== REPORT =====\n" + report_text
        + "\n===== SCHEMAS =====\n" + schemas,
        model=model, timeout=240, claude_bin=claude_bin, schema=PLAN_SCHEMA)
    checks = payload.get("checks")
    if not isinstance(checks, list):
        raise RuntimeError("source planner returned no checks array")
    metadata = {
        **metadata,
        "uncheckable_reason": payload.get("uncheckable_reason"),
        "suggested_source": payload.get("suggested_source"),
    }
    return checks, metadata


def plan_mcp_checks(report_text: str, tools: dict[str, dict], *,
                    model: str | None, claude_bin: str | None,
                    force_freshness: bool = False,
                    snapshot_date: date | None = None) -> tuple[list[dict], dict]:
    retry_instruction = (
        "\nRETRY REQUIREMENT: This report makes a freshness claim. "
        "The first check must have kind freshness and query the current source time or value.\n"
        if force_freshness else "")
    snapshot_instruction = (
        f"\nREPORT SNAPSHOT DATE: {snapshot_date.isoformat()}. "
        "Use the same effective period whenever the source supports it.\n"
        if snapshot_date else "")
    payload, metadata = run_claude_json(
        MCP_PROMPT + retry_instruction + snapshot_instruction
        + "\n===== REPORT =====\n" + report_text
        + "\n===== APPROVED TOOLS =====\n"
        + json.dumps(list(tools.values()), indent=2, ensure_ascii=False),
        model=model, timeout=240, claude_bin=claude_bin,
        schema=MCP_PLAN_SCHEMA)
    checks = payload.get("checks")
    if not isinstance(checks, list):
        raise RuntimeError("MCP source planner returned no checks array")
    for check in checks:
        if check.get("tool") not in tools:
            raise ValueError(
                f"MCP source planner selected unapproved tool {check.get('tool')!r}")
    metadata = {
        **metadata,
        "uncheckable_reason": payload.get("uncheckable_reason"),
        "suggested_source": payload.get("suggested_source"),
    }
    return checks, metadata


def map_mcp_result(check: dict, payload, *, model: str | None,
                   claude_bin: str | None) -> tuple[dict, dict]:
    mapped, metadata = run_claude_json(
        MCP_RESULT_PROMPT
        + "\n===== REQUESTED ALIASES =====\n"
        + json.dumps(list((check.get("expected") or {}).keys()),
                     indent=2, ensure_ascii=False)
        + "\n===== NORMALIZED MCP PAYLOAD =====\n"
        + json.dumps(payload, indent=2, ensure_ascii=False),
        model=model, timeout=240, claude_bin=claude_bin,
        schema=MCP_RESULT_SCHEMA)
    return mapped, metadata


SENSITIVE_ARGUMENT = re.compile(
    r"(?:api[_-]?key|authorization|bearer|password|secret|token)", re.I)


def redact_arguments(value):
    if isinstance(value, dict):
        return {
            str(key): ("<redacted>" if SENSITIVE_ARGUMENT.search(str(key))
                       else redact_arguments(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_arguments(item) for item in value]
    return value


def run_mcp_source(artifact, out: Path, *, session: str,
                   approved_tool_names: list[str], mcpc_path: str | None,
                   model: str | None, claude_bin: str | None) -> int:
    identity = None
    tools = {}
    snapshot_date = report_snapshot_date(artifact.text)
    try:
        mcpc = resolve_mcpc(mcpc_path)
        identity = session_identity(mcpc, session)
        tools = approved_tools(mcpc, session, approved_tool_names)
        log(f"live MCP source {identity['server_name']} ({session})")
        if snapshot_date:
            log(f"report snapshot date: {snapshot_date.isoformat()}")
        log("planning checks with explicitly approved read-only tools")
        checks, planner_runtime = plan_mcp_checks(
            artifact.text, tools, model=model, claude_bin=claude_bin,
            snapshot_date=snapshot_date)
        needs_freshness = report_requires_freshness(artifact.text)
        try:
            normalized = normalize_checks(checks, needs_freshness=needs_freshness)
        except ValueError:
            log("MCP source plan omitted the required freshness check; retrying once")
            checks, planner_runtime = plan_mcp_checks(
                artifact.text, tools, model=model, claude_bin=claude_bin,
                force_freshness=True, snapshot_date=snapshot_date)
            normalized = normalize_checks(checks, needs_freshness=needs_freshness)
        checks = normalized
    except (McpSourceError, RuntimeError, ValueError,
            subprocess.TimeoutExpired) as error:
        failure = {
            "status": "failed", "provider": "mcp", "profile": session,
            "source_identity": identity, "generated_at": now(), "tables": [],
            "confirmed": 0, "contradicted": 0, "not_run": 0, "checks": [],
            "error": customer_source_error(str(error)), "technical_error": str(error),
        }
        (out / "source-findings.json").write_text(
            json.dumps(failure, indent=2) + "\n")
        print(f"sourcecheck: {error}", file=sys.stderr)
        return 2

    if not checks:
        no_claims = {
            "status": "not_applicable", "provider": "mcp", "profile": session,
            "source_identity": identity, "generated_at": now(), "tables": [],
            "confirmed": 0, "contradicted": 0, "not_run": 0, "checks": [],
            "error": (planner_runtime.get("uncheckable_reason")
                      or "The approved MCP tools did not map to a material report claim."),
            "suggested_source": planner_runtime.get("suggested_source"),
        }
        destination = out / "source-findings.json"
        destination.write_text(json.dumps(no_claims, indent=2) + "\n")
        log(f"MCP source connected, but no report claim could be checked → {destination}")
        return 0

    normalized_report = re.sub(r"\s+", " ", artifact.text).casefold()
    results = []
    comparison_runtimes = []
    response_cache = {}
    for check in checks:
        checked_at = now()
        quote = re.sub(r"\s+", " ", str(check.get("quote", ""))).strip()
        if not quote or quote.casefold() not in normalized_report:
            results.append({**check, "verdict": "not_run",
                            "why": "quote not verbatim in visible report text",
                            "queried_at": checked_at})
            continue
        tool_name = str(check.get("tool") or "")
        if tool_name not in tools:
            results.append({**check, "verdict": "not_run",
                            "why": "tool was not explicitly approved",
                            "queried_at": checked_at})
            continue
        arguments = check.get("arguments") or {}
        try:
            cache_key = (tool_name, json.dumps(
                arguments, ensure_ascii=False, sort_keys=True,
                separators=(",", ":")))
            if cache_key in response_cache:
                response, receipt_path, payload = response_cache[cache_key]
            else:
                response = call_tool(mcpc, session, tool_name, arguments)
                receipt_path = write_raw_receipt(
                    out, str(check.get("id") or "check"), response)
                payload = normalized_payload(response)
                response_cache[cache_key] = (response, receipt_path, payload)
            mapping, mapping_runtime = map_mcp_result(
                check, payload, model=model, claude_bin=claude_bin)
            comparison_runtimes.append(mapping_runtime)
            paths = mapping.get("paths") or {}
            temporal_check = {
                **check,
                "sql": json.dumps(arguments, ensure_ascii=False, sort_keys=True),
            }
            if mapping.get("missing"):
                comparison = result_for_rows(
                    temporal_check, [], snapshot_date=snapshot_date,
                    queried_at=checked_at)
            else:
                missing_aliases = [alias for alias in (check.get("expected") or {})
                                   if alias not in paths]
                if missing_aliases:
                    raise McpSourceError(
                        "MCP response did not map expected aliases: "
                        + ", ".join(missing_aliases))
                actual = {
                    alias: resolve_json_pointer(payload, str(paths[alias]))
                    for alias in (check.get("expected") or {})
                }
                comparison = result_for_rows(
                    temporal_check, [actual], snapshot_date=snapshot_date,
                    queried_at=checked_at)
                comparison.pop("sql", None)
            receipt = {
                "kind": "mcp", "source": identity, "tool": tool_name,
                "arguments": redact_arguments(arguments),
                "response_sha256": response_sha256(response),
                "response_path": str(receipt_path.relative_to(out)),
                "value_paths": paths,
            }
            results.append({**check, **comparison, "receipt": receipt,
                            "queried_at": checked_at})
            log(f"{check.get('id')}: {comparison['verdict']} via {tool_name}")
        except (McpSourceError, RuntimeError, ValueError,
                subprocess.TimeoutExpired) as error:
            results.append({**check, "verdict": "not_run",
                            "why": str(error)[:300], "queried_at": checked_at})

    not_run_count = sum(result["verdict"] == "not_run" for result in results)
    summary = {
        "status": "partial" if not_run_count else "complete",
        "provider": "sum-api",
        "provider": "mcp", "profile": session, "source_identity": identity,
        "error": ("One or more live MCP calls did not return a receipted result."
                  if not_run_count else None),
        "generated_at": now(),
        "report": {"path": artifact.path.name, "format": artifact.format,
                   "sha256": artifact.sha256, "extraction_method": artifact.method},
        "report_snapshot_date": snapshot_date.isoformat() if snapshot_date else None,
        "tables": [],
        "confirmed": sum(result["verdict"] == "confirmed" for result in results),
        "contradicted": sum(result["verdict"] == "contradicted" for result in results),
        "changed_since_report": sum(
            result["verdict"] == "changed_since_report" for result in results),
        "matches_current_source": sum(
            result["verdict"] == "matches_current_source" for result in results),
        "not_run": not_run_count,
        "agent_runtime": {"planner": planner_runtime,
                          "comparators": comparison_runtimes},
        "checks": results,
    }
    destination = out / "source-findings.json"
    destination.write_text(json.dumps(summary, indent=2) + "\n")
    log(f"{summary['confirmed']} confirmed · {summary['contradicted']} contradicted · "
        f"{summary['changed_since_report']} changed since report · "
        f"{summary['matches_current_source']} current matches · "
        f"{summary['not_run']} not run → {destination}")
    return 0


def as_number(value):
    try:
        return float(str(value).replace(",", "").replace("$", "").replace("%", ""))
    except (ValueError, TypeError):
        return None


def compare(expected, actual) -> bool:
    expected_number, actual_number = as_number(expected), as_number(actual)
    if expected_number is not None and actual_number is not None:
        if isinstance(expected, int) and not isinstance(expected, bool):
            return expected_number == actual_number
        return abs(expected_number - actual_number) <= max(
            1e-9, abs(expected_number) * 0.000001)
    return str(expected).strip().casefold() == str(actual).strip().casefold()


WRITE_SQL = re.compile(
    r"\b(insert|update|delete|merge|drop|alter|create|truncate|copy|attach|detach|"
    r"install|load|call|pragma|vacuum)\b", re.I)


def is_readonly_select(sql: str) -> bool:
    """Allow one SELECT, including SELECTs prefixed by read-only CTEs."""
    statement = sql.strip()
    if statement.endswith(";"):
        statement = statement[:-1].rstrip()
    if not statement or ";" in statement:
        return False
    if not re.match(r"^(select|with)\b", statement, re.I):
        return False
    if WRITE_SQL.search(statement):
        return False
    return bool(re.search(r"\bselect\b", statement, re.I))


def report_requires_freshness(report_text: str) -> bool:
    patterns = (
        r"\blast\s+as[- ]of\b",
        r"\bcurrent\s+(?:through|as[- ]of)\b",
        r"\bdata\s+(?:is\s+)?current\b",
        r"\bdata\s+through\b",
        r"\blatest\s+(?:data|date|day|week|month|quarter|period|as[- ]of)\b",
        r"\b(?:figures|numbers|results)\s+are\s+current\b",
    )
    return any(re.search(pattern, report_text, re.I) for pattern in patterns)


MONTHS = {
    name.casefold(): number
    for number, name in enumerate(
        ("January", "February", "March", "April", "May", "June",
         "July", "August", "September", "October", "November", "December"),
        start=1)
}


def _date_in_text(value: str) -> date | None:
    month_range = re.search(
        r"\b(" + "|".join(MONTHS) + r")\s+\d{1,2}\s*[–—-]\s*"
        r"(\d{1,2})(?:st|nd|rd|th)?[,]?\s+(20\d{2})\b",
        value, re.I)
    if month_range:
        try:
            return date(
                int(month_range.group(3)),
                MONTHS[month_range.group(1).casefold()],
                int(month_range.group(2)),
            )
        except ValueError:
            return None
    iso = re.search(r"\b(20\d{2})-(\d{2})-(\d{2})\b", value)
    if iso:
        try:
            return date(*(int(part) for part in iso.groups()))
        except ValueError:
            return None
    named = re.search(
        r"\b(" + "|".join(MONTHS) + r")\s+(\d{1,2})(?:st|nd|rd|th)?[,]?\s+(20\d{2})\b",
        value, re.I)
    if named:
        try:
            return date(int(named.group(3)), MONTHS[named.group(1).casefold()],
                        int(named.group(2)))
        except ValueError:
            return None
    return None


def report_snapshot_date(report_text: str) -> date | None:
    """Read an explicit report-level date without guessing from incidental dates."""
    labels = (
        r"(?:last\s+updated|report\s+date|snapshot\s+date|data\s+as[- ]of)\s*:?\s*([^\n]{0,120})",
        r"(?:^|\n)\s*current\s+at\s+([^\n]{0,160})",
    )
    for pattern in labels:
        match = re.search(pattern, report_text, re.I)
        if match:
            parsed = _date_in_text(match.group(1))
            if parsed:
                return parsed
    # Titles and header subtitles commonly carry the report date without a
    # label (for example, "Operations dashboard · August 17, 2026"). Limit
    # this fallback to the opening lines so dates in the report body do not
    # become accidental publication dates.
    for line in report_text.splitlines()[:5]:
        parsed = _date_in_text(line)
        if parsed:
            return parsed
    return None


def _dates_in_text(value: str, *, default_year: int | None = None) -> set[date]:
    dates: set[date] = set()
    for match in re.finditer(r"\b(20\d{2})-(\d{2})-(\d{2})\b", value):
        try:
            dates.add(date(*(int(part) for part in match.groups())))
        except ValueError:
            continue
    named_pattern = (
        r"\b(" + "|".join(MONTHS) + r")\s+(\d{1,2})(?:st|nd|rd|th)?"
        r"(?:[,]?\s+(20\d{2}))?\b"
    )
    for match in re.finditer(named_pattern, value, re.I):
        year = int(match.group(3)) if match.group(3) else default_year
        if year is None:
            continue
        try:
            dates.add(date(year, MONTHS[match.group(1).casefold()], int(match.group(2))))
        except ValueError:
            continue
    return dates


def query_is_time_aligned(check: dict, snapshot_date: date) -> bool:
    """Require the query to contain the claim's effective date, not any date."""
    claim_dates = _dates_in_text(
        str(check.get("quote") or ""), default_year=snapshot_date.year)
    if not claim_dates:
        claim_dates = {snapshot_date}
    sql_dates = _dates_in_text(str(check.get("sql") or ""))
    return bool(claim_dates & sql_dates)


def query_uses_historical_snapshot(check: dict, snapshot_date: date) -> bool:
    """Recognize explicit source-time travel, not only a business-date filter."""
    sql = str(check.get("sql") or "")
    has_snapshot_date = snapshot_date.isoformat() in sql
    time_travel = re.search(
        r"\b(?:for\s+system_time\s+as\s+of|timestamp\s+as\s+of|version\s+as\s+of)\b"
        r"|\bat\s*\(\s*timestamp\s*=>",
        sql, re.I)
    return bool(has_snapshot_date and time_travel)


def _query_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return _date_in_text(value)


def normalize_checks(checks: list[dict], *, needs_freshness: bool) -> list[dict]:
    """Put a required freshness check first and remove unclaimed ones."""
    if needs_freshness:
        freshness = [check for check in checks if check.get("kind") == "freshness"]
        if not freshness:
            raise ValueError("the source plan contains no required freshness check")
        first = freshness[0]
        return [first] + [check for check in checks if check is not first]
    return [check for check in checks if check.get("kind") != "freshness"]


def customer_source_error(error: str) -> str:
    low = error.casefold()
    if "timeout" in low or "deadline exceeded" in low:
        return "The source catalog did not respond before the timeout."
    if "no table" in low or "table name" in low or "source mapping" in low:
        return "The report table did not match one visible table in this source."
    if "freshness" in low:
        return "The live source planner could not create a safe freshness query."
    return "The live source check did not complete."


def result_for_rows(check: dict, rows: list[dict], *,
                    snapshot_date: date | None = None,
                    queried_at: str | None = None) -> dict:
    """Compare one successful query result with report-implied values."""
    expected_values = check.get("expected") or {}
    if not expected_values:
        return {
            "verdict": "not_run",
            "why": "planner supplied no report-implied expected values",
        }
    query_date = _query_date(queried_at)
    current_only = bool(
        snapshot_date and query_date and query_date > snapshot_date
        and not query_uses_historical_snapshot(check, snapshot_date)
    )
    if not rows:
        result = {
            "verdict": "changed_since_report" if current_only else "contradicted",
            "actual_row": {},
            "matches": {},
            "mismatches": {
                alias: {"expected": expected, "actual": None}
                for alias, expected in expected_values.items()
            },
            "missing_row": True,
            "why": ("the current source returned no matching row"
                    if current_only else "the source returned no matching row"),
        }
        if current_only:
            result.update({
                "report_snapshot_date": snapshot_date.isoformat(),
                "comparison_scope": "current_source_vs_historical_snapshot",
                "why": (
                    f"The report is dated {snapshot_date.isoformat()}, but the current "
                    f"source on {query_date.isoformat()} returned no matching row without "
                    "a same-period filter. That does not prove the historical record was absent."
                ),
            })
        return result
    if len(rows) != 1:
        return {
            "verdict": "not_run",
            "why": f"query returned {len(rows)} rows; expected one",
        }
    actual = {snake(key): value for key, value in rows[0].items()}
    mismatches, matches = {}, {}
    for alias, expected in expected_values.items():
        observed = actual.get(snake(alias))
        target = matches if compare(expected, observed) else mismatches
        target[alias] = {"expected": expected, "actual": observed}
    verdict = "contradicted" if mismatches else "confirmed"
    if current_only:
        verdict = "changed_since_report" if mismatches else "matches_current_source"
    result = {
        "verdict": verdict,
        "actual_row": actual,
        "matches": matches,
        "mismatches": mismatches,
    }
    if verdict in {"changed_since_report", "matches_current_source"}:
        result.update({
            "report_snapshot_date": snapshot_date.isoformat(),
            "comparison_scope": "current_source_vs_historical_snapshot",
            "why": (
                f"The report is dated {snapshot_date.isoformat()}, but this query read "
                f"the current source on {query_date.isoformat()} without an explicit "
                "same-period filter. "
                + ("The difference does not prove the historical claim was wrong."
                   if verdict == "changed_since_report" else
                   "The current match supports the value now but does not prove the "
                   "historical snapshot independently.")
            ),
        })
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--out", required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--profile",
                        help="explicit sum-api profile; never defaults to production")
    source.add_argument("--mcp-session",
                        help="explicit connected mcpc session, for example @insightsentry")
    parser.add_argument("--mcp-tool", action="append", default=[],
                        help="approved read-only MCP tool; repeat for each allowed tool")
    parser.add_argument("--mcpc", default=None,
                        help="path to mcpc for direct MCP source checks")
    parser.add_argument("--model", default="sonnet")
    parser.add_argument("--claude-bin", default=None)
    parser.add_argument("--sum-api", default=None)
    args = parser.parse_args()
    if args.mcp_session and not args.mcp_tool:
        parser.error("--mcp-session requires at least one --mcp-tool")
    if args.profile and args.mcp_tool:
        parser.error("--mcp-tool requires --mcp-session")

    source_dir = Path(args.input).resolve()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    if args.mcp_session:
        try:
            artifact = extract(find_report(source_dir))
        except (RuntimeError, ValueError) as error:
            failure = {
                "status": "failed", "provider": "mcp",
                "profile": args.mcp_session, "source_identity": None,
                "generated_at": now(), "tables": [], "confirmed": 0,
                "contradicted": 0, "not_run": 0, "checks": [],
                "error": customer_source_error(str(error)),
                "technical_error": str(error),
            }
            (out / "source-findings.json").write_text(
                json.dumps(failure, indent=2) + "\n")
            print(f"sourcecheck: {error}", file=sys.stderr)
            return 2
        return run_mcp_source(
            artifact, out, session=args.mcp_session,
            approved_tool_names=args.mcp_tool, mcpc_path=args.mcpc,
            model=args.model, claude_bin=args.claude_bin)
    try:
        sum_api = resolve_sum_api(args.sum_api)
        artifact = extract(find_report(source_dir))
        tables = discover_tables(sum_api, args.profile, artifact.text)
        if not tables:
            raise RuntimeError(
                "the report table name did not match one visible table on this profile")
        log(f"live source {args.profile}: {', '.join(sorted(tables))}")
        snapshot_date = report_snapshot_date(artifact.text)
        if snapshot_date:
            log(f"report snapshot date: {snapshot_date.isoformat()}")
        log("planning headline and freshness checks")
        checks, runtime = plan_checks(
            artifact.text, tables, model=args.model, claude_bin=args.claude_bin,
            snapshot_date=snapshot_date)
        needs_freshness = report_requires_freshness(artifact.text)
        try:
            normalized = normalize_checks(checks, needs_freshness=needs_freshness)
        except ValueError:
            log("source plan omitted the required freshness check; retrying once")
            checks, runtime = plan_checks(
                artifact.text, tables, model=args.model,
                claude_bin=args.claude_bin, force_freshness=True,
                snapshot_date=snapshot_date)
            normalized = normalize_checks(checks, needs_freshness=needs_freshness)
        if needs_freshness and normalized and normalized[0] is not checks[0]:
            log("moved the freshness check to the first position")
        if not needs_freshness:
            discarded_freshness = len(checks) - len(normalized)
            if discarded_freshness:
                log(f"discarded {discarded_freshness} unclaimed freshness check(s)")
        checks = normalized
    except (RuntimeError, ValueError, subprocess.TimeoutExpired) as error:
        failure = {
            "status": "failed",
            "provider": "sum-api",
            "profile": args.profile,
            "generated_at": now(),
            "tables": sorted(tables) if "tables" in locals() else [],
            "confirmed": 0,
            "contradicted": 0,
            "not_run": 0,
            "checks": [],
            "error": customer_source_error(str(error)),
            "technical_error": str(error),
        }
        (out / "source-findings.json").write_text(
            json.dumps(failure, indent=2) + "\n")
        print(f"sourcecheck: {error}", file=sys.stderr)
        return 2
    if not checks:
        no_claims = {
            "status": "not_applicable",
            "provider": "sum-api",
            "profile": args.profile,
            "generated_at": now(),
            "tables": sorted(tables),
            "confirmed": 0,
            "contradicted": 0,
            "not_run": 0,
            "checks": [],
            "error": (runtime.get("uncheckable_reason")
                      or "This connected source could not check a material report claim."),
            "suggested_source": runtime.get("suggested_source"),
        }
        destination = out / "source-findings.json"
        destination.write_text(json.dumps(no_claims, indent=2) + "\n")
        log(f"source connected, but no report claim mapped to its columns → {destination}")
        return 0
    log(f"planner proposed {len(checks)} checks")

    normalized_report = re.sub(r"\s+", " ", artifact.text).casefold()
    results = []
    for check in checks:
        sql = str(check.get("sql", ""))
        checked_at = now()
        if not is_readonly_select(sql):
            results.append({**check, "verdict": "not_run",
                            "why": "not a single read-only SELECT",
                            "queried_at": checked_at})
            continue
        quote = re.sub(r"\s+", " ", str(check.get("quote", ""))).strip()
        if not quote or quote.casefold() not in normalized_report:
            results.append({**check, "verdict": "not_run",
                            "why": "quote not verbatim in visible report text",
                            "queried_at": checked_at})
            continue
        response = sql_query_with_retry(sum_api, args.profile, sql)
        if "error" in response:
            results.append({**check, "verdict": "not_run",
                            "why": response["error"][:300], "queried_at": checked_at})
            continue
        rows = rows_of(response)
        comparison = result_for_rows(
            check, rows, snapshot_date=snapshot_date, queried_at=checked_at)
        verdict = comparison["verdict"]
        results.append({**check, **comparison, "queried_at": checked_at})
        log(f"{check.get('id')}: {verdict}"
            + (f" ({', '.join(comparison.get('mismatches') or {})})"
               if comparison.get("mismatches") else ""))

    not_run_count = sum(result["verdict"] == "not_run" for result in results)
    summary = {
        "status": "partial" if not_run_count else "complete",
        "error": ("One or more live queries did not return a result."
                  if not_run_count else None),
        "profile": args.profile,
        "generated_at": now(),
        "report": {"path": artifact.path.name, "format": artifact.format,
                   "sha256": artifact.sha256, "extraction_method": artifact.method},
        "report_snapshot_date": snapshot_date.isoformat() if snapshot_date else None,
        "tables": sorted(tables),
        "confirmed": sum(result["verdict"] == "confirmed" for result in results),
        "contradicted": sum(result["verdict"] == "contradicted" for result in results),
        "changed_since_report": sum(
            result["verdict"] == "changed_since_report" for result in results),
        "matches_current_source": sum(
            result["verdict"] == "matches_current_source" for result in results),
        "not_run": not_run_count,
        "agent_runtime": runtime,
        "checks": results,
    }
    destination = out / "source-findings.json"
    destination.write_text(json.dumps(summary, indent=2) + "\n")
    log(f"{summary['confirmed']} confirmed · {summary['contradicted']} contradicted · "
        f"{summary['changed_since_report']} changed since report · "
        f"{summary['matches_current_source']} current matches · "
        f"{summary['not_run']} not run → {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
