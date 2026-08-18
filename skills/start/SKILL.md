---
name: start
description: Summation onboarding — sign in, map data, meet the analyst, first report. Use when the user says set up Summation, get started, or is clearly new.
---

# Summation Start

Walk a new user from zero to a first useful answer **in plain language**. No HTML artifacts or welcome steppers. Prefer MCP tools + domain skills. For “what’s supported?”, always fetch **`https://docs.summation.com/llms.txt`** (see `../api/references/product.md`). Scripted CLI use needs **sumcli ≥ 0.1.3** — check the version and install before the first call (`../api/references/sumcli.md`).

## Checklist (optional one-liner in chat)

`1 Connect → 2 Discover → 3 Meet the analyst → 4 First report`

### Step 1 — Connect (sign in)

Run the **`signin` skill**. Show who they are (name/email, org) in ordinary words.

### Step 2 — Discover (hard gate)

MCP first (do not stop early): `list_data_connections`, `list_connection_datasets`, `list_projects`, `search_tables` as needed. Treat **imported project tables** and **attached connection datasets** as analyzable data.

**Gate open** when either holds:

- at least one connection with attached datasets (friendly names — never leave auto `*_dataset_N`), **or**
- at least one imported / project table with a clear analyzable name  

Then give a short source map and continue.

**Gate closed** only when **both** are missing — no attached datasets **and** no imported tables. Then stop and offer:

1. **Connect a database/warehouse** → the `connect` skill (confirm sources via `llms.txt` / product docs)  
2. **Import files** into a project → file import tools, then re-list tables  
3. **They already connected or imported in the web app** → re-list and continue  

**Connection exists but nothing attached and no imports →** browse and attach with **friendly names** (table names), or import. Do not claim readiness until the gate opens.

### Step 3 — Meet the analyst

1. Ensure a project (`list_projects` / `get_default_project` / create with consent).  
2. Project catalog: attach agreed business tables if empty.  
3. `ask_analyst`: introduce what you see + 3 concrete report ideas from **real** table names. Tell the user the analyst is working.

### Step 3b — Opportunities from recent chats (optional, once)

After the gate is open **or** after a clear “no data yet” path, offer **once**:

> I can also look at recent local chats in this IDE for workflows Summation can take over (scan stays on your machine). Want that?

- **Yes** → run the **`opportunities`** skill (consent + local scan + catalog-grounded list). Prefer their pick for step 4.  
- **No** → one line: anytime the `opportunities` skill — then continue.  
- Do **not** scan without consent. Do **not** dump transcripts.

### Step 4 — First report

Numbered ideas (from catalog and/or opportunities). On yes → **report** skill (markdown) → offer **validate**. Next steps in plain language.

## Voice

- Outcomes only: no endpoints, OpenAPI, or raw tool-id dumps.  
- Never claim “added” / “imported” without a final list/check.  
- No HTML welcome visuals.

## Rules

- Analyzable data = **named datasets / tables**, not system tables alone and not “browsable but unattached.”  
- Passwords never in chat; **connect** skill owns secrets.  
- Keep momentum: short steps, clear waits on long tools.
