---
name: signout
description: Disconnect Claude from Summation - revoke the stored device-login session, remove the local credential, and deregister the Summation MCP server. Use when the user wants to disconnect, sign in as a different Summation user, or clear a stale session.
---

# Addison Logout

Revoke the stored device-login session, remove `SUM_API_DEVICE_LOGIN_CREDENTIAL`, and deregister the Summation MCP server from Claude Code. The helper lives in the sibling `api` skill: `<plugin>/skills/api/scripts/sum_api.py` (resolve relative to this skill's base directory: `../api/scripts/sum_api.py`).

## Flow

1. Run logout, then deregister the MCP server:

```bash
python3 ../api/scripts/sum_api.py logout
python3 ../api/scripts/sum_api.py mcp-disconnect
```

2. Interpret the results:
   - `logout` → `{"status":"logged_out", ...}` — the device-login session was revoked and the credential removed. `{"status":"already_logged_out", ...}` — no credential was present.
   - `mcp-disconnect` → `{"status":"disconnected"}` — the MCP registration (which carried a bearer header) was removed. `{"status":"not_registered"}` — nothing to remove.

## Rules

- Always run both commands: a revoked session must not leave a stale bearer header in the Claude Code MCP registration.
- Report both outcomes to the user.
- Internal users change environment or tenant by signing out and signing back in (both are pinned at login) — after logout, re-run `/addison:signin` and pick the new environment, switching org on the Summation web app first if they need a different tenant.
