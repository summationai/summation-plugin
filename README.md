# Addison — Summation's AI analyst in Claude Code and Codex

Plugin marketplace for Summation. One plugin, `addison`, brings Addison to Claude Code, Claude Desktop, and OpenAI Codex: data questions over the hosted Summation MCP server, report generation and export (PDF/DOCX/Markdown), catalog discovery, bounded SQL.

**Architecture:** skills orchestrate the **summation MCP server**. Auth is **host-managed MCP OAuth** (browser) on Claude Code, Claude Desktop, and Codex — the plugin ships a headerless `.mcp.json` and does not mint or inject bearer tokens for the happy path.

**External vs internal**

| | External (default) | Internal |
|---|---|---|
| Who | Customers | Summation employees |
| Enable | (nothing) | Launch Claude with `ADDISON_PLUGIN_INTERNAL=1` |
| Environment | Single plugin default | `/addison:signin` asks prod / staging / sandbox |
| Tenant | Org approved in browser | Same; skill tells you to switch org on the web app, then re-auth |

```bash
# Internal dogfood (env picker + tenant guidance at sign-in)
ADDISON_PLUGIN_INTERNAL=1 claude --plugin-dir ./plugins/addison-claude
```

## Install

**Claude Code (CLI/IDE):**

```
/plugin marketplace add summationai/addison-plugin
/plugin install addison@summation
```

Then `/addison:signin` — Claude authenticates the **summation** MCP server in the browser. Or just invoke a Summation tool / `/addison:start` and complete the auth prompt when it appears.

**Dogfood note (this branch / 0.10.0):** `.mcp.json` points at **sandbox**  
`https://sandbox-mcp.summation.com/mcp`  
so you can test-drive OAuth before prod is deployed. Flip the URL to `https://mcp.summation.com/mcp` when prod OAuth is live.

**claude.ai / Claude Desktop (org admins):** Admin console → Plugins → Add plugins → *Sync from GitHub* (this repo) or *Upload a file* using the release zip:

```
https://github.com/summationai/addison-plugin/releases/latest/download/addison-plugin.zip
```

Members then install from the org library. Desktop is MCP-native: same headerless server + host auth.

**Codex** (same repo — `plugins/addison-codex` is **generated** from Claude via `./build-codex.sh`):

```
codex plugin marketplace add summationai/addison-plugin
codex plugin install addison
```

Then `$addison-signin` or any data ask. Skills use `$addison-…` mentions. MCP is packaged in the plugin (headerless sandbox URL while dogfooding); auth is `codex mcp login summation` / host browser OAuth — same model as Claude, not a second setup step.

```bash
# local dogfood from this checkout
codex plugin marketplace add ./   # or path to this repo
codex plugin install addison
# internal env picker (same flag as Claude Code):
ADDISON_PLUGIN_INTERNAL=1 codex
```

## Contents

| Skill | Invoke | Does |
|---|---|---|
| `start` | `/addison:start` | guided onboarding: connect → source map → meet Addison → first report |
| `api` | model-invoked | MCP tool map + safety rules (domain skills are preferred) |
| `signin` | `/addison:signin` | ensure MCP auth (host browser OAuth via `whoami`) |
| `signout` | `/addison:signout` | clear Summation MCP session |
| `diagnose` | `/addison:diagnose` | MCP connectivity/auth + environment card |
| `report` | `/addison:report` | generate report → export markdown/PDF/DOCX |
| `validate` | `/addison:validate` | report verification before external share |
| `query` | `/addison:query` | bounded read-only SQL or `ask_analyst` |
| `catalog` | `/addison:catalog` | search/describe tables, views, catalog |
| `connect` | `/addison:connect` | add a data source (secrets via webapp; MCP for test/attach) |
| `schedule` | `/addison:schedule` | recurring playbook runs + email (confirm recipients) |

Credentials are **not** stored by the plugin for the happy path. The host MCP client holds the session token. Do not commit config or tokens; `.summation-config*` stays gitignored for any legacy local files.

## Org announcement template

> **Summation is now in Claude.** Open a new chat and type **/addison:start** — it walks you through connecting (browser auth), shows a map of your data, introduces Addison, and runs your first report. Already connected? Just ask data questions, or use /addison:report, /addison:query, /addison:catalog, /addison:validate.

## For agent harnesses (customer `AGENTS.md` snippet)

```md
When working on data analysis, metrics, or report commentary, use the Summation
plugin first (catalog discovery before SQL; never guess table names). Prefer
exported report content over raw internals, cite request_ids on failures, and
run /addison:validate before any report is shared externally. Drafts need explicit
user approval before publishing anywhere.
```

## One plugin, two surfaces

`plugins/addison-claude` is the source of truth:

- **`.mcp.json`** — remote Summation MCP, **no headers** (OAuth on first use)
- **skills/** — product workflows over curated MCP tools
- **`sum_api.py`** — legacy/local escape hatch only (not used by domain skills)

The **Codex** surface is **generated** from Claude (one product, two packages):

| Shared | Claude-only | Codex-only (builder) |
|---|---|---|
| Skills, MCP URL, auth model, external/internal | `.claude-plugin/`, SessionStart hook | `$addison-` mentions, Codex `.mcp.json` shape, `codex mcp …` CLI, `.codex-plugin/` |

```bash
./build-codex.sh   # regenerates plugins/addison-codex + .agents/plugins/marketplace.json
```

CI (`Check generated Codex edition`) fails if Codex drifts from source. **Never hand-edit** `plugins/addison-codex`.

## Dev loop

```bash
# External-shaped dogfood (plugin default MCP URL — currently sandbox)
claude --plugin-dir ./plugins/addison-claude

# Internal dogfood (sign-in asks env + tenant guidance)
ADDISON_PLUGIN_INTERNAL=1 claude --plugin-dir ./plugins/addison-claude

# If you still have an old user-scope Authorization header entry, remove it so OAuth can win:
claude mcp remove -s user summation

claude plugin validate ./plugins/addison-claude
./build-codex.sh
./build-zip.sh
```

## Release

1. Bump `version` in `plugins/addison-claude/.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json`.
2. When leaving sandbox dogfood, set `.mcp.json` URL to `https://mcp.summation.com/mcp`.
3. Run `./build-codex.sh`, commit, merge to `main`.
4. Tag matching the version:
   ```bash
   git tag v0.10.0 && git push origin v0.10.0
   ```
   The release workflow publishes `addison-plugin.zip` as **Latest**.

`https://github.com/summationai/addison-plugin/releases/latest/download/addison-plugin.zip`
