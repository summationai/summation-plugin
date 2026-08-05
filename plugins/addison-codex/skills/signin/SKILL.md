---
name: signin
description: Connect Codex to Summation via the hosted MCP server. Use when the user needs to connect Addison, when Summation tools are missing or unauthenticated, or when any Summation MCP call fails with 401/403.
---

# Addison Sign-in

Auth is owned by the MCP client, not by this plugin. Register the hosted Summation MCP server **without** an Authorization header and complete browser auth when the host prompts.

**Dogfood target today:** sandbox (`https://sandbox-mcp.summation.com/mcp`). Production URL flips when prod OAuth is deployed.

## Flow

### 1. Check whether Summation MCP tools are available

Call the MCP tool **whoami** (server name `summation`).

| Outcome | Action |
|---|---|
| Returns identity | Already connected. Report who they are and stop. |
| Auth challenge / not connected | Continue to step 2. |
| Server missing | Ensure the plugin is installed and the MCP URL is registered (step 2). |

### 2. Ensure a headerless MCP entry, then authenticate

If `summation` is not configured, add it to Codex MCP config as HTTP:

- URL: `https://sandbox-mcp.summation.com/mcp` (dogfood)
- **No** Authorization header — host OAuth owns the token

Tell the user:

> Summation needs a one-time browser sign-in. When Codex prompts you to authenticate the **summation** MCP server, approve it in the browser. No password or token is pasted into this chat.

Then call **whoami** again. Do **not** run device-login scripts or write bearer headers into config for the happy path.

### 3. Confirm

After a successful `whoami`, call `get_default_project` or `list_projects`, report identity/org, and hand off to `$addison-start` if they wanted onboarding.

## Rules

- Never print, log, or commit tokens.
- Never ask the user to paste client secrets or bearers into chat.
- On later 401/403 from Summation tools: re-run this skill (re-auth), do not improvise REST auth.
- Tenant is the org approved in the browser; switch org on the web app, then re-auth to change tenant.
