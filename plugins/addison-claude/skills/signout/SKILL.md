---
name: signout
description: Disconnect Claude from Summation — clear the hosted MCP session so the next use re-authenticates. Use when the user wants to disconnect, switch Summation user/org, or clear a stale MCP session.
---

# Addison Sign-out

Auth lives in Claude Code’s MCP client. Sign-out means clearing that session so the next Summation tool call re-prompts browser auth.

## Flow

1. **Disconnect the MCP server** using the host’s MCP UI or CLI, for example:

```bash
claude mcp remove summation -s user
```

   If the server was provided only by the plugin (not a user-scope override), disabling/reloading the plugin or clearing MCP auth for `summation` in `/mcp` is enough. Prefer the host’s “disconnect / re-authenticate” control when available.

2. **Confirm** Summation tools no longer work without re-auth: do not call tools that would re-trigger a silent reconnect unless the user asked to stay signed out.

3. Report: Summation MCP disconnected; next `/addison:signin` or tool use will open browser auth again.

## Rules

- Do not run `sum_api.py logout` or delete `~/.summation/*` as the primary path — those are legacy device-login leftovers. Only mention them if the user still has an old header-based `summation` entry (`claude mcp get summation` shows an `Authorization` header); then remove that user-scope entry so the plugin’s headerless `.mcp.json` can take over.
- To switch org/tenant: switch org on the Summation web app first, then sign out here and sign in again.
- Never print tokens while inspecting MCP config.
