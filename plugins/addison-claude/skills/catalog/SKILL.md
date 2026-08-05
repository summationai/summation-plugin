---
name: catalog
description: Search and describe Summation tables, views, and catalog metadata. Use when the user asks what data exists, wants schemas or column details, or before writing any SQL.
argument-hint: "[search term]"
---

# Summation Catalog

Discover what data exists before touching it. **MCP tools only.**

## Flow

1. **Search:** `search_tables` (and `search_views` if relevant) with the user’s term.
2. **Detail:** for a chosen table — `get_table_schema`, optional `preview_table_data` (limit ≤ 5), optional `get_table_lineage`. For views — `get_view` / `preview_view_data` (see caveat).
3. **Project catalog:** `list_catalog_entries` when the question is “what’s in this project?”
4. Render compact schema cards: name, id, columns/types, one-line description. Group tables vs views.

## Rules

- With huge inventories, never dump everything — show matches + totals and ask to narrow.
- Sample peeks stay small (`limit` ≤ 5); analysis is `/addison:query` or `ask_analyst`.
- **Caveat:** `get_view` / `preview_view_data` can 404 on ids from `search_views` — fall back to tables tools.
- Suggest next steps: `/addison:query` or `/addison:report`.
- No REST helper for this skill.
