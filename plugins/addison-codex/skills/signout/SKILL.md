---
name: signout
description: Disconnect Codex from Summation — clear the hosted MCP session so the next use re-authenticates. Use when the user wants to disconnect, switch Summation user/org/environment, or clear a stale MCP session.
---

# Addison Sign-out

Auth lives in Codex’s MCP client. Sign-out clears that session so the next Summation tool call re-prompts browser auth.

## Flow

1. **Disconnect** using the host control, or:

```bash
codex mcp remove summation 2>/dev/null || true
```

   Also run `codex mcp logout summation` if a session remains after remove. Prefer the host’s “disconnect / re-authenticate” when available.

2. **Confirm** tools no longer work without re-auth (optional: do not call tools that would immediately re-prompt unless the user wants to stay signed out).

3. Report: disconnected. Next `$addison-signin` re-runs the connect flow.

## Internal vs external

| | After sign-out |
|---|---|
| **External** | Next sign-in is production/plugin default only — no env picker. |
| **Internal** (`ADDISON_PLUGIN_INTERNAL=1`) | Next sign-in asks **environment** again and re-applies the allowlisted MCP URL; **tenant** is whatever org they approve in the browser (switch org on the web app first if needed). |

Env and tenant are both pinned at sign-in. Changing either always means sign out → sign in.

## Rules

- Do not use `sum_api.py logout` as the primary path (legacy device-login).
- If `codex mcp get summation` still shows an `Authorization` header, remove that user-scope entry so headerless OAuth can work.
- Never print tokens while inspecting MCP config.
