# Summation product knowledge (dynamic)

**Do not treat this file as a catalog of features.** Product capabilities change; the live docs index is authoritative.

## Always look up the product map

Before answering “what’s supported?”, “can we connect X?”, or “what can Summation do?”, fetch:

```text
https://docs.summation.com/llms.txt
```

That index lists current docs (connectors, integrations, features). Then:

1. Open the relevant linked page (e.g. a connector or feature guide).  
2. Answer from that page in plain language for the user.  
3. If `llms.txt` or the page fails to load, say you couldn’t reach the docs right now — **do not invent** “unsupported” from a failed fetch, a wrong URL, marketing homepage copy, or a truncated API spec.

## How to use the index

- **Supported data sources:** find connector entries under the docs index (Postgres, Snowflake, BigQuery, etc. appear when published there). Hosted variants (e.g. Neon → Postgres) map to the matching connector page.  
- **Other product areas:** reports, playbooks, schedules, plugins, MCP, CLI, API — use the matching links in `llms.txt`.  
- **Never** treat OpenAPI free-form fields as the full product catalog.

## Plugin behavior vs product catalog

Claude invokes `/summation:name`. Codex invokes `$summation-name`. Same skills.

| Need | In this plugin |
|---|---|
| Ask a business question | `query` skill or `ask_analyst` |
| Explore tables | `catalog` |
| Leadership write-up | `report` → export |
| Check a report | `validate` |
| Add a warehouse/database | `connect` (passwords in Summation **Connections**) |
| Recurring emailed analysis | playbooks + `schedule` |
| Workflow ideas from recent IDE chats | `opportunities` (local scan + catalog) |
| Sign in / health | `signin`, `diagnose` |

The **list of warehouses and features** still comes from `llms.txt` + linked docs, not from hardcoding here.

## Voice

Talk like a helpful analyst: “Postgres is supported — here’s how we connect it,” not API enums or OpenAPI dumps.
