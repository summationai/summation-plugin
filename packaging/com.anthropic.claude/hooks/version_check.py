#!/usr/bin/env python3
"""SessionStart hook: nudge (at most once/day) when a newer Summation plugin version is
published. Fail-soft by contract — always exits 0 with valid hook JSON and never blocks
session start. Uses only the stdlib (python3 is already required by the plugin's helper);
no jq/curl dependency."""
import json
import os
import pathlib
import ssl
import sys
import time
import urllib.request

REPO_RAW = "https://raw.githubusercontent.com/summationai/summation-plugin/main/.claude-plugin"


def emit(system_message: str | None = None) -> None:
    payload = {"continue": True}
    if system_message:
        payload["systemMessage"] = system_message
    sys.stdout.write(json.dumps(payload))
    sys.exit(0)


def version_tuple(value: str) -> tuple[int, ...]:
    parts = []
    for chunk in str(value).split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def main() -> None:
    root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if not root:
        emit()
    try:
        manifest = json.loads((pathlib.Path(root) / "plugin.json").read_text(encoding="utf-8"))
    except Exception:
        emit()
    name = manifest.get("name") or "summation"
    current = manifest.get("version")
    if not current:
        emit()

    internal = name.endswith("-internal")
    market_file = "marketplace.internal.json" if internal else "marketplace.json"
    market_name = "summationai-internal" if internal else "summationai"

    # At most one network check per calendar day, per edition.
    data_dir = os.environ.get("CLAUDE_PLUGIN_DATA") or str(pathlib.Path.home() / ".summation")
    stamp = pathlib.Path(data_dir) / f".version-check-{name}"
    today = time.strftime("%Y-%m-%d")
    try:
        if stamp.exists() and stamp.read_text(encoding="utf-8").strip() == today:
            emit()
    except Exception:
        pass

    # Record the check now (best-effort), before any network I/O, so the once-per-day
    # throttle holds even when offline — a failed fetch must not retry (and re-incur the
    # 2s timeout) on every SessionStart.
    try:
        stamp.parent.mkdir(parents=True, exist_ok=True)
        stamp.write_text(today, encoding="utf-8")
    except Exception:
        pass

    url = os.environ.get("SUMMATION_VERSION_CHECK_URL") or os.environ.get("ADDISON_VERSION_CHECK_URL") or f"{REPO_RAW}/{market_file}"
    try:
        with urllib.request.urlopen(url, timeout=2, context=ssl.create_default_context()) as resp:
            market = json.loads(resp.read().decode("utf-8"))
    except Exception:
        emit()  # offline / unreachable → stay silent

    latest = next((p.get("version") for p in market.get("plugins", []) if p.get("name") == name), None)
    if not latest:
        emit()

    if version_tuple(latest) > version_tuple(current):
        emit(
            f"Summation plugin {latest} is available (you have {current}). Update with "
            f"`claude plugin marketplace update {market_name} && claude plugin update {name}@{market_name}`, "
            f"then restart Claude Code."
        )
    emit()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        emit()
