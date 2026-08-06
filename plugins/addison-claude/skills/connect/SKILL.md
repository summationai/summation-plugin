---
name: connect
description: Connect a data source (Postgres, Snowflake, BigQuery, etc.) to Summation. Use when the user wants to add a warehouse or database. Secrets stay in the Summation web app; then attach tables with clear names via MCP.
argument-hint: "[postgres|snowflake|bigquery|... or describe the source]"
---

# Summation Connect

Help the user get a **live data source** into Summation, then make its tables analyzable under **human-readable names**.

## Product knowledge (required)

1. Read sibling `../api/references/product.md` (or fetch `https://docs.summation.com/llms.txt`) before answering “what sources are supported?”
2. **Postgres is supported**, as are Snowflake, BigQuery, Redshift, Databricks, MySQL, SQL Server, Oracle, MongoDB, ClickHouse, MotherDuck, S3, GCS, Glue, Iceberg, REST, GitHub — see product.md.
3. Hosted Postgres (Neon, RDS, Cloud SQL, …) → walk them as **Postgres**.

Never invent “I can’t confirm that source” after a failed URL or truncated API spec. Prefer product docs.

## Customer path (default — do this)

**New connections with passwords are created in the Summation web app**, not by inventing API calls in chat.

1. Confirm the source type (use the supported list).
2. Collect **non-secret** fields only (host, database, user, warehouse, …). Echo them for confirmation.
3. Tell the user clearly:

   > Open Summation → **Connections** → **Add connection** → pick **\<Source\>**.  
   > Enter the settings we listed. Put the **password only in the browser**.  
   > Click **Test**, then save. Tell me when it’s done.

4. Wait for the user. Do **not** dig through OpenAPI, guess config key names, or run multi-variant experiments in chat.
5. When they say done: MCP `list_data_connections` → `test_data_connection` → browse → **attach with names** (below).

If they already have a connection: skip create; go to attach.

## After the connection exists (MCP)

1. `list_data_connections` — find the connection by name.
2. `test_data_connection` — report pass/fail in plain language (not raw error dumps unless needed).
3. `browse_connection_resources` — show what can be attached as a **preview**, not “already loaded.”
4. **`attach_connection_datasets` — always pass a clear `name` for each table** (use the source table name, e.g. `customers`, `invoices`).  
   **Never accept auto names** like `pg_…_dataset_2`. If the tool would auto-name, set `name` explicitly.
5. Verify: `list_connection_datasets` shows those friendly names; for project work, `attach_catalog_entry` as needed with clear labels.
6. Confirm to the user: “Connected **X**. Tables ready: **a, b, c**.” Only after verification.

## Hard bans (do not do these in chat)

- Download or parse OpenAPI to discover connector types or field names for the user.
- Guess password-field or config-key variants (`database` vs `pgDb`, etc.) across many retries.
- Put secrets in MCP tool arguments or re-ask for a password in chat (if they already pasted one: use webapp, advise rotating).
- Create a connection without a password and leave an unfinished orphan.
- Claim success from intermediate status text without a final list/test check.
- Dump `/v1/…` paths, schema JSON, or internal tool ids to the user.

## File / CSV import

If file→table import fails or tools are missing:

> File import isn’t available in this environment right now. Easiest path: connect a database in Summation (**Connections**), or explore files only if Addison can already read them in this project. We can retry import later if the platform path is fixed.

Do not name internal sandbox tools (`apply_data_table`, etc.) to the user.

## Pasted-secret salvage

If the user already pasted a password: don’t scold and bounce them. Guide webapp create with that value, then firmly recommend **rotating** the credential because it appeared in chat. Prefer file/webapp next time.

## Auth

If MCP auth fails: hand off to `/addison:signin`.
