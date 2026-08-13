---
name: logout
description: Alias for signout — disconnect Summation MCP session so the next use re-authenticates. Prefer signout.
---

# Logout → signout

This skill was **renamed to `signout`**. Do **not** run `python3 ../api/scripts/sum_api.py logout` or relative `../api/scripts/...` paths.

## What to do

Follow the **`signout`** skill: host MCP disconnect (Claude `/mcp`, or `codex mcp logout` / `codex mcp remove`) for **summation**, verify, then report disconnected.

Invoke the `signout` skill (`logout` is an alias if the host still registers it).
