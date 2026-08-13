---
name: api
description: Use Summation through the hosted summation MCP server and Summation skills. Product questions, data work, reports, connections, and auth.
metadata:
  short-description: Work with Summation via MCP
---

# Summation (MCP-native)

All day-to-day data work goes through the hosted **`summation` MCP server** and domain skills. Browser sign-in owns auth. Do **not** call sum-api or invent REST for normal work.

**Default MCP:** `https://mcp.summation.com/mcp`

## Before you answer “what’s supported?”

1. **Fetch `https://docs.summation.com/llms.txt`** (live product map — do not rely on a baked-in list).  
2. Open the linked doc for that feature or connector.  
3. See **`references/product.md`** for how to use the index and plugin skill routing.  
4. Never invent “unsupported” from a failed fetch, wrong URL, homepage marketing, or truncated OpenAPI.

## Core workflow

1. Auth: **`whoami`**. If needed → **signin** skill.  
2. Prefer a domain skill: `start`, `opportunities`, `report`, `validate`, `query`, `catalog`, `schedule`, `connect`, `diagnose`.  
3. Else use MCP tools (below). Speak in outcomes to the user.  
4. Auth errors → signin; never ask for tokens in chat.

## MCP tools (curated)

Identity / projects: `whoami`, `get_org`, `list_projects`, `get_default_project`, `get_project`, `create_project`

Analyst: `ask_analyst`, `reply_to_analyst`, `list_conversations`, `get_conversation`, `list_chat_models`

Sources: `list_data_connections`, `list_connection_datasets`, `browse_connection_resources`, `attach_connection_datasets`, `test_data_connection`, `snapshot_dataset`, `list_snapshot_runs`, `list_app_connections`, `browse_app_catalog`

Tables / views / query: `search_tables`, `get_table_schema`, `preview_table_data`, `get_table_lineage`, `create_calc_table`, `materialize_table`, `sync_table`, `append_table_rows`, `search_views`, `get_view`, `preview_view_data`, `run_query`

Files: `list_files`, `download_file`, `upload_file`, `request_file_upload`, `finalize_file_upload`, `import_file_to_table`

Catalog / reports / playbooks / schedules: `list_catalog_entries`, `attach_catalog_entry`, `start_report`, `list_reports`, `get_report_status`, `export_report`, `validate_report`, `list_playbooks`, `get_playbook`, `list_schedules`, `get_schedule`, `list_schedule_runs`, `create_schedule` — plus any create/update/detach tools the live server exposes (use them when present).

Prefer the **live server’s tool list** over this doc if names differ.

## Client behaviors (required)

- **Long tools** (`ask_analyst`, `start_report`, `validate_report`, `import_file_to_table`): tell the user you’re working; **reports can take a few minutes** — brief progress every ~30–45s until status is terminal.  
- **Auth errors** → signin.  
- **Views** may 404 on ids from search — fall back to tables.  
- **Schedules** that email people — confirm recipients + cadence (with timezone) first.  
- **Secrets:** never in tool args or chat; **connect** skill + web app for passwords.  
- **Attach datasets:** always set human-readable **`name`** (table name). Never leave auto `*_dataset_N` names.  
- **Success:** verify with list/test/export before telling the user it’s done.  
- **User chat:** product language only — no OpenAPI dumps, path lists, or key-guessing experiments.

## Auth summary

See `signin` / `signout` and `references/auth.md`. Headerless plugin MCP; host OAuth. Do not re-register with an Authorization header.

## Safety

- Confirm email schedules and destructive actions.  
- Prefer list before mutate.  
- Preserve org/project from `whoami` / project tools.  
- On hard failures, you may mention a `request_id` if present (for support) — still explain in plain language.

## Legacy helper

`scripts/sum_api.py` is **not** for normal customer flows. Prefer MCP + domain skills (`signin`, `diagnose`, …).

If you must run the helper (internal/debug only), **never** use relative `../api/scripts/sum_api.py` — hosts often mount skills as `summation:api` / `summation:doctor`, so `../api` resolves outside the plugin and fails. Use the plugin root:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/api/scripts/sum_api.py" doctor
```

If `CLAUDE_PLUGIN_ROOT` is unset, resolve from the installed package path the host shows for this skill — still under `…/skills/api/scripts/sum_api.py`, not `…/plugins/api/…`.
