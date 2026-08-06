---
name: api
description: Use Summation through the hosted summation MCP server and Addison skills. Product questions, data work, reports, connections, and auth.
---

# Summation (MCP-native)

All day-to-day data work goes through the hosted **`summation` MCP server** and domain skills. Browser sign-in owns auth. Do **not** call sum-api or invent REST for normal work.

**Default MCP:** `https://mcp.summation.com/mcp`

## Before you answer “what’s supported?”

1. Read **`references/product.md`** (connectors + feature map).  
2. If still unsure, fetch **`https://docs.summation.com/llms.txt`**, then the linked page.  
3. Never treat a bad URL, marketing homepage, or truncated OpenAPI as “unsupported.” **Postgres is supported** (and the full list in product.md).

## Core workflow

1. Auth: **`whoami`**. If needed → **signin** skill.  
2. Prefer a domain skill: `start`, `report`, `validate`, `query`, `catalog`, `schedule`, `connect`, `diagnose`.  
3. Else use MCP tools (below). Speak in outcomes to the user.  
4. Auth errors → signin; never ask for tokens in chat.

## MCP tools (curated)

Identity / projects: `whoami`, `get_org`, `list_projects`, `get_default_project`, `get_project`, `create_project`

Analyst: `ask_analyst`, `reply_to_analyst`, `list_conversations`, `get_conversation`, `list_chat_models`

Sources: `list_data_connections`, `list_connection_datasets`, `browse_connection_resources`, `attach_connection_datasets`, `test_data_connection`, `snapshot_dataset`, `list_snapshot_runs`, `list_app_connections`, `browse_app_catalog`

Tables / views / query: `search_tables`, `get_table_schema`, `preview_table_data`, `get_table_lineage`, `create_calc_table`, `materialize_table`, `sync_table`, `append_table_rows`, `search_views`, `get_view`, `preview_view_data`, `run_query`

Files: `list_files`, `download_file`, `upload_file`, `request_file_upload`, `finalize_file_upload`, `import_file_to_table`

Catalog / reports / playbooks / schedules: `list_catalog_entries`, `attach_catalog_entry`, `start_report`, `list_reports`, `get_report_status`, `export_report`, `validate_report`, `list_playbooks`, `get_playbook`, `list_schedules`, `get_schedule`, `list_schedule_runs`, `create_schedule`

Prefer the live server’s tool list if names drift slightly.

## Client behaviors (required)

- **Long tools** (`ask_analyst`, `start_report`, `validate_report`, `import_file_to_table`): tell the user you’re working; **reports can take several minutes** — give brief progress every ~30–45s while waiting; do not declare failure at 120s if status is still running (wait up to ~7–10 minutes or until status is terminal).  
- **Auth errors** → signin.  
- **Views** may 404 on ids from search — fall back to tables.  
- **`create_schedule`** emails people — confirm recipients + cadence (with timezone) first.  
- **Secrets:** never in tool args; **connect** skill + web app.  
- **Attach datasets:** always set human-readable **`name`** (table name). Never leave auto `*_dataset_N` names.  
- **Success:** verify with list/test tools before telling the user it’s done. Never trust intermediate “Added…” stream text alone.  
- **User chat:** no OpenAPI dumps, path lists, or key-guessing experiments.

## Auth summary

See `signin` / `signout` and `references/auth.md`. Headerless plugin MCP; host OAuth. Do not re-register with an Authorization header.

## Safety

- Confirm email schedules and destructive actions.  
- Prefer list before mutate.  
- Preserve org/project from `whoami` / project tools.  
- On hard failures, you may mention a `request_id` if present (for support) — still explain in plain language.

## Legacy helper

`scripts/sum_api.py` is not for normal customer flows. Prefer MCP + domain skills.
