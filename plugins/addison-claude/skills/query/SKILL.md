---
name: query
description: Answer a data question or run read-only SQL against Summation. Use for quick checks, tables, or open-ended questions.
argument-hint: <sql or data question> [--limit N]
---

# Summation Query

MCP only. Sign in first if needed (`whoami` / signin skill).

## Flow

1. Ground names: `/addison:catalog` or `search_tables` — never invent table names.  
2. **Open-ended business questions** (including “top N”, trends, “why”): prefer **`ask_analyst`** (Addison). Tell the user it’s working; answers often take a bit.  
3. **Explicit SQL** the user provided (or a simple lookup): **`run_query`** with an explicit limit (default 100; ask before very large pulls).  
4. Render a compact table; show row count and the SQL used when you ran SQL. Spot-check surprising results in plain language.

## Rules

- Prefer Addison for narrative analysis; SQL for precise, user-authored queries.  
- Read-only: don’t retry mutations.  
- Errors: plain language; permission issues ≠ “not signed in.”  
- No REST helper.
