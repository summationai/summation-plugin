# sumcli (plugin ↔ CLI)

**sumcli is the plugin's preferred surface when a shell is available.** MCP is the fallback for shell-less hosts (Claude Desktop, sandboxes) and anywhere the CLI cannot run. Needs **≥ 0.1.3**; newer CLI releases are always compatible (`sumcli update` → PyPI latest).

Install on **first need**: before the first `sumcli` command (every host, including Codex), check the version here and install if needed — tell the user before running a bootstrap. Claude Code **SessionStart** nudges once a day if sumcli is missing or too old; it does not install (opt in to auto-install with `SUMCLI_AUTO_INSTALL=1`).

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

## 4. Sign in

First CLI use needs `sumcli login` (browser device-code). This credential is separate from the MCP host OAuth session — being signed in over MCP does not sign in the CLI, and vice versa. Config lives in `~/.summation/summation-config`; never paste tokens into chat.
