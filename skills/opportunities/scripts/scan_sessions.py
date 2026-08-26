#!/usr/bin/env python3
"""Local-only scan of recent Claude Code / Codex sessions for Summation opportunity themes.

Privacy:
  - Reads only local session JSONL under ~/.claude/projects and ~/.codex/sessions
  - Never uploads, never network
  - Emits short theme hits + sample phrases (truncated), never full transcripts

Usage:
  python3 scan_sessions.py [--days 14] [--limit-sessions 20] [--source claude|codex|all]
                           [--project-substr PATH_FRAGMENT] [--json]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

CLAUDE_PROJECTS = Path.home() / ".claude" / "projects"
CODEX_SESSIONS = Path.home() / ".codex" / "sessions"

# Theme id → (label, regex patterns on user text)
THEME_SPECS: list[tuple[str, str, list[str]]] = [
    (
        "metrics_kpi",
        "Metrics, KPIs, or “why did the number move”",
        [
            r"\bkpi\b",
            r"\bmetric",
            r"\brevenue\b",
            r"\bchurn\b",
            r"\bconversion\b",
            r"\bfunnel\b",
            r"\bmrr\b",
            r"\barr\b",
            r"\bnps\b",
            r"\bwhy did\b",
            r"\bdropped\b",
            r"\bspiked\b",
            r"\byoy\b",
            r"\bwo?w\b",
            r"\bmom\b",
        ],
    ),
    (
        "sql_warehouse",
        "Ad-hoc SQL or warehouse / database work",
        [
            r"\bselect\b.+\bfrom\b",
            r"\bsql\b",
            r"\bsnowflake\b",
            r"\bbigquery\b",
            r"\bredshift\b",
            r"\bdatabricks\b",
            r"\bpostgres\b",
            r"\bmysql\b",
            r"\bduckdb\b",
            r"\bwarehouse\b",
            r"\bquery the\b",
        ],
    ),
    (
        "files_csv",
        "CSV / spreadsheet / file analysis",
        [
            r"\bcsv\b",
            r"\bxlsx?\b",
            r"\bspreadsheet\b",
            r"\bexcel\b",
            r"\bparquet\b",
            r"\bimport (the )?file\b",
            r"\bupload(ed)? (a |the )?(file|csv)\b",
        ],
    ),
    (
        "reports_narrative",
        "Board packs, status write-ups, or narrative analysis",
        [
            r"\breport\b",
            r"\bboard\b",
            r"\bexec(utive)? summary\b",
            r"\bweekly update\b",
            r"\bstatus update\b",
            r"\bwrite[- ]?up\b",
            r"\bnarrative\b",
            r"\bbrief(ing)?\b",
        ],
    ),
    (
        "recurring",
        "Recurring cadence (daily / weekly / Monday email)",
        [
            r"\bevery (monday|week|day|month)\b",
            r"\bweekly\b",
            r"\bdaily\b",
            r"\bschedule\b",
            r"\bcron\b",
            r"\brecurring\b",
            r"\bemail (me |this |the )?(report|update)\b",
        ],
    ),
    (
        "data_quality",
        "Data quality, freshness, or pipeline friction",
        [
            r"\bstale\b",
            r"\bfreshness\b",
            r"\bmissing (rows|data)\b",
            r"\bnulls?\b",
            r"\bpipeline\b",
            r"\betl\b",
            r"\bdata quality\b",
            r"\bduplicate\b",
        ],
    ),
    (
        "connect_source",
        "Connecting or exploring a data source",
        [
            r"\bconnect (to |my )?",
            r"\bdata source\b",
            r"\bconnector\b",
            r"\bneon\b",
            r"\brds\b",
            r"\bcloud sql\b",
        ],
    ),
]

THEME_RE = [
    (tid, label, re.compile("|".join(f"(?:{p})" for p in pats), re.I | re.S))
    for tid, label, pats in THEME_SPECS
]

SECRETISH = re.compile(
    r"(?i)(password|secret|api[_-]?key|bearer\s+[a-z0-9._\-]{12,}|sm_dls_|authorization:\s*\S+)"
)

# Skip system / agent-prompt dumps that dominate some sessions
SKIP_USER = re.compile(
    r"(?i)("
    r"^you are a |"
    r"^# phase 0|"
    r"your review persona|"
    r"system prompt|"
    r"<environment_context>|"
    r"<task-notification>|"
    r"# AGENTS\.md instructions|"
    r"Base directory for this skill:|"
    r"<INSTRUCTIONS>"
    r")"
)


def _truncate(text: str, n: int = 120) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= n:
        return text
    return text[: n - 1] + "…"


def _scrub(text: str) -> str:
    return SECRETISH.sub("[redacted]", text)


def _as_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                if item.get("type") in ("text", "input_text") and "text" in item:
                    parts.append(str(item["text"]))
                elif item.get("type") == "tool_result":
                    continue
                elif "content" in item:
                    parts.append(_as_text(item["content"]))
        return "\n".join(parts)
    if isinstance(content, dict):
        if "text" in content:
            return str(content["text"])
        if "content" in content:
            return _as_text(content["content"])
    return ""


def extract_user_texts_claude(obj: dict[str, Any]) -> Iterable[str]:
    if obj.get("type") != "user":
        return
    msg = obj.get("message")
    if isinstance(msg, dict) and msg.get("role") == "user":
        text = _as_text(msg.get("content"))
        if text.strip():
            yield text
    elif isinstance(msg, str) and msg.strip():
        yield msg


def extract_user_texts_codex(obj: dict[str, Any]) -> Iterable[str]:
    if obj.get("type") not in ("response_item", "event_msg"):
        return
    payload = obj.get("payload")
    if not isinstance(payload, dict):
        return
    if payload.get("type") == "user_message" and payload.get("message"):
        yield str(payload["message"])
        return
    if payload.get("role") == "user" or payload.get("type") == "message" and payload.get("role") == "user":
        text = _as_text(payload.get("content"))
        if text.strip():
            yield text


def iter_session_files(source: str) -> list[tuple[str, Path]]:
    out: list[tuple[str, Path]] = []
    if source in ("claude", "all") and CLAUDE_PROJECTS.is_dir():
        for path in CLAUDE_PROJECTS.rglob("*.jsonl"):
            if path.is_file():
                out.append(("claude", path))
    if source in ("codex", "all") and CODEX_SESSIONS.is_dir():
        for path in CODEX_SESSIONS.rglob("*.jsonl"):
            if path.is_file():
                out.append(("codex", path))
    return out


def session_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def scan_file(
    source: str,
    path: Path,
    *,
    max_user_turns: int,
) -> list[tuple[str, str, str]]:
    """Return list of (theme_id, theme_label, sample_phrase)."""
    hits: list[tuple[str, str, str]] = []
    seen_themes: set[str] = set()
    user_turns = 0
    extract = extract_user_texts_claude if source == "claude" else extract_user_texts_codex
    try:
        with path.open(encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                if user_turns >= max_user_turns:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(obj, dict):
                    continue
                for raw in extract(obj):
                    text = raw.strip()
                    if len(text) < 12:
                        continue
                    if SKIP_USER.search(text):
                        continue
                    if len(text) > 8000:
                        # Huge system dumps / diffs — skip for themes
                        continue
                    user_turns += 1
                    scrubbed = _scrub(text)
                    for tid, label, cre in THEME_RE:
                        if tid in seen_themes:
                            continue
                        if cre.search(scrubbed):
                            seen_themes.add(tid)
                            hits.append((tid, label, _truncate(scrubbed)))
                    if user_turns >= max_user_turns:
                        break
    except OSError:
        return []
    return hits


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan local IDE sessions for Summation opportunity themes.")
    parser.add_argument("--days", type=int, default=14, help="Only sessions modified in the last N days (default 14).")
    parser.add_argument("--limit-sessions", type=int, default=20, help="Max session files to open (default 20).")
    parser.add_argument(
        "--max-user-turns",
        type=int,
        default=40,
        help="Max user turns to read per session (default 40).",
    )
    parser.add_argument(
        "--source",
        choices=("claude", "codex", "all"),
        default="all",
        help="Which host session trees to scan.",
    )
    parser.add_argument(
        "--project-substr",
        default="",
        help="Prefer Claude project paths containing this substring (cwd fragment).",
    )
    parser.add_argument("--json", action="store_true", help="Machine-readable JSON on stdout.")
    args = parser.parse_args()

    now = time.time()
    cutoff = now - max(args.days, 0) * 86400
    files = iter_session_files(args.source)
    # Prefer project-scoped Claude sessions when a substr is given
    substr = (args.project_substr or "").strip()
    if substr:
        preferred = [(s, p) for s, p in files if substr in str(p)]
        others = [(s, p) for s, p in files if substr not in str(p)]
        files = preferred + others

    files = [(s, p) for s, p in files if session_mtime(p) >= cutoff]
    files.sort(key=lambda sp: session_mtime(sp[1]), reverse=True)
    files = files[: max(args.limit_sessions, 0)]

    theme_counts: dict[str, int] = defaultdict(int)
    theme_labels: dict[str, str] = {}
    samples: dict[str, list[str]] = defaultdict(list)
    sessions_scanned = 0
    sessions_with_hits = 0

    for source, path in files:
        sessions_scanned += 1
        hits = scan_file(source, path, max_user_turns=args.max_user_turns)
        if not hits:
            continue
        sessions_with_hits += 1
        for tid, label, sample in hits:
            theme_counts[tid] += 1
            theme_labels[tid] = label
            if len(samples[tid]) < 3 and sample not in samples[tid]:
                samples[tid].append(sample)

    ranked = sorted(theme_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    themes = [
        {
            "id": tid,
            "label": theme_labels[tid],
            "session_hits": count,
            "samples": samples[tid],
            "suggested_skills": _skills_for(tid),
        }
        for tid, count in ranked
    ]

    payload = {
        "privacy": "local_only",
        "days": args.days,
        "source": args.source,
        "sessions_considered": len(files),
        "sessions_scanned": sessions_scanned,
        "sessions_with_theme_hits": sessions_with_hits,
        "claude_projects_dir": str(CLAUDE_PROJECTS),
        "codex_sessions_dir": str(CODEX_SESSIONS),
        "themes": themes,
        "note": (
            "Themes are heuristic keyword matches on recent user turns. "
            "Not a full transcript. Nothing was uploaded."
        ),
    }

    if args.json:
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(f"Local scan: {sessions_scanned} sessions (last {args.days}d, source={args.source})")
        print(f"Sessions with theme hits: {sessions_with_hits}")
        if not themes:
            print("No clear Summation-shaped themes found in the scan window.")
            print("Still suggest catalog explore, connect, or a first report from live data.")
            return 0
        print("Themes (strongest first):")
        for t in themes:
            print(f"  - [{t['session_hits']} session(s)] {t['label']}")
            print(f"    skills: {', '.join(t['suggested_skills'])}")
            for s in t["samples"][:2]:
                print(f"    e.g. “{s}”")
        print("Nothing was uploaded. Scan stayed on this machine.")
    return 0


def _skills_for(theme_id: str) -> list[str]:
    return {
        "metrics_kpi": ["query", "report"],
        "sql_warehouse": ["catalog", "query", "connect"],
        "files_csv": ["connect", "catalog", "query"],
        "reports_narrative": ["report", "verify"],
        "recurring": ["schedule", "report"],
        "data_quality": ["catalog", "query", "diagnose"],
        "connect_source": ["connect", "start"],
    }.get(theme_id, ["start", "catalog", "query"])


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BrokenPipeError:
        sys.exit(0)
