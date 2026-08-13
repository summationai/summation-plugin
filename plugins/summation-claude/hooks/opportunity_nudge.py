#!/usr/bin/env python3
"""SessionStart hook: rare soft invite to run /summation:opportunities.

Fail-soft — always exits 0 with valid hook JSON. Does not read chat history
(that stays in the opportunities skill after user consent). Throttled to once
per 14 days per plugin name. Skips the very first day after install stamp so
onboarding is not double-prompted on day zero.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
import time

NUDGE_INTERVAL_DAYS = 14
INSTALL_GRACE_DAYS = 1


def emit(system_message: str | None = None) -> None:
    payload: dict = {"continue": True}
    if system_message:
        payload["systemMessage"] = system_message
    sys.stdout.write(json.dumps(payload))
    sys.exit(0)


def main() -> None:
    root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if not root:
        emit()

    data_dir = pathlib.Path(
        os.environ.get("CLAUDE_PLUGIN_DATA") or (pathlib.Path.home() / ".summation")
    )
    try:
        name = "summation"
        manifest = pathlib.Path(root) / ".claude-plugin" / "plugin.json"
        if manifest.is_file():
            name = json.loads(manifest.read_text(encoding="utf-8")).get("name") or name
    except Exception:
        name = "summation"

    try:
        data_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        emit()

    install_stamp = data_dir / f".opportunity-install-{name}"
    nudge_stamp = data_dir / f".opportunity-nudge-{name}"
    now = time.time()

    # First ever run: record install time and stay silent (start skill owns first offer).
    if not install_stamp.exists():
        try:
            install_stamp.write_text(str(int(now)), encoding="utf-8")
        except Exception:
            pass
        emit()

    try:
        installed_at = float(install_stamp.read_text(encoding="utf-8").strip())
    except Exception:
        installed_at = now

    if now - installed_at < INSTALL_GRACE_DAYS * 86400:
        emit()

    if nudge_stamp.exists():
        try:
            last = float(nudge_stamp.read_text(encoding="utf-8").strip())
            if now - last < NUDGE_INTERVAL_DAYS * 86400:
                emit()
        except Exception:
            pass

    try:
        nudge_stamp.write_text(str(int(now)), encoding="utf-8")
    except Exception:
        pass

    emit(
        "Summation can suggest workflows from recent local chats in this IDE "
        "(scan stays on your machine). Say “suggest opportunities” or run /summation:opportunities."
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        emit()
