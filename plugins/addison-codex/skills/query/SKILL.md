---
name: query
description: Answer a data question or run read-only SQL against Summation. Use for quick checks, tables, or open-ended questions.
---

# Summation Query

MCP only. Sign in first if needed (`whoami` / signin skill).

## Flow

1. Ground names: `$addison-catalog` or `search_tables` — never invent table names.  
2. **Open-ended / ranking / “top N” business questions:** prefer **`ask_analyst`** (Addison). Tell the user it’s working; answers often take 15–60s+.  
3. **Explicit SQL** the user provided: **`run_query`** with an explicit limit (default 100; ask before very large pulls).  
4. Render a compact table; show row count and the SQL used when you ran SQL.

## Ranking / ORDER BY caveat

Until the platform reliably preserves sort order on limited queries, **do not treat `ORDER BY … LIMIT` SQL as a trustworthy “top N”** without a cross-check (e.g. max/min aggregate, or prefer Addison). For “top customers / largest / worst,” prefer **`ask_analyst`** or rank with window functions in a way that doesn’t depend on discarded outer order — and still sanity-check surprising results.

## Rules

- Read-only: don’t retry mutations.  
- Errors: plain language; role/permission ≠ “not signed in.”  
- No REST helper.
