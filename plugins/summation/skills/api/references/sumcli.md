# sumcli (plugin ↔ CLI)

The plugin's day-to-day work is MCP. **sumcli** is the scripted/automation CLI and needs **≥ 0.1.3**. Newer CLI releases are always compatible (`sumcli update` → PyPI latest). MCP work does not require sumcli.

Claude Code **SessionStart** nudges once a day if sumcli is missing or too old; it does not install. Opt in to auto-install with `SUMCLI_AUTO_INSTALL=1`. Before any `sumcli` command (every host, including Codex), check the version here and install if needed.

## 1. Detect the shell

| Environment | Install command |
|---|---|
| macOS / Linux / Git Bash / WSL | `curl -fsSL https://install.summation.com/sumcli \| sh` |
| Windows PowerShell / `pwsh` | `irm https://install.summation.com/sumcli.ps1 \| iex` |
| Windows cmd.exe | `powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://install.summation.com/sumcli.ps1 \| iex"` |

Do **not** paste `curl | sh` into PowerShell or cmd.exe. Signals: `SHELL`/`MSYSTEM` → posix; `PSModulePath` or `PSExecutionPolicyPreference` → PowerShell; otherwise on Windows → cmd.

## 2. Check the installed version

```bash
SUMCLI_OUTPUT=json SUMCLI_NO_UPDATE_CHECK=1 sumcli --version
```

Read `result.version`. Compare as dotted integers. Need **≥ 0.1.3**.

## 3. Missing → install; too old → update

- Missing: run the matching bootstrap from the table (installs uv if needed, then `summation-cli`).
- Present but `< 0.1.3`: `sumcli update` if this binary is uv-managed. If update refuses (`NOT_UV_MANAGED`), upgrade with the same installer you used (brew / pip / pipx) — do not bootstrap a second copy.
- Already ≥ 0.1.3: continue. Do not pin an upper bound.

After install, if `sumcli` is not on `PATH`, add `uv tool dir --bin` (usually `~/.local/bin`) and retry `--version`.

## 4. State intent

Agents must send the human's request **in their own words** so later events can join to a goal. See the **`sumcli` skill**. If `SUMCLI_NO_INTENT` is set, skip `--intent` / `SUMCLI_INTENT` — the CLI will not send the header.

```bash
export SUMCLI_INTENT="convert my weekly recap"          # once per session
export SUMCLI_CLIENT_CONTEXT="$(python3 "${PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT:-$CODEX_PLUGIN_ROOT}}/skills/sumcli/scripts/client_context.py")"
sumcli --intent "convert my weekly recap" projects list
```

- Right: `--intent "convert my weekly recap"` (what they asked).
- Wrong: `--intent "list projects"` (a command summary — joins nothing).
- `--intent` is a root option and must precede the subcommand. Limit is 500 bytes after encoding.
- **Exempt:** discovery, `--help`, `--version`, `update`, `auth`, `config`, `filesystem`.
- Missing intent warns on stderr and still runs. An oversized value is refused (`INTENT_TOO_LONG`).
- Caller context is a versioned product token (`claude-plugin/<version>` or `codex-plugin/<version>`). Print it from the script above — do not invent one.
