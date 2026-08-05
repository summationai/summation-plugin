---
name: query
description: Run a read-only SQL query against Summation data and render the result as a table. Use for quick data questions, sanity checks, or when the user provides SQL or asks something answerable with one query.
argument-hint: <sql or data question> [--limit N]
---

# Summation Query

Use the hosted **`summation` MCP** tools only. Auth via `/addison:signin` if needed (`whoami` first).

## Flow

1. If the user gave a question rather than SQL, ground it first: `/addison:catalog <term>` or MCP `search_tables` — never guess table names.
2. For **open-ended data questions**, prefer **`ask_analyst`** (buffered, ~15–60s; tell the user Addison is working; wait ~120s before failing).
3. For **explicit SQL**, call **`run_query`** with the SQL, an explicit `limit` (default 100, ask before >1000, max per tool rules), and a reasonable timeout.
4. Render a compact markdown table. State row count and whether results were truncated. Show the executed SQL for spot-checking.

## Rules

- Read-only semantics: mutations are rejected — say so, don’t retry as writes.
- On error, surface tool error text and any `request_id`. A role/permission message means the tenant lacks query roles — not “broken auth.”
- No REST helper / `sum_api.py` for this skill.
