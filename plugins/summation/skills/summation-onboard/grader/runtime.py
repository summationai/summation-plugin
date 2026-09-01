"""Runtime discovery and structured agent execution for the demo grader."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess


def _unique(paths):
    seen = set()
    for raw in paths:
        if not raw:
            continue
        path = str(Path(raw).expanduser())
        if path not in seen:
            seen.add(path)
            yield path


def resolve_claude(explicit: str | None = None) -> str:
    """Choose a current Claude Code binary instead of trusting PATH order."""
    candidates = _unique((
        explicit,
        os.environ.get("SUMMATION_GRADE_CLAUDE_BIN"),
        Path.home() / ".local/bin/claude",
        shutil.which("claude"),
    ))
    rejected = []
    for candidate in candidates:
        path = Path(candidate)
        if not path.is_file() or not os.access(path, os.X_OK):
            continue
        probe = subprocess.run(
            [str(path), "--version"], capture_output=True, text=True, timeout=10)
        version = (probe.stdout + probe.stderr).strip()
        major_match = re.search(r"\b(\d+)\.", version)
        if probe.returncode == 0 and major_match and int(major_match.group(1)) >= 2:
            return str(path)
        rejected.append(f"{path} ({version or 'version probe failed'})")
    detail = "; ".join(rejected) or "no executable found"
    raise RuntimeError(
        "Claude Code 2.x is required for structured grading output; "
        f"checked: {detail}. Set SUMMATION_GRADE_CLAUDE_BIN to override.")


def _json_after_noise(text: str) -> dict:
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            value, _ = decoder.raw_decode(text[match.start():])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError(f"no JSON object in output: {text[:240]}")


def _result_envelope(text: str) -> dict:
    """Accept Claude Code's legacy object or current event-array JSON output."""
    stripped = text.strip()
    try:
        output = json.loads(stripped)
    except json.JSONDecodeError:
        # Some installations print a non-JSON status line before the payload.
        decoder = json.JSONDecoder()
        output = None
        for match in re.finditer(r"[\[{]", stripped):
            try:
                output, _ = decoder.raw_decode(stripped[match.start():])
                break
            except json.JSONDecodeError:
                continue
        if output is None:
            raise ValueError(f"no Claude JSON envelope in output: {text[:240]}")
    if isinstance(output, dict):
        return output
    if isinstance(output, list):
        candidates = [item for item in output if isinstance(item, dict)
                      and (item.get("type") == "result" or "result" in item
                           or "structured_output" in item)]
        if candidates:
            return candidates[-1]
    raise ValueError("Claude JSON output contains no result envelope")


def run_claude_json(prompt: str, *, model: str | None, timeout: int = 240,
                    claude_bin: str | None = None,
                    schema: dict | None = None) -> tuple[dict, dict]:
    """Run one fresh Claude process and return its JSON answer plus run metadata."""
    binary = resolve_claude(claude_bin)
    # This verifier reads prompt text only. Disable tools, plugins, skills, MCP,
    # Chrome, and persistence so a grade cannot mutate the workspace or call an
    # unrelated connected service.
    cmd = [
        binary, "-p", "--output-format", "json",
        "--tools", "", "--disable-slash-commands",
        "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
        "--setting-sources", "", "--no-session-persistence", "--no-chrome",
    ]
    budget = os.environ.get("SUMMATION_GRADE_MAX_BUDGET_USD", "").strip()
    if budget:
        cmd += ["--max-budget-usd", budget]
    if schema:
        cmd += ["--json-schema", json.dumps(schema, separators=(",", ":"))]
    if model:
        cmd += ["--model", model]
    result = subprocess.run(
        cmd, input=prompt, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"agent process failed: {detail[-800:] or 'no diagnostic'}")
    envelope = _result_envelope(result.stdout)
    if envelope.get("is_error"):
        raise RuntimeError(f"agent returned an error: {envelope.get('result')}")
    structured = envelope.get("structured_output")
    if isinstance(structured, dict):
        payload = structured
    else:
        answer = envelope.get("result")
        if not isinstance(answer, str):
            raise RuntimeError("agent JSON envelope has no structured output or string result")
        answer = re.sub(r"^```(?:json)?\s*|\s*```$", "", answer.strip(), flags=re.I)
        payload = _json_after_noise(answer)
    meta = {
        "claude_bin": binary,
        "session_id": envelope.get("session_id"),
        "duration_ms": envelope.get("duration_ms"),
        "num_turns": envelope.get("num_turns"),
        "isolated": True,
    }
    return payload, meta


def resolve_sum_api(explicit: str | None = None) -> Path:
    candidates = _unique((
        explicit,
        os.environ.get("SUMMATION_GRADE_SUM_API"),
        Path.home() / ".claude/skills/sum-api/scripts/sum_api.py",
        Path.home() / ".codex/skills/sum-api/scripts/sum_api.py",
    ))
    for candidate in candidates:
        path = Path(candidate)
        if path.is_file():
            return path
    raise RuntimeError(
        "sum-api helper not found. Pass --sum-api or set SUMMATION_GRADE_SUM_API.")
