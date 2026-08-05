---
name: diagnose
description: Diagnose Summation MCP connectivity and auth. Use when Summation tools fail, auth seems stale, or the user asks whether Summation is set up correctly.
---

# Summation Diagnose

Auth and data plane are the hosted **`summation` MCP server**. Diagnose with MCP tools, not OpenAPI scripts.

## Flow

### 1. Auth + identity

Call **`whoami`**.

| Result | Meaning |
|---|---|
| Identity + org + scopes | Auth OK. Continue to environment map. |
| Needs authentication / 401 | Hand off to `$addison-signin`. |
| Server not found / tools missing | Plugin MCP entry not loaded — enable **addison**, restart Codex, confirm `/mcp` lists `summation`. |

### 2. Environment card (when `whoami` works)

Call, in order (skip gracefully if a tool errors):

1. **`get_org`** — org name
2. **`list_projects`** — count + names
3. **`get_default_project`** — default project id/name
4. **`list_data_connections`** — connections
5. **`search_tables`** (broad or empty query as the tool allows) — table signal
6. **`list_app_connections`** if relevant

Render a short card: who you are, org, project count, connection count, sample table names, and 2–3 questions that would work against those names.

### 3. Auth mismatch (legacy install)

If the user has a **user-scope** `summation` entry with an `Authorization` header (old device-login bridge) and tools fail:

1. Explain the plugin now uses headerless OAuth.
2. Remove the user override: `claude mcp remove summation -s user`
3. Reload so the plugin `.mcp.json` applies, then `$addison-signin`.

## Interpreting failures

- **401 / auth errors** → re-run `$addison-signin` (host browser auth), not a password paste.
- **403** → signed in but lacking scope/role; report tool name + error body; user may need a different org or grant.
- **Empty connections / zero datasets** → auth is fine; hand off to `$addison-connect` or `$addison-start` discovery gates.
- **Timeouts on `ask_analyst` / `start_report` / `validate_report`** → long buffered tools (15–60s+); wait ~120s before declaring failure.
- Always surface any `request_id` from tool error payloads when present.
