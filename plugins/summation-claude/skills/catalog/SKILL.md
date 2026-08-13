---
name: catalog
description: Search and describe Summation tables, views, and catalog metadata. Use when the user asks what data exists or before writing SQL.
argument-hint: "[search term]"
---

# Summation Catalog

MCP only. Show **human-readable names** first.

## Flow

1. **Search:** `search_tables` / `search_views` as needed.  
2. **Detail:** `get_table_schema`, optional small `preview_table_data` (≤ 5 rows), lineage if useful. Views: `get_view` / preview (may 404 — fall back to tables).  
3. **Project:** `list_catalog_entries` when asking “what’s in this project?”  
4. Present compact cards: **friendly name**, columns/types, one-line description.

## Rules

- Huge lists: show matches + totals; ask to narrow.  
- Previews small; deep analysis → query / report.  
- If names look like `…_dataset_N`, offer to re-attach with proper names via **connect** / attach flow.  
- Suggest next: ask a question, report, or connect more data.  
- No REST helper. User-facing text stays non-technical.
