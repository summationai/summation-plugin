---
name: query
description: "Answer a data question or run read-only SQL against Summation. Use for quick checks, tables, or open-ended questions."
---

# Summation Query

MCP only. Sign in first if needed (`whoami` / signin skill).

## Flow

1. Ground names: `$summation-catalog` or `search_tables` — never invent table names.  
2. **Open-ended business questions** (including “top N”, trends, “why”): prefer **`ask_analyst`**. Tell the user it’s working; answers often take a bit.  
3. **Explicit SQL** the user provided (or a simple lookup): **`run_query`** with an explicit limit (default 100; ask before very large pulls).  
4. Render a compact table; show row count and the SQL used when you ran SQL. Spot-check surprising results in plain language.

## Rules

- Prefer the analyst (`ask_analyst`) for narrative analysis; SQL for precise, user-authored queries.  
- **Ranked / top-N SQL** needs `ORDER BY`. Without it, `LIMIT N` is not “top N” — add an order (with consent) or say the rows are unordered, not a ranking.  
- **Truncation:** if the result row count equals the limit (default 100), say the result may be truncated and offer a higher limit or a tighter filter. Never present a capped pull as the full set.  
- Read-only: don’t retry mutations.  
- Errors: plain language; permission issues ≠ “not signed in.”  
- No REST helper.
