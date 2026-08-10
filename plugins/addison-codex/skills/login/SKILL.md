---
name: login
description: >
---

# Login → signin

This skill was **renamed to `signin`**. Do **not** run `python3 ../api/scripts/sum_api.py login` / `login-poll` / `mcp-connect`. Relative `../api/scripts/...` paths fail under hosts that mount skills as `addison:api` (not a sibling named `api`).

## What to do

Follow the **`signin`** skill: host MCP OAuth for server **`summation`**, then confirm with **`whoami`**.

Slash: `$addison-signin` (or this alias `$addison-login` if registered).
