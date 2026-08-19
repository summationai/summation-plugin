---
name: diagnose
description: Check whether Summation is connected and what data is visible. Use when tools fail, sign-in seems broken, or the user asks if setup is OK.
---

# Summation Diagnose

Give a **plain-language health check** for customers and data scientists — not an API essay.

## 1. Identity

Call **`whoami`** on **`summation`**.

| Result | What to tell the user |
|---|---|
| Identity + org | “You’re signed in as … in org …” |
| Needs sign-in / 401 | Hand off to the `signin` skill |
| Tools missing | Enable/reload the **summation** plugin and restart the host |

## 2. What’s visible

As available: `get_org`, `list_projects`, `get_default_project`, `list_data_connections`, `list_connection_datasets` / `search_tables`.

Short card:

- Who / org  
- Connections (friendly names)  
- Tables ready for analysis (friendly names)  
- 2–3 sample questions that fit **those** tables  

If empty: “You’re signed in, but there’s no business data yet” → the `connect` skill or Connections in the web app.

## 3. Interpreting problems (user language)

- **Can’t authenticate** → sign in again in the browser.  
- **Signed in but no data** → connect a source in Summation, then attach tables with clear names.  
- **Permission denied** → their role/org may not allow that action; try another org (sign out / sign in after switching in the web app) or ask an admin.  
- **Long report / analysis** → still normal for several minutes; keep the user informed.  
- If support is needed and a `request_id` exists, include it **after** a plain explanation.

## 4. CLI

sumcli is the preferred surface when a shell is available (plugin minimum **0.1.3**); MCP is the fallback for shell-less hosts. When a shell is present, also check the CLI session: `sumcli whoami` — 401 → `sumcli login` (separate credential; a successful MCP sign-in does not sign in the CLI). If sumcli is missing or failed: follow `../api/references/sumcli.md` — install at first need, after an explicit yes. On Windows use the PowerShell or cmd.exe bootstrap, never `curl | sh`.

## Rules

- Do **not** download OpenAPI or debug connector key names here.  
- Do **not** dump internal tool ids into chat.  
- Do **not** run `python3 ../api/scripts/sum_api.py doctor` (or any relative `../api/...` path) — relative paths break when skills mount as `summation:api`.  
- If they ask “is X supported?”, fetch **`https://docs.summation.com/llms.txt`** then the linked page (see `../api/references/product.md`).
