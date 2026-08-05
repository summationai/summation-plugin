---
name: signout
description: Disconnect Codex from Summation — clear the hosted MCP session so the next use re-authenticates. Use to disconnect, switch Summation user/org, or clear a stale MCP session.
---

# Addison Sign-out

Auth lives in the MCP client. Sign-out means removing or clearing the `summation` MCP server entry so the next tool call re-prompts browser auth.

## Flow

1. Remove the Summation MCP server from Codex config (delete the `summation` / MCP server block for `https://sandbox-mcp.summation.com/mcp` or the prod URL, including any legacy Authorization header).
2. Confirm Summation tools no longer work without re-auth.
3. Report: disconnected; next `$addison-signin` or tool use will re-authenticate.

## Rules

- Prefer clearing MCP config over legacy helper logout unless a device-login credential file is still present and the user wants it gone too.
- To switch org/tenant: switch org on the Summation web app, then sign out and sign in again.
- Never print tokens while inspecting config.
