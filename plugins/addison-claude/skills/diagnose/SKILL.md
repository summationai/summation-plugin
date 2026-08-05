---
name: diagnose
description: Diagnose Summation MCP connectivity and auth. Use when Summation tools fail, auth seems stale, or the user asks whether Summation is set up correctly.
---

# Summation Diagnose

Auth and data plane are the hosted **`summation` MCP server**. Diagnose with MCP tools, not OpenAPI scripts.

## 0. Mode

```bash
printf '%s' "${ADDISON_PLUGIN_INTERNAL:-}"
```

- Internal if `1` / `true` / `yes` / `on` → expect env selection at sign-in; report which env URL is configured if you can see it (`claude mcp get summation`, redact secrets).
- Otherwise **external** → single plugin default; no env questions.

## 1. Auth + identity

Call **`whoami`** on **`summation`**.

| Result | Meaning |
|---|---|
| Identity + org + scopes | Auth OK. Continue. |
| Needs authentication / 401 | `/addison:signin`. |
| Server not found | Plugin MCP not loaded — enable **addison**, restart; internal may need the env URL re-registered. |

## 2. Environment card (when `whoami` works)

Call as available: `get_org`, `list_projects`, `get_default_project`, `list_data_connections`, `search_tables`.

Render a short card:

- **Mode:** external | internal  
- **Env:** (internal) prod / staging / sandbox if known from MCP URL; (external) plugin default  
- **Tenant/org:** from `whoami` / `get_org`  
- Projects, connections, sample tables  
- 2–3 sample questions against real names  

## 3. Auth mismatch (legacy install)

If user-scope `summation` has an `Authorization` header (old device-login bridge):

1. Explain the plugin uses headerless OAuth.
2. `claude mcp remove summation -s user`
3. `/addison:signin` (internal will re-ask env).

## Interpreting failures

- **401** → `/addison:signin` (internal: confirm env + web-app org first).
- **403** → wrong org/role for this env; switch org on web app and re-auth, or pick another env (internal).
- **Empty connections** → auth fine; `/addison:connect` or `/addison:start`.
- Long tools (`ask_analyst`, reports): wait ~120s before declaring failure.
- Surface any `request_id` from tool errors.
