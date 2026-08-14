# sumcli (plugin ↔ CLI)

The plugin's day-to-day work is MCP. **sumcli** is the scripted/automation CLI. This plugin requires **sumcli ≥ 0.1.3**. Newer CLI releases are always compatible (`sumcli update` → PyPI latest).

Claude Code **SessionStart** installs or upgrades automatically (opt out: `SUMCLI_NO_AUTO_INSTALL=1`). Codex and hosts without that hook: do it here before any `sumcli` command.

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
- Present but `< 0.1.3`: `sumcli update` (installs `@latest` over an exact pin). If that fails, re-run the bootstrap.
- Already ≥ 0.1.3: continue. Do not pin an upper bound.

After install, if `sumcli` is not on `PATH`, add `uv tool dir --bin` (usually `~/.local/bin`) and retry `--version`.
