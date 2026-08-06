---
name: api
description: Use Summation through the hosted summation MCP server and Addison skills. Use when users ask to inspect or operate Summation data, projects, reports, chats, files, or MCP auth.
---

# Summation (MCP-native)

All data operations go through the hosted **`summation` MCP server**. Auth is Codex OAuth against that server (browser sign-in). Do **not** call sum-api with a local helper for day-to-day work, and do **not** invent REST paths in chat.

**Default MCP URL:** `https://mcp.summation.com/mcp` (plugin `.mcp.json`).

## Core workflow

1. Ensure auth: call **`whoami`**. If unauthenticated, hand off to the `signin` skill.
2. Prefer a **domain skill** when the task matches one (`start`, `report`, `validate`, `query`, `catalog`, `schedule`, `connect`).
3. Otherwise call the right **MCP tools** directly (list below). Prefer task-shaped tools over inventing multi-step REST.
4. On auth failure, re-run `signin` — never ask for tokens in chat.

## MCP tools (curated)

Identity / projects: `whoami`, `get_org`, `list_projects`, `get_default_project`, `get_project`, `create_project`

Analyst: `ask_analyst`, `reply_to_analyst`, `list_conversations`, `get_conversation`, `list_chat_models`

Sources: `list_data_connections`, `list_connection_datasets`, `browse_connection_resources`, `attach_connection_datasets`, `test_data_connection`, `snapshot_dataset`, `list_snapshot_runs`, `list_app_connections`, `browse_app_catalog`

Tables / views / query: `search_tables`, `get_table_schema`, `preview_table_data`, `get_table_lineage`, `create_calc_table`, `materialize_table`, `sync_table`, `append_table_rows`, `search_views`, `get_view`, `preview_view_data`, `run_query`

Files: `list_files`, `download_file`, `upload_file`, `request_file_upload`, `finalize_file_upload`, `import_file_to_table`

Catalog / reports / playbooks / schedules: `list_catalog_entries`, `attach_catalog_entry`, `start_report`, `list_reports`, `get_report_status`, `export_report`, `validate_report`, `list_playbooks`, `get_playbook`, `list_schedules`, `get_schedule`, `list_schedule_runs`, `create_schedule`

Tool names and shapes come from the live MCP server — if a name differs slightly, use the server’s list, not this doc as gospel.

## Client-side behaviors

- **Long tools return one buffered result:** `ask_analyst`, `start_report`, `validate_report`, `import_file_to_table` (~15–60s). Tell the user Addison is working; do not treat silence as failure before ~120s.
- **Auth errors** → `$addison-signin` (host re-auth).
- **`get_view` / `preview_view_data`** can 404 on ids from `search_views` (known list/show split) — fall back to tables tools.
- **`create_schedule`** emails people — confirm recipients + cadence (with timezone) verbatim before calling.
- **Secrets never in tool args.** Connection passwords use the `connect` skill (webapp or local-file path), never MCP arguments.

## Auth

See the sibling `signin` / `signout` skills and `references/auth.md`. Summary:

- Plugin ships headerless `.mcp.json` for `summation`.
- Codex stores the OAuth/session token; skills never read or write `sm_dls_…` files for the happy path.
- **External** (default): one env, no env/tenant prompts.
- **Internal** (`ADDISON_PLUGIN_INTERNAL=1` in the launch shell): signin asks **environment** (prod/staging/sandbox allowlist) and **tenant** guidance (web-app org + re-auth).
- Do not register a user-scope MCP entry with an `Authorization` header — that fights OAuth.

## Safety rules

- Destructive or outward-facing actions (email schedules, deletes) are confirmation-gated.
- Prefer list/show before mutate.
- Preserve org/project context from `whoami` / project tools — never trust caller-supplied org headers.
- On failure, quote any `request_id` from the tool error.

## Legacy helper (not for normal use)

`scripts/sum_api.py` remains in-tree only for rare local recovery (e.g. secret-file connection create when MCP cannot carry secrets). **Do not use it for queries, reports, catalog, schedules, or auth.** Prefer MCP tools and the domain skills.
