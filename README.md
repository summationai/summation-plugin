# Summation plugin for Claude Code and Codex

Plugin marketplace for Summation. One plugin, `summation`, brings the analyst into Claude Code, Claude Desktop, and OpenAI Codex: data questions over the hosted Summation MCP server, report generation and export (PDF/DOCX/Markdown), catalog discovery, and bounded SQL.

Install the plugin, approve Summation in the browser once, then ask in plain English. No API keys and no secrets pasted into chat. Auth is host-managed MCP OAuth; the plugin ships a headerless connection to production:

```text
https://mcp.summation.com/mcp
```

## Install

**Claude Code (CLI/IDE):**

Two different names:

1. **GitHub repo** — `summationai/summation-plugin` (hosts the marketplace catalog).
2. **Plugin @ marketplace** — install plugin `summation` from marketplace `summationai`.

```
/plugin marketplace add summationai/summation-plugin
/plugin install summation@summationai
```

Then `/summation:signin` — or run `/summation:start` / ask a data question and complete the browser sign-in when Claude prompts you.

0.11.0 renamed the plugin from `addison` to `summation` (slash commands `/summation:…`). 0.12.0 is one Agent Plugins package (`plugins/summation`) for both hosts. If you still have `addison@summation` or the old `addison-plugin` marketplace, remove them and add `summationai/summation-plugin`.

**claude.ai / Claude Desktop (org admins):** Admin console → Plugins → Add plugins → *Sync from GitHub* (this repo) or *Upload a file* using the latest release zip:

```
https://github.com/summationai/summation-plugin/releases/latest/download/summation-plugin.zip
```

Members then install from the org library.

**Codex (CLI):**

```
codex plugin marketplace add summationai/summation-plugin
codex plugin install summation
```

Marketplace id is **summationai**; plugin id is **summation** (same as Claude: `summation@summationai`).

Then `$summation-signin` or any data ask. Skills use `$summation-…` mentions (not `/summation:…`). MCP is packaged with the plugin; auth is the same browser flow (`codex mcp login summation` if needed).

**Codex desktop app (Add plugin marketplace):**

Layout matches the `openai/plugins` convention: marketplace catalog at `.agents/plugins/marketplace.json`, plugin package at `plugins/summation/`.

| Field | Value |
|---|---|
| **Source** | `summationai/summation-plugin` |
| **Git ref** | `main` |
| **Sparse paths** | leave **empty** (clear the default `plugins/codex` placeholder) |

Then install plugin **summation** from the Summation marketplace, start a new thread (or restart the app), and run `$summation-start` or `$summation-signin`.

If you must sparse-checkout, include **both** the catalog and the package (not the package alone):

```text
.agents/plugins
plugins/summation
```

Sparse path `plugins/summation` alone fails with “marketplace root does not contain a supported manifest” — that directory is the plugin, not the marketplace.

## Contents

| Skill | Invoke | Does |
|---|---|---|
| `start` | `/summation:start` | guided onboarding: connect → map data → meet the analyst → first report |
| `opportunities` | `/summation:opportunities` | suggest workflows from recent local chats + live catalog (consent first) |
| `api` | model-invoked | MCP tool map + safety rules |
| `signin` | `/summation:signin` | connect or re-authenticate Summation (`login` is an alias) |
| `signout` | `/summation:signout` | disconnect Summation (`logout` is an alias) |
| `diagnose` | `/summation:diagnose` | check connectivity and what data is visible (`doctor` is an alias) |
| `report` | `/summation:report` | generate a report → export markdown/PDF/DOCX |
| `validate` | `/summation:validate` | verify a report before sharing |
| `query` | `/summation:query` | read-only query or open-ended analysis |
| `catalog` | `/summation:catalog` | search tables, views, catalog |
| `connect` | `/summation:connect` | add a data source (secrets stay in the Summation web app) |
| `schedule` | `/summation:schedule` | recurring playbook runs with email delivery |

Credentials for the happy path live in the host MCP client, not in this repo. Do not commit config files or tokens.

## Org announcement template

> **Summation is now in Claude.** Open a new chat and type **/summation:start** — it walks you through connecting, shows a map of your data, introduces the analyst, and runs your first report. Already connected? Just ask data questions, or use /summation:report, /summation:query, /summation:catalog, /summation:validate.

## For agent harnesses (customer `AGENTS.md` snippet)

```md
When working on data analysis, metrics, or report commentary, use the Summation
plugin first (catalog discovery before SQL; never guess table names). Prefer
exported report content over raw internals, cite request_ids on failures, and
run /summation:validate before any report is shared externally. Drafts need explicit
user approval before publishing anywhere.
```

## Development

**One skill tree, one package** ([Agent Plugins](https://agent-plugins.org/) 1.0.0):

| Path | Role |
|---|---|
| **`skills/`** | **Source of truth** — edit skills here only |
| **`packaging/plugin.json`** | Portable manifest + version |
| **`packaging/mcp.json`** | Portable MCP URL (`streamable-http`) |
| **`packaging/com.anthropic.claude/`** | Claude hooks |
| **`assets/`** | Brand images (`logo.png`, `logo-dark.png`, `icon.png`) |
| `plugins/summation/` | Generated package (spec core + Claude/Codex shims) |

```bash
# edit skills/ or packaging/…
./build-plugins.sh        # plugins/summation from skills/ + packaging/
claude --plugin-dir ./plugins/summation
claude plugin validate ./plugins/summation
./build-zip.sh            # dist/summation-plugin.zip for Desktop upload
```

CI regenerates the package and fails on drift. **Never hand-edit** `plugins/summation` (see `plugins/summation/GENERATED.md`). Claude still reads `.claude-plugin/` + `hooks/` + `.mcp.json`. Codex still reads `.codex-plugin/` and rewritten skills under `com.openai.codex/`. Clients that load Agent Plugins use root `plugin.json`, `mcp.json`, and `skills/`.

## Release

1. Bump `version` in `packaging/plugin.json`.
2. Run `./build-plugins.sh`, commit, merge to `main`.
3. Tag matching the version (for example `v0.12.0`) and push the tag. The release workflow publishes `summation-plugin.zip` as **Latest**.

`https://github.com/summationai/summation-plugin/releases/latest/download/summation-plugin.zip`
