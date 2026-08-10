---
name: opportunities
description: >
  Suggest Summation workflows from recent Claude Code or Codex chats and the live catalog.
  Use when the user asks what Summation can do for their work, wants workflow ideas, use cases,
  “how can you help”, opportunity scan, or after onboarding discover when they consent to a
  local chat scan. Also /addison:opportunities.
---

# Summation opportunities

Turn **recent local IDE chats** + **what’s already in Summation** into a short list of concrete next steps. Privacy first: scan stays on this machine unless the user later runs a normal Summation tool.

## When to run

- User: “what can Summation do for me?”, “workflows”, “use cases”, “how can you help my work?”
- `/addison:opportunities`
- Handoff from **`start`** after the data gate (only with consent)

## Privacy (say this once, plainly)

> I can scan recent **local** Claude Code / Codex sessions on this machine for themes (metrics, SQL, reports, CSVs, …). Nothing is uploaded. I only show short theme summaries, not full transcripts. OK?

- If they decline → skip the scan; still suggest from live catalog / docs if signed in.  
- Never paste long chat excerpts. Never invent table names.

## Flow

### 1. Local session scan (optional after consent)

Run the bundled scanner (local only, no network). Prefer the plugin root when the host sets it:

```bash
# Claude Code (plugin root set):
python3 "$CLAUDE_PLUGIN_ROOT/skills/opportunities/scripts/scan_sessions.py" \
  --days 14 --limit-sessions 20 --json \
  --project-substr "$(basename "$(pwd)")"

# Otherwise: path relative to this skill’s scripts/ directory in the installed package:
python3 skills/opportunities/scripts/scan_sessions.py --days 14 --limit-sessions 20 --json
```

Caps are intentional. Prefer `--json` and turn themes into customer language yourself. If the scan fails or finds nothing, say so and continue with catalog-only ideas.

### 2. Live Summation context (if signed in)

MCP: `whoami` (signin if needed) → `list_data_connections` / `list_connection_datasets` / `search_tables` or `/addison:catalog` as needed.

- **Have named tables** → ground each idea in real names.  
- **No data yet** → opportunities that start with `/addison:connect` or import, not fake schemas.

### 3. Present 3–5 opportunities

Numbered list. Each item:

1. **Theme** — one short phrase (from scan label or catalog).  
2. **Why it fits** — tie to a redacted sample or a real table (not a wall of chat).  
3. **Next step** — one skill/action: `query`, `report`, `validate`, `connect`, `catalog`, `schedule`, `start`.

Map themes roughly:

| Scan theme | Prefer |
|---|---|
| Metrics / KPIs / “why did it move” | `query` (Addison for narrative) or ranked SQL with `ORDER BY` |
| SQL / warehouse | `catalog` then `query`; `connect` if no source |
| CSV / files | import / `connect` then catalog |
| Board / status / narrative | `report` → offer `validate` |
| Recurring / every Monday | `report` then `schedule` |
| Data quality / pipelines | `catalog` + spot-check `query` |
| Connect / explore source | `connect` / `start` |

### 4. Act on their pick

When they choose a number → run that skill. Do not dump the whole menu again.

## Rules

- **Local scan only** for host chat history — no cloud “conversation intelligence.”  
- Prefer **catalog-grounded** next steps when MCP works.  
- Product map for “is X supported?” still comes from `https://docs.summation.com/llms.txt` (see `../api/references/product.md`).  
- Outcomes in user chat; no OpenAPI archaeology.  
- If not signed in: still list opportunities; first step is often `/addison:signin` or `/addison:start`.
