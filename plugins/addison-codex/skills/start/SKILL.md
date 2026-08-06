---
name: start
description: Summation onboarding — sign in, map data, meet Addison, first report. Use when the user says set up Summation, get started, or is clearly new.
---

# Summation Start

Walk a new user from zero to a first useful answer **in plain language**. No HTML artifacts or welcome steppers. Prefer MCP tools + domain skills. For “what’s supported?”, always fetch **`https://docs.summation.com/llms.txt`** (see `../api/references/product.md`).

## Checklist (optional one-liner in chat)

`1 Connect → 2 Discover → 3 Meet Addison → 4 First report`

### Step 1 — Connect (sign in)

Run the **`signin` skill**. Show who they are (name/email, org) in ordinary words.

### Step 2 — Discover (hard gate)

MCP: `list_data_connections`, `list_connection_datasets`, `list_projects`, `search_tables` as needed.

**No connections → stop.** Offer:

1. **Connect a database/warehouse** → `$addison-connect` (confirm sources via `llms.txt` / product docs)  
2. **Import files** if they already have files in a project → file import tools, then confirm tables exist  
3. **They already connected in the web app** → re-list and continue  

**Connection exists but no attached datasets → stop.** Browse and attach with **friendly names** (table names). Never leave auto `*_dataset_N` names.

**Gate open** when there is at least one real connection (or imported tables) with clear, analyzable names. Short source map for the user.

### Step 3 — Meet Addison

1. Ensure a project (`list_projects` / `get_default_project` / create with consent).  
2. Project catalog: attach agreed business tables if empty.  
3. `ask_analyst`: introduce what you see + 3 concrete report ideas from **real** table names. Tell the user Addison is working.

### Step 4 — First report

Numbered ideas. On yes → **report** skill (markdown) → offer **validate**. Next steps in plain language.

## Voice

- Outcomes only: no endpoints, OpenAPI, or raw tool-id dumps.  
- Never claim “added” / “imported” without a final list/check.  
- No HTML welcome visuals.

## Rules

- Analyzable data = **named datasets / tables**, not system tables alone and not “browsable but unattached.”  
- Passwords never in chat; **connect** skill owns secrets.  
- Keep momentum: short steps, clear waits on long tools.
