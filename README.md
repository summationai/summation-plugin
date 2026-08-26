# Summation plugin for Claude Code and Codex

Plugin marketplace for Summation. One plugin, `summation`, brings the analyst into Claude Code, Claude Desktop, and OpenAI Codex: data questions, report generation and export (PDF/DOCX/Markdown), catalog discovery, and bounded SQL — through sumcli when a shell is available, over the hosted Summation MCP server otherwise.

Install the plugin, approve Summation in the browser (host OAuth for MCP), then ask in plain English. CLI work signs in separately, once, via `sumcli auth login` (browser device-code) — the two sessions are independent. No API keys and no secrets pasted into chat. Auth is host-managed MCP OAuth; the plugin ships a headerless connection to production:

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

## sumcli

When a shell is available, [sumcli](https://github.com/summationai/summation-cli) (**≥ 0.1.3**) is the plugin's preferred surface — it exposes the full sum-api contract, where the hosted MCP server is a curated subset. MCP is the fallback for shell-less hosts (Claude Desktop, sandboxes). Skills install sumcli at first need, after an explicit yes; newer CLI releases are always compatible (`sumcli update` to PyPI latest).

Claude Code **SessionStart** detects a missing or too-old binary and prints the install command. It does not run the installer. Opt in with `SUMCLI_AUTO_INSTALL=1`.

| Shell | Bootstrap |
|---|---|
| macOS / Linux / Git Bash / WSL | `curl -fsSL https://install.summation.com/sumcli \| sh` |
| Windows PowerShell | `irm https://install.summation.com/sumcli.ps1 \| iex` |
| Windows cmd.exe | `powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://install.summation.com/sumcli.ps1 \| iex"` |

The floor lives in `packaging/com.anthropic.claude/hooks/sumcli.json` (`minVersion`). A plugin release that needs a higher floor bumps that value; it does not pin an upper bound.

**1.0.0 is a breaking package change.** The installable tree is an [Agent Plugins](https://agent-plugins.org/) 1.0.0 directory (`plugin.json` + `mcp.json` + `skills/`). There is no `.claude-plugin` / `.codex-plugin` manifest inside the package, and no `addison` plugin id. Hosts that only load those older manifests cannot install this version.

Two host-discovery files ride along until the hosts read the spec files directly: root `hooks/` (Claude SessionStart) and root `.mcp.json` (Claude MCP registration). Both are generated from `packaging/`. Claude Code loads `skills/` from the spec tree but does not yet register servers from `mcp.json`, so without `.mcp.json` the skills appear and then fail at their first tool call.

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

Then `$summation-signin` or any data ask. Skills are the same portable tree; Codex mentions are `$summation-…`. MCP is `mcp.json` (streamable HTTP). Auth is the same browser flow (`codex mcp login summation` if needed).

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

Claude Code invokes a skill as `/summation:<name>`; Codex invokes it as `$summation-<name>`. `api` is model-invoked only.

| Skill | Does |
|---|---|
| `start` | guided onboarding: connect → map data → meet the analyst → first report |
| `opportunities` | suggest workflows from recent local chats + live catalog (consent first) |
| `api` | MCP tool map + safety rules |
| `signin` | connect or re-authenticate Summation (`login` is an alias) |
| `signout` | disconnect Summation (`logout` is an alias) |
| `diagnose` | check connectivity and what data is visible (`doctor` is an alias) |
| `report` | generate a report → export markdown/PDF/DOCX |
| `verify` | grade a disk file or a report that lives in Summation (`validate` is an alias) |
| `query` | read-only query or open-ended analysis |
| `catalog` | search tables, views, catalog |
| `connect` | add a data source (secrets stay in the Summation web app) |
| `schedule` | recurring playbook runs with email delivery |

Credentials for the happy path live in the host MCP client, not in this repo. Do not commit config files or tokens.

## Org announcement template

> **Summation is now in Claude.** Open a new chat and type **/summation:start** — it walks you through connecting, shows a map of your data, introduces the analyst, and runs your first report. Already connected? Just ask data questions, or use /summation:report, /summation:query, /summation:catalog, /summation:verify.

## For agent harnesses (customer `AGENTS.md` snippet)

```md
When working on data analysis, metrics, or report commentary, use the Summation
plugin first (catalog discovery before SQL; never guess table names). Prefer
exported report content over raw internals, cite request_ids on failures, and
run the `verify` skill before any report is shared externally. Drafts need explicit
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
| `plugins/summation/` | Generated Agent Plugins 1.0.0 package |

```bash
# edit skills/ or packaging/…
./build-plugins.sh        # plugins/summation from skills/ + packaging/
./build-zip.sh            # dist/summation-plugin.zip
```

CI regenerates the package and fails on drift. **Never hand-edit** `plugins/summation` (see `plugins/summation/GENERATED.md`).

The package is spec-only. Claude hooks are authored under `packaging/com.anthropic.claude/` and copied to `hooks/` (Claude SessionStart discovery) plus `com.anthropic.claude/hooks/`. Codex listing metadata and `oauth_resource` live in `extensions.com.openai.codex`. Repo-root `.claude-plugin/marketplace.json` and `.agents/plugins/marketplace.json` are marketplace catalogs, not plugin manifests.

## Release

1. Bump `version` in `packaging/plugin.json`.
2. Run `./build-plugins.sh`, commit, merge to `main`.
3. Tag matching the version (for example `v1.0.0`) and push the tag. The release workflow publishes `summation-plugin.zip` as **Latest**.

`https://github.com/summationai/summation-plugin/releases/latest/download/summation-plugin.zip`
