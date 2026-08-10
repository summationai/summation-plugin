---
name: login
description: "Alias for signin — connect Codex to Summation via hosted MCP browser OAuth. Use when the user needs to connect Addison or tools return 401/403. Prefer signin."
---

# Login → signin

This skill was **renamed to `signin`**. Do **not** run `python3 ../api/scripts/sum_api.py login` / `login-poll` / `mcp-connect`. Relative `../api/scripts/...` paths fail under hosts that mount skills as `addison:api` (not a sibling named `api`).

## What to do

Follow the **`signin`** skill: host MCP OAuth for server **`summation`**, then confirm with **`whoami`**.

Slash: `$addison-signin` (or this alias `$addison-login` if registered).
