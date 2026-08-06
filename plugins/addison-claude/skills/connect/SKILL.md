---
name: connect
description: Connect a data source (Postgres, Snowflake, BigQuery, etc.) to Summation. Use when the user wants to add a warehouse or database. Keep secrets out of chat; attach tables with clear names.
argument-hint: "[postgres|snowflake|bigquery|... or describe the source]"
---

# Summation Connect

Help the user get a **live data source** into Summation, then make its tables analyzable under **human-readable names**.

## Product knowledge (required)

1. Read sibling `../api/references/product.md` (or fetch `https://docs.summation.com/llms.txt`) before answering “what sources are supported?”
2. **Postgres is supported**, as are Snowflake, BigQuery, Redshift, Databricks, MySQL, SQL Server, Oracle, MongoDB, ClickHouse, MotherDuck, S3, GCS, Glue, Iceberg, REST, GitHub — see product.md.
3. Hosted Postgres (Neon, RDS, Cloud SQL, …) → treat as **Postgres**.

Never invent “I can’t confirm that source” after a failed URL or truncated API dig. Prefer product docs.

## Customer path for new connections (default)

**Passwords and secrets never go in chat or MCP tool arguments.**

1. Confirm the source type (supported list).  
2. Collect **non-secret** fields only; echo for confirmation.  
3. Guide the user:

   > Open Summation → **Connections** → **Add connection** → pick **\<Source\>**.  
   > Enter the settings we listed. Put the **password only in the browser**.  
   > Click **Test**, then save. Tell me when it’s done.

4. Wait. Do **not** dig through OpenAPI or guess config key names in chat.  
5. When they say done: MCP `list_data_connections` → `test_data_connection` → browse → **attach with names** (below).

If they already have a connection: skip create; go to attach.

(If MCP later exposes a safe create path that never puts secrets in the model transcript, you may use it — still never paste secrets into chat.)

## After the connection exists (MCP)

1. `list_data_connections` — find by name.  
2. `test_data_connection` — pass/fail in plain language.  
3. `browse_connection_resources` — preview of what can be attached.  
4. **`attach_connection_datasets` — always set a clear `name`** (source table name: `customers`, `invoices`, …). Never leave auto names like `pg_…_dataset_2`.  
5. If rename/detach tools exist, use them to fix mistakes; otherwise guide the user in Connections.  
6. Verify with `list_connection_datasets` (friendly names). Attach to the project catalog when needed.  
7. Only then: “Connected **X**. Tables ready: **a, b, c**.”

## File / CSV import

Prefer `import_file_to_table` (and related file tools) when the user has files in the project. Confirm with catalog/list after import. If import fails, say so plainly and offer: connect a warehouse, or retry after fixing the issue — no internal tool names.

## Hard bans (user chat)

- OpenAPI archaeology or multi-variant key guessing  
- Secrets in MCP args or chat (salvage: web app + rotate if already pasted)  
- Secretless orphan connections  
- Claiming success without a final list/test  
- Dumping paths, schema JSON, or internal tool ids  

## Auth

MCP auth failure → `/addison:signin`.
