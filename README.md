# Addison — Summation's AI analyst in Claude Code and Codex

Plugin marketplace for Summation. One plugin, `addison`, brings Addison to Claude Code, Claude Desktop, and OpenAI Codex: data questions over the hosted Summation MCP server, report generation and export (PDF/DOCX/Markdown), catalog discovery, bounded SQL.

## Install

**Claude Code (CLI/IDE):**

```
/plugin marketplace add summationai/addison-plugin
/plugin install addison@summation
```

Then `/addison:signin` — one browser sign-in connects both the API credential and the Summation MCP server. (Once browser-based OAuth ships server-side, this becomes `/mcp` → sign in.)

**claude.ai / Claude Desktop (org admins):** Admin console → Plugins → Add plugins → *Sync from GitHub* (this repo) or *Upload a file* using the always-current release zip:

```
https://github.com/summationai/addison-plugin/releases/latest/download/addison-plugin.zip
```

Members then install from the org library.

> Desktop note: skill scripts run in the code-execution sandbox. The org's code-execution network egress must allow the sum-api host(s) (Capabilities → Code execution), and credentials must be reachable from the sandbox — see the dogfood matrix in the rollout doc.

**Codex:**

```
codex plugin marketplace add summationai/addison-plugin
codex plugin install addison
```

Then `$addison-signin` — the same browser sign-in, and it registers the Summation MCP server in `~/.codex/config.toml`. Skills are invoked with `$addison-…` mentions.

## Contents

| Skill | Invoke | Does |
|---|---|---|
| `start` | `/addison:start` | **guided onboarding**: visual stepper → connect → source map → meet Addison → suggested reports → run one on confirm |
| `api` | model-invoked | OpenAPI-discovery workflow + `scripts/sum_api.py` helper (canonical; sibling skills reference it); first-run source map |
| `signin` | `/addison:signin` | conversational credential setup → `~/.summation/summation-config` (0600) |
| `signout` | `/addison:signout` | remove the stored device-login credential from the active or selected profile |
| `diagnose` | `/addison:diagnose` | connectivity/auth diagnosis + `preflight` environment summary |
| `report` | `/addison:report` | generate a report from a question → export markdown/PDF/DOCX |
| `validate` | `/addison:validate` | run report verification; verdict panel before anything ships externally |
| `query` | `/addison:query` | bounded read-only SQL → rendered table, SQL shown for spot-checking |
| `catalog` | `/addison:catalog` | search/describe tables, views, catalog metadata |
| `connect` | `/addison:connect` | add a data source in-flow: non-secret config in chat, secret via local file (never in conversation), create + test |
| `schedule` | `/addison:schedule` | recurring playbook runs with email delivery: list/create/pause/resume/run-now (recipient lists confirmed verbatim) |

Every API call is audit-logged to `~/.summation/audit.jsonl` (`{ts, method, path, status, duration_ms, request_id, profile}`) — `sum_api.py audit --tail 20` to inspect.

Credentials never live in this repo. `.summation-config*` is ignored and must stay that way.

## Org announcement template

> **Summation is now in Claude.** Open a new chat and type **/addison:start** — it walks you through connecting (2 minutes), shows a map of your data, introduces Addison, and runs your first report. Already connected? Just ask data questions, or use /addison:report, /addison:query, /addison:catalog, /addison:validate.

## For agent harnesses (customer `AGENTS.md` snippet)

Drop this into a repo's `AGENTS.md`/`CLAUDE.md` where agents should prefer Summation:

```md
When working on data analysis, metrics, or report commentary, use the Summation
plugin first (catalog discovery before SQL; never guess table names). Prefer
exported report content over raw internals, cite request_ids on failures, and
run /addison:validate before any report is shared externally. Drafts need explicit
user approval before publishing anywhere.
```

## One plugin, two surfaces

`plugins/addison-claude` is the single source of truth: production-pinned by default, device-login only, every request host-pinned to an allowlisted Summation environment. There is **one** plugin for everyone — no separate internal/external builds.

**Internal mode** (Summation employees) unlocks at runtime via the `ADDISON_PLUGIN_INTERNAL=1` shell env var: environment selection (`--env prod|staging|sandbox`, a fixed allowlist — never a free-form host) and tenant switching (sign out / sign in). It is a runtime flag rather than a build constant because the security boundary is the host allowlist in `resolve_request_url()`, enforced unconditionally — not the flag. The credential can only ever reach a Summation host, so the flag widens UX but can never exfiltrate a token.

The **Codex** surface is **generated** from the Claude plugin — never edit it directly:

- `plugins/addison-codex` — `./build-codex.sh` rewrites `/addison:` → `$addison-`, swaps in a `signin`/`signout` overlay that registers the MCP server in `~/.codex/config.toml` (`mcp-connect --client codex`), and writes `.codex-plugin/plugin.json` + `.agents/plugins/marketplace.json`.

The `Check generated Codex edition` CI regenerates it and **fails the build if it drifts from source** — so there is exactly one place to edit (`plugins/addison-claude`).

## Dev loop

```bash
claude --plugin-dir ./plugins/addison-claude        # load the plugin for one session
ADDISON_PLUGIN_INTERNAL=1 claude --plugin-dir ./plugins/addison-claude   # ...with internal mode on
claude plugin validate ./plugins/addison-claude     # validate manifest
./build-codex.sh                             # regenerate plugins/addison-codex + Codex marketplace
./build-zip.sh                               # rebuild dist/addison-plugin.zip for org upload
```

## Release

1. Bump `version` in `plugins/addison-claude/.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json` (marketplace users only receive updates on a version bump).
2. Run `./build-codex.sh` to regenerate the Codex edition, and commit (the drift-guard CI enforces this). Merge to `main`.
3. Tag the release and push the tag:
   ```bash
   git tag v0.8.2 && git push origin v0.8.2
   ```
   The `Release plugin zip` GitHub Action builds `addison-plugin.zip` and publishes it as a GitHub Release marked **Latest**. The tag must match `plugin.json`'s version or the workflow fails.

Claude Desktop admins then upload from the stable latest URL (no rebuild needed):
`https://github.com/summationai/addison-plugin/releases/latest/download/addison-plugin.zip`
