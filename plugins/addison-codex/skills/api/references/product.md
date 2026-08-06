# Summation product map (for the Addison plugin)

Use this before answering “what can Summation do?” or “is X supported?”. Prefer this file and official docs over inventing limits. When unsure, fetch **`https://docs.summation.com/llms.txt`** first, then open the linked page — never treat a wrong URL 404 as “unsupported.”

## Supported data connections

These are **supported** (docs under `https://docs.summation.com/features/connectors/…`):

| Source | Docs |
|---|---|
| **Postgres** | https://docs.summation.com/features/connectors/postgres.md |
| **Snowflake** | https://docs.summation.com/features/connectors/snowflake.md |
| **BigQuery** | https://docs.summation.com/features/connectors/bigquery.md |
| **Redshift** | https://docs.summation.com/features/connectors/redshift.md |
| **Databricks** | https://docs.summation.com/features/connectors/databricks.md |
| **MySQL** | https://docs.summation.com/features/connectors/mysql.md |
| **SQL Server** | https://docs.summation.com/features/connectors/mssql.md |
| **Oracle** | https://docs.summation.com/features/connectors/oracle.md |
| **MongoDB** | https://docs.summation.com/features/connectors/mongodb.md |
| **ClickHouse** | https://docs.summation.com/features/connectors/clickhouse.md |
| **MotherDuck** | https://docs.summation.com/features/connectors/motherduck.md |
| **S3** | https://docs.summation.com/features/connectors/s3.md |
| **GCS** | https://docs.summation.com/features/connectors/gcs.md |
| **AWS Glue** | https://docs.summation.com/features/connectors/glue.md |
| **Apache Iceberg** | https://docs.summation.com/features/connectors/iceberg.md |
| **REST / HTTP APIs** | https://docs.summation.com/features/connectors/http.md |
| **GitHub** | https://docs.summation.com/features/connectors/github.md |

Overview: https://docs.summation.com/features/connectors.md

**Neon, RDS, Cloud SQL, AlloyDB, etc.** that speak Postgres → treat as **Postgres**. Same idea for other hosted variants of the sources above.

**Do not say a source is unsupported** unless you have checked `llms.txt` / this list and the connector page is missing. OpenAPI free-form `type` fields are **not** a full product catalog.

## How customers get value (product features)

| Need | How in this plugin |
|---|---|
| Ask a business question | `ask_analyst` / `$addison-query` |
| Explore tables | `$addison-catalog`, `search_tables`, previews |
| Full write-up for leadership | `$addison-report` → export markdown/PDF/DOCX |
| Check a report before sharing | `$addison-validate` |
| Add a warehouse/database | `$addison-connect` → **Summation web app** for passwords |
| Recurring emailed analysis | Playbooks in the web app (today) + `$addison-schedule` for cadence |
| Who am I / is it working? | `$addison-signin`, `$addison-diagnose` |

## Product docs index

Always start here when looking up features:

```text
https://docs.summation.com/llms.txt
```

Useful integration pages (when present in the index): Codex plugin, Codex plugin, MCP server, CLI, Public API under `https://docs.summation.com/integrations/…`.

## Voice with customers

Talk like a helpful analyst, not an API engineer:

- Say “Connections in Summation” not “POST /v1/connections/data”
- Say “Postgres is supported” not “type enum is free-form in OpenAPI”
- Say “Still building your report…” not silent multi-minute waits
- Never dump OpenAPI, raw tool ids, or failed key-guessing experiments into chat
