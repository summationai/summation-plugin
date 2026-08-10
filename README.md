# Addison — Summation's AI analyst in Claude Code and Codex

Plugin marketplace for Summation. One plugin, `addison`, brings Addison to Claude Code, Claude Desktop, and OpenAI Codex: data questions over the hosted Summation MCP server, report generation and export (PDF/DOCX/Markdown), catalog discovery, and bounded SQL.

Install the plugin, approve Summation in the browser once, then ask in plain English. No API keys and no secrets pasted into chat. Auth is host-managed MCP OAuth; the plugin ships a headerless connection to production:

```text
https://mcp.summation.com/mcp
```

## Install

**Claude Code (CLI/IDE):**

```
/plugin marketplace add summationai/addison-plugin
/plugin install addison@summation
```

Then `/addison:signin` — or run `/addison:start` / ask a data question and complete the browser sign-in when Claude prompts you.

**claude.ai / Claude Desktop (org admins):** Admin console → Plugins → Add plugins → *Sync from GitHub* (this repo) or *Upload a file* using the latest release zip:

```
https://github.com/summationai/addison-plugin/releases/latest/download/addison-plugin.zip
```

Members then install from the org library.

**Codex (CLI):**

```
codex plugin marketplace add summationai/addison-plugin
codex plugin install addison
```

Then `$addison-signin` or any data ask. Skills use `$addison-…` mentions (not `/addison:…`). MCP is packaged with the plugin; auth is the same browser flow (`codex mcp login summation` if needed).

**Codex desktop app (Add plugin marketplace):**

Layout matches the `openai/plugins` convention: marketplace catalog at `.agents/plugins/marketplace.json`, plugin package at `plugins/addison-codex/`.

| Field | Value |
|---|---|
| **Source** | `summationai/addison-plugin` |
| **Git ref** | `main` |
| **Sparse paths** | leave **empty** (clear the default `plugins/codex` placeholder) |

Then install plugin **addison** from the Summation marketplace, start a new thread (or restart the app), and run `$addison-start` or `$addison-signin`.

If you must sparse-checkout, include **both** the catalog and the package (not the package alone):

```text
.agents/plugins
plugins/addison-codex
```

Sparse path `plugins/addison-codex` alone fails with “marketplace root does not contain a supported manifest” — that directory is the plugin, not the marketplace.

## Contents

| Skill | Invoke | Does |
|---|---|---|
| `start` | `/addison:start` | guided onboarding: connect → map data → meet Addison → first report |
| `opportunities` | `/addison:opportunities` | suggest workflows from recent local chats + live catalog (consent first) |
| `api` | model-invoked | MCP tool map + safety rules |
| `signin` | `/addison:signin` | connect or re-authenticate Summation |
| `signout` | `/addison:signout` | disconnect Summation |
| `diagnose` | `/addison:diagnose` | check connectivity and what data is visible |
| `report` | `/addison:report` | generate a report → export markdown/PDF/DOCX |
| `validate` | `/addison:validate` | verify a report before sharing |
| `query` | `/addison:query` | read-only query or open-ended analysis |
| `catalog` | `/addison:catalog` | search tables, views, catalog |
| `connect` | `/addison:connect` | add a data source (secrets stay in the Summation web app) |
| `schedule` | `/addison:schedule` | recurring playbook runs with email delivery |

Credentials for the happy path live in the host MCP client, not in this repo. Do not commit config files or tokens.

## Org announcement template

> **Summation is now in Claude.** Open a new chat and type **/addison:start** — it walks you through connecting, shows a map of your data, introduces Addison, and runs your first report. Already connected? Just ask data questions, or use /addison:report, /addison:query, /addison:catalog, /addison:validate.

## For agent harnesses (customer `AGENTS.md` snippet)

```md
When working on data analysis, metrics, or report commentary, use the Summation
plugin first (catalog discovery before SQL; never guess table names). Prefer
exported report content over raw internals, cite request_ids on failures, and
run /addison:validate before any report is shared externally. Drafts need explicit
user approval before publishing anywhere.
```

## Development

**One skill tree, two packages** (DRY authoring):

| Path | Role |
|---|---|
| **`skills/`** | **Source of truth** — edit skills here only |
| `plugins/addison-claude/` | Claude package (skills copied in by `./build-claude.sh`) |
| `plugins/addison-codex/` | Codex package (generated: mention syntax + MCP shape) |

```bash
# edit skills/…
./build-plugins.sh        # Claude + Codex from skills/
claude --plugin-dir ./plugins/addison-claude
claude plugin validate ./plugins/addison-claude
./build-zip.sh            # dist/addison-plugin.zip for Desktop upload
```

CI regenerates both packages and fails on drift. **Never hand-edit** `plugins/addison-*/skills` or `plugins/addison-codex` (see `plugins/addison-codex/GENERATED.md`).

## Release

1. Bump `version` in `plugins/addison-claude/.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json`.
2. Run `./build-plugins.sh`, commit, merge to `main`.
3. Tag matching the version (for example `v0.10.2`) and push the tag. The release workflow publishes `addison-plugin.zip` as **Latest**.

`https://github.com/summationai/addison-plugin/releases/latest/download/addison-plugin.zip`
