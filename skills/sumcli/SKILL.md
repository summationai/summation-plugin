---
name: sumcli
description: Use the sumcli CLI for scripted Summation automation. Always pass --intent with the human's request in their own words. Use when running sumcli, the user asks for the CLI, or MCP is the wrong tool.
metadata:
  short-description: Scripted Summation via sumcli
---

# sumcli

MCP is the default. Use **sumcli** for scripted automation, or when the user asks for the CLI. Install and version: `../api/references/sumcli.md`.

## State intent (required of agents)

The agent already holds the human's request. Send those words so later events can join to a goal — not a summary of the command you are running.

- User said: `convert my weekly recap` → `--intent "convert my weekly recap"`
- Wrong: `--intent "list projects"` or `--intent "attach the catalog table"`

```bash
export SUMCLI_INTENT="convert my weekly recap"   # once per session, their words
sumcli --intent "convert my weekly recap" projects list
```

`--intent` is a **root** option and must precede the subcommand. `SUMCLI_INTENT` covers every later call in the process. Prefer both: set the env at the start of the session, and pass `--intent` on each data command.

If `SUMCLI_NO_INTENT` is set (`1` / `true` / `yes`), do **not** pass `--intent` and do not set `SUMCLI_INTENT`. That is an org kill switch: the CLI will not send `X-Summation-Intent`.

The CLI does not fail without it (unattended pipelines have no ask to state), but it warns on stderr, and the run cannot be joined to a goal. You are an agent: you have the human's words, so send them.

- **Limit:** 500 bytes after encoding. Plain English gets about 500 characters; accented or non-Latin text gets fewer. If the request is longer, use the first part of their words.
- **Exempt** (no `--intent` needed): discovery, `--help`, `--version`, `update`, and the `auth`, `config`, and `filesystem` groups. `auth` and `config` set up the session before there is a goal; `filesystem` talks to the external provider, not to sum-api.
- An intent over 500 bytes is refused (`INTENT_TOO_LONG`). A missing one only warns.

Do not copy placeholder text from this file. Use the words in front of you.

## Caller context

Identify this surface so sum-api can attribute the call. Short product token only — never free text or anything user-identifying. Do not invent the token — print it:

```bash
export SUMCLI_CLIENT_CONTEXT="$(python3 "${PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT:-$CODEX_PLUGIN_ROOT}}/skills/sumcli/scripts/client_context.py")"
```

The script detects Claude vs Codex (`CODEX_PLUGIN_ROOT` / `CODEX_APP`) and appends the plugin version from `plugin.json`, matching the MCP helper (`claude-plugin/<version>` or `codex-plugin/<version>`).

## Agent rules

1. **Discover live commands** — do not hardcode the tree:
   ```bash
   sumcli | jq '.result.resources'
   sumcli <resource> --help
   ```
2. **Parse JSON** — piped/agent output is a JSON envelope. Pipe through `jq`. Force with `SUMCLI_OUTPUT=json` or `sumcli --output json …` (`--output` must precede the subcommand).
3. **Root options before the subcommand:** `--intent`, `--profile`, `--base-url`, `--output`, `--project`.
4. **Destructive ops need `--confirm`.** If the CLI refuses, show the user what it would do and re-run with `--confirm` only after they agree.
5. **Never put secrets** in commits, logs, or skill files. Config lives in `~/.summation/summation-config`.
6. **Parallel agents:** do not call `config use` on a shared config. Pass `--profile` and/or set `SUMMATION_PROFILE` / `SUMMATION_PROJECT` per process.

```text
sumcli --intent "human's request" [--profile NAME] [--base-url URL] [--output json|human] <resource> <action> [options]
```
