---
name: start
description: Summation onboarding wizard — guided first-run setup with a visual progress stepper, MCP auth, data source map, a hello from Addison, and suggested first reports. Use when a user says "set up summation", "get started with summation", asks what Summation can do, or has clearly never connected before.
---

# Summation Start — five-star onboarding

Walk a brand-new user from zero to their first report, with a visual that tracks progress. **All data plane = summation MCP tools.** Auth = host OAuth via the `signin` skill.

## The four steps

```
1 CONNECT → 2 DISCOVER → 3 MEET ADDISON → 4 FIRST REPORT
```

**Render the welcome visual FIRST, before any tool call** — interactive HTML from `references/welcome.html` (four-step stepper, dark clean styling). If the surface can’t render HTML artifacts, use a markdown checklist — never block on the visual.

**Re-render the visual after each step**, with that step done and the next active. Choices stay in chat replies.

### Step 1 — Connect

Call **`whoami`** (or run the `signin` skill).

- Identity returned → mark done; show user/org/scopes.
- Needs auth → run **`signin`** (browser OAuth; no device-login scripts).
- Tools missing → enable/reload the **addison** plugin so `.mcp.json` loads, then retry.

### Step 2 — Discover (GATE: connections AND attached datasets)

Build a source map with MCP:

- `list_data_connections`
- For each connection: `list_connection_datasets` (and counts)
- `search_tables` / project list via `list_projects`

**Zero connections → pause. Do not proceed to steps 3–4. Do not suggest reports.**

- Mark step 2 amber/blocked.
- Say plainly: no data sources yet. Any internal system tables are **not** business data.
- Paths: **(a)** `/addison:connect` (webapp for secrets + MCP attach), **(b)** workspace → Connections.
- After a connection exists: re-check datasets.

**Gate 2b — attached datasets must be > 0.** A connection is only a pipe. If datasets are empty:

- Stay blocked. Optionally `browse_connection_resources` as a **preview of what they can attach**.
- Attach via `attach_connection_datasets` or the webapp Connections page.
- Resume when `list_connection_datasets` (or equivalent totals) shows data.

**Both gates pass** → source map panel: systems, dataset counts, notable table names (verbatim from tools).

### Step 3 — Meet Addison (project must see data)

1. Ensure a project: `list_projects` / `get_default_project`; if none, propose `getting-started` and `create_project` only after yes.
2. **Project catalog:** `list_catalog_entries`. If empty, pick business tables (`search_tables`) and `attach_catalog_entry` for each agreed table.
3. **`ask_analyst`** with roughly:

   > A new user just connected. In 3 short bullets, introduce what you can do with the data you can see, then propose 3 specific, runnable report ideas based on the actual tables available. Keep it under 120 words.

   Buffered ~15–60s; keep the visual updated. If the analyst fails (infra), generate 3 ideas yourself from real table names — don’t dead-end.

### Step 4 — First report

Numbered report-idea cards in the visual. Ask: “Run 1, 2, 3 — or describe your own.” On yes → `/addison:report` (markdown) → offer `/addison:validate`. Mark step 4 done with next steps (`query`, `catalog`, `report`).

## Voice

- Outcomes, never mechanics: no endpoint paths, no schema dumps in chat.
- Never narrate capability uncertainty mid-flow.
- Only surface `request_id` when something fails.

## Rules

- **Attached datasets** (not raw table counts, not browsable-only sources) mean “data is analyzable.”
- Ladder: MCP auth → connection → attached datasets → project catalog → Addison.
- Visual first; one visual updated through the flow.
- Never ask for DB passwords in chat; `connect` owns secret handling.
- Prefer under five minutes of feel; stream progress language on long tools.
