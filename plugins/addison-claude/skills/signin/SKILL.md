---
name: signin
description: Connect Claude to Summation via the hosted MCP server. Use when the user needs to connect Addison, when Summation tools are missing or unauthenticated, or when any Summation MCP call fails with 401/403.
---

# Addison Sign-in

Auth is owned by Claude Code’s MCP client, not by this plugin. The plugin ships a headerless MCP server entry (`summation` → hosted Summation MCP). On first use Claude discovers OAuth, opens the browser, and stores the token. You never mint, poll, store, or inject a credential.

**Dogfood target today:** sandbox (`https://sandbox-mcp.summation.com/mcp`). Production URL flips when prod OAuth is deployed.

## Flow

### 1. Check whether Summation MCP tools are available

Call the MCP tool **`whoami`** (server name `summation`).

| Outcome | Action |
|---|---|
| Returns identity (user/org/scopes) | Already connected. Report who they are and stop (or continue to the `start` skill if they asked for onboarding). |
| Auth challenge / needs authentication / not connected | Continue to step 2. |
| Server missing entirely | Tell the user to enable the **addison** plugin (or reload Claude Code so `.mcp.json` loads), then retry `whoami`. |

### 2. Let Claude authenticate

Tell the user clearly:

> Summation needs a one-time browser sign-in. When Claude prompts you to authenticate the **summation** MCP server, approve it in the browser (same Summation account / SSO you use on the web app). No password or token is pasted into this chat.

Then invoke **`whoami`** again (or another cheap tool). Do **not** run device-login scripts, do **not** write `~/.summation/*` credentials, do **not** call `claude mcp add` with an `Authorization` header.

If the host surfaces a `/mcp` UI or an “Authenticate” control for `summation`, point the user there and wait for them to finish before retrying.

### 3. Confirm

After a successful `whoami`:

1. Call **`get_default_project`** (or `list_projects`) so the session has a project context.
2. Report: signed-in identity, org, environment (sandbox while dogfooding), and that Summation tools are ready.
3. If they were onboarding, hand off to `/addison:start` from step 2 (Discover).

## Environment / tenant

- **Default dogfood:** sandbox only — the plugin’s `.mcp.json` points at sandbox MCP.
- **Tenant** is the org the user approves in the browser (active org on the Summation web app). To switch tenant: switch org in the web app, then re-authenticate the MCP server (`/addison:signout` then this flow).
- **Internal multi-env** (staging/prod) after prod OAuth ships: change the MCP URL (or add extra named servers). Do not invent free-form hosts.

## Rules

- Never print, log, or commit tokens or credentials.
- Never ask the user to paste a client secret, device code, or bearer into chat.
- Never fall back to `sum_api.py login` / `login-poll` / `mcp-connect` for this skill — that path is retired for Claude.
- On later 401/403 from any Summation MCP tool: re-run this skill (re-auth), do not improvise REST auth.
