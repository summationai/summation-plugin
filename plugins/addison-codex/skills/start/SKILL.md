---
name: start
description: Summation onboarding — sign in, map data, meet Addison, first report. Use when the user says set up Summation, get started, or is clearly new.
---

# Summation Start

Walk a new user from zero to a first useful answer **in plain language**. No HTML artifacts or welcome steppers. Prefer MCP tools + domain skills. Product facts: `../api/references/product.md` and `https://docs.summation.com/llms.txt`.

## Checklist (optional one-liner in chat)

`1 Connect → 2 Discover → 3 Meet Addison → 4 First report`

### Step 1 — Connect (sign in)

Run the **`signin` skill**. Show who they are (name/email, org) in ordinary words. Do not invent a second auth path.

### Step 2 — Discover (hard gate)

MCP: `list_data_connections`, `list_connection_datasets`, `list_projects`, `search_tables` as needed.

**No connections → stop.** Do not invent reports. Say clearly there is no business source yet. Offer:

1. **Connect a database/warehouse** → `$addison-connect` (web app for passwords; Postgres/Snowflake/etc. are supported — see product.md)  
2. **They already connected in the web app** → re-list connections and continue  

**Connection exists but no attached datasets → stop.** A connection is only a pipe. Browse what can be attached; attach with **friendly names** (table names). Never leave auto `*_dataset_N` names. Or send them to **Connections** in the web app to attach, then re-check.

**CSV / file import** if it fails: use the friendly failure text from the **connect** skill — do not thrash failed import tools or name internal platform tools.

**Gate open** when there is at least one real connection with attached, named datasets. Show a short source map: system names + readable table names.

### Step 3 — Meet Addison

1. Ensure a project (`list_projects` / `get_default_project` / create only with consent).  
2. Project catalog: attach agreed business tables if empty (`attach_catalog_entry`).  
3. `ask_analyst`: introduce what you can see + 3 concrete report ideas from **real** table names. Tell the user Addison is working; long answers are normal.

### Step 4 — First report

Numbered ideas in chat. On yes → **report** skill (markdown) → offer **validate**. Next steps in plain language (ask another question, catalog, report).

## Voice

- Outcomes only for the user: no endpoints, OpenAPI, or raw tool-id dumps.  
- Never claim “added” / “imported” without a final list/check.  
- No HTML welcome visuals.

## Rules

- Analyzable data = **attached datasets with clear names**, not system tables alone and not “browsable but unattached.”  
- Passwords never in chat; **connect** skill owns that path.  
- Keep momentum: short steps, clear waits on long tools.
