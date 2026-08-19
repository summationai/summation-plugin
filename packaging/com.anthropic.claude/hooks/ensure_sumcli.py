#!/usr/bin/env python3
"""SessionStart hook: detect a missing or too-old sumcli and nudge.

Default is detect-and-tell — same posture as version_check.py. MCP is the
default transport; this hook does not curl|sh on every session. Set
SUMCLI_AUTO_INSTALL=1 to opt into install/upgrade.

Fail-soft by contract — always exits 0 with valid hook JSON and never blocks
session start. Stdlib only. Installer stdout is captured so it cannot corrupt
the hook envelope.

Contract (hooks/sumcli.json):
  minVersion from that file; newer PyPI releases are always compatible.
  Already new enough → silent. Otherwise print the bootstrap / update command.
  Opt-in install: missing → bootstrap; too-old uv-managed → `sumcli update`.
  A non-uv install is never bootstrapped over.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time

HOOK_DIR = pathlib.Path(__file__).resolve().parent
CONTRACT_NAME = "sumcli.json"
FAILURE_TTL_SECONDS = 60 * 60
# Shared across update + bootstrap so the pair cannot exceed the hook timeout.
# hooks.json SessionStart timeout is 240s, leaving margin for emit() / stamp.
INSTALL_BUDGET = 150
VERSION_TIMEOUT = 8
_TRUTHY = frozenset({"1", "true", "yes"})
_POSIX_SHELL_HINTS = ("bash", "zsh", "sh", "fish", "ksh")
_NOT_UV_MANAGED_MARKERS = ("NOT_UV_MANAGED", "not installed with uv")


def emit(system_message: str | None = None, context: str | None = None) -> None:
    payload: dict = {"continue": True}
    if system_message:
        payload["systemMessage"] = system_message
    if context:
        payload["hookSpecificOutput"] = {
            "hookEventName": "SessionStart",
            "additionalContext": context,
        }
    sys.stdout.write(json.dumps(payload))
    sys.exit(0)


def version_tuple(value: str) -> tuple[int, ...] | None:
    """All-digit dotted parts only — same rule as sumcli's ``_parse_version``.

    ``0.1.3rc1`` is not current; stripping non-digits would treat it as 0.1.3.
    """
    parts = str(value).split(".")
    if not parts or not all(p.isdigit() for p in parts):
        return None
    return tuple(int(p) for p in parts)


def meets_min(current: str, minimum: str) -> bool:
    cur = version_tuple(current)
    floor = version_tuple(minimum)
    if cur is None or floor is None:
        return False
    return cur >= floor


def load_contract(path: pathlib.Path | None = None) -> dict:
    target = path or (HOOK_DIR / CONTRACT_NAME)
    data = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not data.get("minVersion"):
        raise ValueError("sumcli.json missing minVersion")
    bootstrap = data.get("bootstrap") if isinstance(data.get("bootstrap"), dict) else {}
    return {
        "minVersion": str(data["minVersion"]),
        "upgradePolicy": str(data.get("upgradePolicy") or "latest-is-compatible"),
        "bootstrap": {
            "posix": str(bootstrap.get("posix") or "curl -fsSL https://install.summation.com/sumcli | sh"),
            "powershell": str(
                bootstrap.get("powershell") or "irm https://install.summation.com/sumcli.ps1 | iex"
            ),
            "cmd": str(
                bootstrap.get("cmd")
                or 'powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://install.summation.com/sumcli.ps1 | iex"'
            ),
        },
    }


def is_windows() -> bool:
    return os.name == "nt" or sys.platform == "win32"


def detect_shell() -> str:
    """Return 'powershell', 'cmd', or 'posix' for the copy-paste install command.

    The opt-in installer always *runs* the PowerShell bootstrap on Windows
    (works from cmd.exe by launching powershell.exe). This picks the command
    shown to the user on the default nudge path.
    """
    shell = (os.environ.get("SHELL") or "").lower()
    if any(name in shell for name in _POSIX_SHELL_HINTS) or os.environ.get("MSYSTEM"):
        return "posix"
    if not is_windows():
        return "posix"
    # PowerShell sets PSModulePath / PSExecutionPolicyPreference. cmd.exe does
    # not. ComSpec is cmd.exe even inside PowerShell, so it is not a signal.
    if os.environ.get("PSExecutionPolicyPreference") or os.environ.get("PSModulePath"):
        return "powershell"
    return "cmd"


def install_command_for_user(contract: dict, shell: str | None = None) -> str:
    kind = shell or detect_shell()
    return contract["bootstrap"].get(kind) or contract["bootstrap"]["posix"]


def parse_installed_version(output: str) -> str | None:
    text = (output or "").strip()
    if not text:
        return None
    try:
        payload = json.loads(text.splitlines()[-1])
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        result = payload.get("result")
        if isinstance(result, dict):
            version = result.get("version")
            if isinstance(version, str) and version.strip():
                return version.strip()
        version = payload.get("version")
        if isinstance(version, str) and version.strip():
            return version.strip()
    match = re.search(r"\b(\d+\.\d+\.\d+(?:[0-9a-zA-Z._+-]*)?)\b", text)
    return match.group(1) if match else None


def _bin_dirs() -> list[pathlib.Path]:
    home = pathlib.Path.home()
    dirs: list[pathlib.Path] = [
        home / ".local" / "bin",
        home / ".cargo" / "bin",
    ]
    uv = shutil.which("uv")
    if uv:
        try:
            out = subprocess.check_output(
                [uv, "tool", "dir", "--bin"],
                text=True,
                timeout=5,
                stderr=subprocess.DEVNULL,
            )
            extra = pathlib.Path(out.strip())
            if extra.as_posix():
                dirs.insert(0, extra)
        except (OSError, subprocess.SubprocessError):
            pass
    return dirs


def prepend_tool_bins() -> None:
    parts = os.environ.get("PATH", "").split(os.pathsep)
    extra = [str(p) for p in _bin_dirs() if p.is_dir()]
    os.environ["PATH"] = os.pathsep.join(extra + parts)


def which_sumcli() -> str | None:
    prepend_tool_bins()
    found = shutil.which("sumcli")
    if found:
        return found
    if is_windows():
        return shutil.which("sumcli.exe")
    return None


def read_version(binary: str) -> str | None:
    env = os.environ.copy()
    env["SUMCLI_OUTPUT"] = "json"
    env["SUMCLI_NO_UPDATE_CHECK"] = "1"
    try:
        proc = subprocess.run(
            [binary, "--version"],
            capture_output=True,
            text=True,
            timeout=VERSION_TIMEOUT,
            env=env,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return parse_installed_version(proc.stdout or "") or parse_installed_version(proc.stderr or "")


def _powershell_prefix() -> list[str] | None:
    for name in ("pwsh", "powershell"):
        path = shutil.which(name)
        if path:
            return [path, "-NoProfile", "-ExecutionPolicy", "Bypass"]
    return None


def _remaining(deadline: float) -> float:
    return max(0.0, deadline - time.monotonic())


def run_bootstrap(contract: dict, *, timeout: float | None = None) -> tuple[bool, str]:
    """Install latest sumcli via the OS bootstrap. Returns (ok, detail)."""
    budget = INSTALL_BUDGET if timeout is None else timeout
    if budget <= 0:
        return False, "sumcli install timed out."
    if is_windows():
        prefix = _powershell_prefix()
        if prefix is None:
            return False, "PowerShell not found (needed to run the sumcli installer from cmd.exe)."
        argv = prefix + ["-Command", contract["bootstrap"]["powershell"]]
    else:
        argv = ["sh", "-c", contract["bootstrap"]["posix"]]
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=budget,
        )
    except subprocess.TimeoutExpired:
        return False, "sumcli install timed out."
    except OSError as exc:
        return False, f"could not run installer: {exc}"
    detail = (proc.stderr or proc.stdout or "").strip()
    if proc.returncode != 0:
        tail = detail[-400:] if detail else f"exit {proc.returncode}"
        return False, tail
    return True, detail


def run_update(binary: str, *, timeout: float | None = None) -> tuple[bool, str]:
    budget = INSTALL_BUDGET if timeout is None else timeout
    if budget <= 0:
        return False, "sumcli update timed out."
    env = os.environ.copy()
    env["SUMCLI_OUTPUT"] = "json"
    env["SUMCLI_NO_UPDATE_CHECK"] = "1"
    try:
        proc = subprocess.run(
            [binary, "update"],
            capture_output=True,
            text=True,
            timeout=budget,
            env=env,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()[-400:]
        return False, detail or f"sumcli update exited {proc.returncode}"
    return True, (proc.stdout or "").strip()


def not_uv_managed(detail: str) -> bool:
    """sumcli update refused because this binary is brew/pip/pipx, not uv."""
    text = detail or ""
    return any(marker in text for marker in _NOT_UV_MANAGED_MARKERS)


def _auto_install() -> bool:
    """Opt-in only. Default SessionStart never runs the installer."""
    return os.environ.get("SUMCLI_AUTO_INSTALL", "").strip().lower() in _TRUTHY


def _data_dir() -> pathlib.Path:
    """Plugin data dir for the fail-stamp. Never sumcli's config home.

    Prefer the Agent Plugins spec variable, then the Claude-prefixed alias,
    then a plugin-owned subdirectory of ``~/.summation``.
    """
    raw = os.environ.get("PLUGIN_DATA") or os.environ.get("CLAUDE_PLUGIN_DATA")
    if raw:
        return pathlib.Path(raw)
    return pathlib.Path.home() / ".summation" / "plugin"


def _fail_stamp() -> pathlib.Path:
    return _data_dir() / ".sumcli-ensure-fail"


def _nudge_stamp() -> pathlib.Path:
    return _data_dir() / ".sumcli-ensure-nudge"


def _recent_nudge() -> bool:
    today = time.strftime("%Y-%m-%d")
    try:
        return _nudge_stamp().read_text(encoding="utf-8").strip() == today
    except OSError:
        return False


def _record_nudge() -> None:
    path = _nudge_stamp()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(time.strftime("%Y-%m-%d"), encoding="utf-8")
    except OSError:
        pass


def _nudge(minimum: str, current: str | None, cmd: str) -> str:
    if current:
        return (
            f"sumcli {current} is below the plugin minimum {minimum}. "
            f"The plugin prefers sumcli for data work — upgrade with: sumcli update"
        )
    return (
        f"sumcli is not installed (plugin requires ≥ {minimum}). "
        f"The plugin prefers sumcli for data work — install with: {cmd}"
    )


def _recent_failure() -> bool:
    path = _fail_stamp()
    try:
        age = time.time() - path.stat().st_mtime
    except OSError:
        return False
    return age < FAILURE_TTL_SECONDS


def _record_failure() -> None:
    path = _fail_stamp()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(int(time.time())), encoding="utf-8")
    except OSError:
        pass


def _clear_failure() -> None:
    try:
        _fail_stamp().unlink(missing_ok=True)
    except OSError:
        pass
    try:
        _nudge_stamp().unlink(missing_ok=True)
    except OSError:
        pass


def _on_login_path(login_path: str) -> bool:
    """True when sumcli is resolvable without the hook mutating PATH."""
    if shutil.which("sumcli", path=login_path):
        return True
    return bool(is_windows() and shutil.which("sumcli.exe", path=login_path))


def _path_hint() -> str:
    return (
        "If the next `sumcli` call fails, add `uv tool dir --bin` "
        "(usually ~/.local/bin) to PATH."
    )


def _with_path_note(message: str, login_path: str) -> str:
    if _on_login_path(login_path):
        return message
    return f"{message} {_path_hint()}"


def ensure(contract: dict | None = None) -> str | None:
    """Return a user-facing message, or None when nothing to say.

    Never raises. Callers that need the hook envelope should use main().
    """
    spec = contract or load_contract()
    minimum = spec["minVersion"]
    cmd = install_command_for_user(spec)
    login_path = os.environ.get("PATH", "")
    deadline = time.monotonic() + INSTALL_BUDGET
    binary = which_sumcli()
    current = read_version(binary) if binary else None

    if current and meets_min(current, minimum):
        _clear_failure()
        return None

    if not _auto_install():
        if _recent_nudge():
            return None
        _record_nudge()
        return _nudge(minimum, current, cmd)

    if _recent_failure():
        if current:
            return (
                f"sumcli {current} is below the plugin minimum {minimum}. "
                f"Retry later or run: sumcli update"
            )
        return None  # already told them this hour; stay quiet

    if current and binary:
        ok, detail = run_update(binary, timeout=_remaining(deadline))
        if not ok and not_uv_managed(detail):
            _record_failure()
            return (
                f"sumcli {current} is below the plugin minimum {minimum} and was "
                f"not installed with uv, so this hook will not bootstrap a second "
                f"copy. Upgrade with the same installer you used (brew / pip / pipx)."
            )
        if not ok:
            ok, _detail = run_bootstrap(spec, timeout=_remaining(deadline))
        prepend_tool_bins()
        latest = read_version(which_sumcli() or binary)
        if latest and meets_min(latest, minimum):
            _clear_failure()
            return _with_path_note(
                f"Upgraded sumcli {current} → {latest} (plugin requires ≥ {minimum}).",
                login_path,
            )
        _record_failure()
        return (
            f"sumcli {current} is below the plugin minimum {minimum} and upgrade failed. "
            f"Run: sumcli update   or   {cmd}"
        )

    ok, _detail = run_bootstrap(spec, timeout=_remaining(deadline))
    prepend_tool_bins()
    installed = which_sumcli()
    latest = read_version(installed) if installed else None
    if ok and latest and meets_min(latest, minimum):
        _clear_failure()
        return _with_path_note(
            f"Installed sumcli {latest} (plugin requires ≥ {minimum}).",
            login_path,
        )
    _record_failure()
    if latest and not meets_min(latest, minimum):
        return (
            f"Installed sumcli {latest}, but the plugin requires ≥ {minimum}. "
            f"Run: sumcli update   or   {cmd}"
        )
    return f"Could not install sumcli (plugin requires ≥ {minimum}). Run: {cmd}"


def routing_context(contract: dict | None = None) -> str:
    """One line of model context stating the surface preference for this session.

    The CLI-first funnel lives in skill text, but MCP tools are ambient — a
    session that never loads a skill never sees the preference (proven by a
    live session importing a CSV entirely over MCP with a shell available).
    This is the one mechanism guaranteed to be in context every session.
    Computed after ensure() so a just-installed binary is reported correctly.
    Never raises.
    """
    try:
        spec = contract or load_contract()
        minimum = spec["minVersion"]
        binary = which_sumcli()
        current = read_version(binary) if binary else None
        if current and meets_min(current, minimum):
            return (
                f"Summation plugin routing: sumcli {current} is installed and meets "
                f"the plugin minimum ({minimum}). Prefer sumcli for Summation data "
                "work in this shell; the Summation MCP tools are the fallback. Load "
                "the summation:api skill before data work — routing and safety "
                "rules live there. The CLI session is separate from MCP OAuth: "
                "check `sumcli auth whoami`, sign in with `sumcli auth login`."
            )
        if current:
            return (
                f"Summation plugin routing: sumcli {current} is installed but below "
                f"the plugin minimum {minimum}, so Summation data work uses the MCP "
                "tools for now. Upgrading requires the user's explicit yes "
                "(`sumcli update`, or their original installer if not uv-managed) — "
                "see the summation:api skill."
            )
        return (
            "Summation plugin routing: sumcli is not installed, so Summation data "
            "work uses the MCP tools. Installing sumcli requires the user's "
            "explicit yes — see the summation:api skill before offering."
        )
    except Exception:
        return ""


def main() -> None:
    try:
        spec = load_contract()
        message = ensure(spec)
        emit(message, context=routing_context(spec))
    except Exception:
        emit()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        emit()
