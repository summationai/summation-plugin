#!/usr/bin/env python3
"""SessionStart hook: install or upgrade sumcli to the plugin's minimum version.

Fail-soft by contract — always exits 0 with valid hook JSON and never blocks
session start. Stdlib only. Installer stdout is captured so it cannot corrupt
the hook envelope.

Contract (hooks/sumcli.json):
  minVersion 0.1.3; newer PyPI releases are always compatible.
  Missing or too-old → bootstrap / `sumcli update`. Already new enough → silent.
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
INSTALL_TIMEOUT = 180
VERSION_TIMEOUT = 8
_TRUTHY = frozenset({"1", "true", "yes"})
_POSIX_SHELL_HINTS = ("bash", "zsh", "sh", "fish", "ksh")


def emit(system_message: str | None = None) -> None:
    payload: dict = {"continue": True}
    if system_message:
        payload["systemMessage"] = system_message
    sys.stdout.write(json.dumps(payload))
    sys.exit(0)


def version_tuple(value: str) -> tuple[int, ...]:
    parts = []
    for chunk in str(value).split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) or (0,)


def meets_min(current: str, minimum: str) -> bool:
    return version_tuple(current) >= version_tuple(minimum)


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

    The hook always *runs* the PowerShell bootstrap on Windows (works from
    cmd.exe by launching powershell.exe). This only picks the command shown
    to the user if install fails.
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


def run_bootstrap(contract: dict) -> tuple[bool, str]:
    """Install latest sumcli via the OS bootstrap. Returns (ok, detail)."""
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
            timeout=INSTALL_TIMEOUT,
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


def run_update(binary: str) -> tuple[bool, str]:
    env = os.environ.copy()
    env["SUMCLI_OUTPUT"] = "json"
    env["SUMCLI_NO_UPDATE_CHECK"] = "1"
    try:
        proc = subprocess.run(
            [binary, "update"],
            capture_output=True,
            text=True,
            timeout=INSTALL_TIMEOUT,
            env=env,
        )
    except (OSError, subprocess.SubprocessError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()[-400:]
        return False, detail or f"sumcli update exited {proc.returncode}"
    return True, (proc.stdout or "").strip()


def _opted_out() -> bool:
    return os.environ.get("SUMCLI_NO_AUTO_INSTALL", "").strip().lower() in _TRUTHY


def _data_dir() -> pathlib.Path:
    raw = os.environ.get("CLAUDE_PLUGIN_DATA") or str(pathlib.Path.home() / ".summation")
    return pathlib.Path(raw)


def _fail_stamp() -> pathlib.Path:
    return _data_dir() / ".sumcli-ensure-fail"


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


def ensure(contract: dict | None = None) -> str | None:
    """Return a user-facing message, or None when nothing to say.

    Never raises. Callers that need the hook envelope should use main().
    """
    spec = contract or load_contract()
    minimum = spec["minVersion"]
    cmd = install_command_for_user(spec)
    binary = which_sumcli()
    current = read_version(binary) if binary else None

    if current and meets_min(current, minimum):
        _clear_failure()
        return None

    if _opted_out():
        if current:
            return (
                f"sumcli {current} is below the plugin minimum {minimum}. "
                f"Auto-install is off (SUMCLI_NO_AUTO_INSTALL). Run: sumcli update"
            )
        return (
            f"sumcli is not installed (plugin requires ≥ {minimum}). "
            f"Auto-install is off (SUMCLI_NO_AUTO_INSTALL). Run: {cmd}"
        )

    if _recent_failure():
        if current:
            return (
                f"sumcli {current} is below the plugin minimum {minimum}. "
                f"Retry later or run: sumcli update"
            )
        return None  # already told them this hour; stay quiet

    if current and binary:
        ok, _detail = run_update(binary)
        if not ok:
            ok, _detail = run_bootstrap(spec)
        prepend_tool_bins()
        latest = read_version(which_sumcli() or binary)
        if latest and meets_min(latest, minimum):
            _clear_failure()
            return f"Upgraded sumcli {current} → {latest} (plugin requires ≥ {minimum})."
        _record_failure()
        return (
            f"sumcli {current} is below the plugin minimum {minimum} and upgrade failed. "
            f"Run: sumcli update   or   {cmd}"
        )

    ok, _detail = run_bootstrap(spec)
    prepend_tool_bins()
    installed = which_sumcli()
    latest = read_version(installed) if installed else None
    if ok and latest and meets_min(latest, minimum):
        _clear_failure()
        return f"Installed sumcli {latest} (plugin requires ≥ {minimum})."
    _record_failure()
    if latest and not meets_min(latest, minimum):
        return (
            f"Installed sumcli {latest}, but the plugin requires ≥ {minimum}. "
            f"Run: sumcli update   or   {cmd}"
        )
    return f"Could not install sumcli (plugin requires ≥ {minimum}). Run: {cmd}"


def main() -> None:
    try:
        emit(ensure())
    except Exception:
        emit()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        emit()
