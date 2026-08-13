---
name: signout
description: "Disconnect Codex from Summation — clear the hosted MCP session so the next use re-authenticates. Use when the user wants to disconnect, switch Summation user/org/environment, or clear a stale MCP session."
---

# Summation Sign-out

Auth lives in Codex’s MCP client. Sign-out clears that session so the next Summation tool call re-prompts browser auth.

## Flow

1. **Disconnect** using the host control when available (`/mcp` → disconnect / re-authenticate for **summation**). Prefer that over CLI when the host can do it.

2. **CLI fallback** only if the host control is unavailable. Do **not** blanket-suppress errors:

```bash
codex mcp logout summation
codex mcp remove summation
```

- Exit 0, or a clear “not found / not registered” message → registration is gone; treat as already signed out for that path.  
- Any other failure (CLI missing, permission, unexpected error) → **stop**. Tell the user what failed and how to clear **summation** under `/mcp` manually. Do not claim disconnected.

3. **Verify** before confirming: `codex mcp get summation` should fail or show no live session / no stale `Authorization` header. If it still shows a configured server with auth material, remove that user-scope entry and re-check.

4. Report **disconnected** only after host disconnect or a successful remove **and** verification. Next `$summation-signin` re-runs the connect flow.

## Internal vs external

| | After sign-out |
|---|---|
| **External** | Next sign-in is production/plugin default only — no env picker. |
| **Internal** (`SUMMATION_PLUGIN_INTERNAL=1`) | Next sign-in asks **environment** again and re-applies the allowlisted MCP URL; **tenant** is whatever org they approve in the browser (switch org on the web app first if needed). |

Env and tenant are both pinned at sign-in. Changing either always means sign out → sign in.

## Rules

- Do not use `sum_api.py logout` as the primary path (legacy device-login).
- If `codex mcp get summation` still shows an `Authorization` header, remove that user-scope entry so headerless OAuth can work.
- Never print tokens while inspecting MCP config.
