---
name: api
description: Use Summation through sumcli (preferred when a shell is available) or the hosted summation MCP server (shell-less fallback), plus Summation skills. Product questions, data work, reports, connections, and auth.
metadata:
  short-description: Work with Summation via sumcli or MCP
---

# Summation

When a shell is available, day-to-day data work goes through **sumcli** (full sum-api contract — see `references/sumcli.md`). Shell-less hosts (Claude Desktop, sandboxes) use the hosted **`summation` MCP server** (curated subset) and domain skills. Browser sign-in owns MCP auth; `sumcli auth login` owns the CLI session. Do **not** invent REST for normal work.

**Default MCP (fallback):** `https://mcp.summation.com/mcp`

## Before you answer “what’s supported?”

1. **Fetch `https://docs.summation.com/llms.txt`** (live product map — do not rely on a baked-in list).  
2. Open the linked doc for that feature or connector.  
3. See **`references/product.md`** for how to use the index and plugin skill routing.  
4. Never invent “unsupported” from a failed fetch, wrong URL, homepage marketing, or truncated OpenAPI.

## Core workflow

1. Pick the surface: shell available → **sumcli**; shell-less → MCP.  
2. Auth: CLI → `sumcli auth whoami` (401 → `sumcli auth login`); MCP → **`whoami`** (if needed → **signin** skill).  
3. Prefer a domain skill: `start`, `opportunities`, `report`, `validate`, `query`, `catalog`, `schedule`, `connect`, `diagnose`.  
4. Else: sumcli commands (discover live: `sumcli | jq '.result.resources'`) or MCP tools (below). Speak in outcomes to the user.  
5. Auth errors → `sumcli auth login` / signin; never ask for tokens in chat.

## MCP tools (curated — shell-less fallback)

Identity / projects: `whoami`, `get_org`, `list_projects`, `get_default_project`, `get_project`, `create_project`

Analyst: `ask_analyst`, `reply_to_analyst`, `list_conversations`, `get_conversation`, `list_chat_models`

Sources: `list_data_connections`, `list_connection_datasets`, `browse_connection_resources`, `attach_connection_datasets`, `test_data_connection`, `snapshot_dataset`, `list_snapshot_runs`, `list_app_connections`, `browse_app_catalog`

Tables / views / query: `search_tables`, `get_table_schema`, `preview_table_data`, `get_table_lineage`, `create_calc_table`, `materialize_table`, `sync_table`, `append_table_rows`, `search_views`, `get_view`, `preview_view_data`, `run_query`

Files: `list_files`, `download_file`, `upload_file`, `request_file_upload`, `finalize_file_upload`, `import_file_to_table`

Catalog / reports / playbooks / schedules: `list_catalog_entries`, `attach_catalog_entry`, `start_report`, `list_reports`, `get_report_status`, `export_report`, `validate_report`, `list_playbooks`, `get_playbook`, `list_schedules`, `get_schedule`, `list_schedule_runs`, `create_schedule` — plus any create/update/detach tools the live server exposes (use them when present).

Prefer the **live server’s tool list** over this doc if names differ.

## Client behaviors (required)

- **Long tools** (`ask_analyst`, `start_report`, `validate_report`, `import_file_to_table`): tell the user you’re working; **reports can take a few minutes** — brief progress every ~30–45s until status is terminal.  
- **Auth errors** → CLI: `sumcli auth login`; MCP: signin.  
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

## sumcli

When a shell is available, **sumcli is the preferred surface**; MCP is the fallback for shell-less hosts (Claude Desktop, sandboxes) and anywhere the CLI cannot run. The CLI exposes the full sum-api contract; the hosted MCP is a curated subset — all deletes, connection management, schedule and catalog updates, ingestion batches, and the direct table-import pipeline are CLI-only. Needs **sumcli ≥ 0.1.3** (see `references/sumcli.md`). Newer CLIs are always compatible — `sumcli update` to PyPI latest.

**Install on first need.** If `sumcli` is missing or too old when a CLI call is due, ask the user and **wait for a yes** before running the bootstrap — the same consent bar as `SUMCLI_AUTO_INSTALL`. On no, fall back to MCP for that request. SessionStart only nudges; it never installs. First CLI use also needs `sumcli auth login` (browser device-code) — MCP's host OAuth and the CLI session are separate credentials.

Known import asymmetry: MCP `import_file_to_table` uses the gated agent-workflow route (409 `feature_not_enabled` on tenants without modelgen gates); `sumcli tables import` uses the ungated direct pipeline, which has no MCP equivalent. Imports go through sumcli. A 403 with tool-profile text is a Connected Apps problem — not CLI-recoverable; tell the user.

## Legacy helper

`scripts/sum_api.py` is **not** for normal customer flows. Prefer sumcli / MCP + domain skills (`signin`, `diagnose`, …).

If you must run the helper (internal/debug only), **never** use relative `../api/scripts/sum_api.py` — hosts often mount skills as `summation:api` / `summation:doctor`, so `../api` resolves outside the plugin and fails. Use the plugin root:

```bash
python3 "${PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/skills/api/scripts/sum_api.py" doctor
```

If both `PLUGIN_ROOT` and `CLAUDE_PLUGIN_ROOT` are unset, resolve from the installed package path the host shows for this skill — still under `…/skills/api/scripts/sum_api.py`, not `…/plugins/api/…`.
