---
name: connect
description: Connect a data source (Postgres, Snowflake, etc.) to Summation — non-secret settings in chat, secrets never in MCP tool args or the conversation when avoidable; then test and attach datasets via MCP.
---

# Summation Connect

**Secrets must never pass through MCP tool arguments or (when avoidable) chat.** Connection **create with password** is not on the curated MCP surface for that reason.

## Preferred paths (in order)

1. **Webapp end-to-end (default):** workspace → **Connections** → Add connection. Dictate non-secret fields so the user only types secrets in the browser. Then return here for MCP browse/attach/test.
2. **After a connection exists:** use MCP only — `list_data_connections`, `test_data_connection`, `browse_connection_resources`, `attach_connection_datasets`, `list_connection_datasets`.
3. **Pasted-secret salvage:** if the user already pasted a secret, do not bounce them — guide webapp create with that value and advise **rotating** the credential; teach webapp/file habits next time.

## Flow (MCP after the pipe exists)

1. Collect **non-secret** settings in chat; echo them back for a yes.
2. User creates the connection in the **webapp** (or already has one).
3. **`list_data_connections`** → find the new id; **`test_data_connection`**.
4. **Datasets gate:** `list_connection_datasets`. If empty, `browse_connection_resources` (label as attachable preview, not “already data”), then **`attach_connection_datasets`** for chosen tables — or send them to Connections in the webapp.
5. Confirm with `list_connection_datasets` / a light `search_tables`. Hand back to `$addison-start` step 2 if that was the parent flow.

## Rules

- Narrate outcomes, not protocol internals.
- Never put passwords into MCP tool JSON.
- Never create a secretless orphan connection and leave it.
- A live connection is not the finish line — **attached datasets** are.
- Auth for MCP tools: `$addison-signin` if `whoami` fails.
