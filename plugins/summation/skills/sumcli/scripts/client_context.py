#!/usr/bin/env python3
"""Print the SUMCLI_CLIENT_CONTEXT token for this plugin host.

Same surface detection as ``skills/api/scripts/sum_api.py:client_user_agent``:
``CODEX_PLUGIN_ROOT`` / ``CODEX_APP`` → ``codex-plugin``, otherwise
``claude-plugin``, plus the version from ``plugin.json``. Agents must export
this value rather than inventing a token.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys


def client_context() -> str:
    token = "claude-plugin"
    try:
        if os.environ.get("CODEX_PLUGIN_ROOT") or os.environ.get("CODEX_APP"):
            token = "codex-plugin"
        version = "0"
        root = (
            os.environ.get("PLUGIN_ROOT")
            or os.environ.get("CLAUDE_PLUGIN_ROOT")
            or os.environ.get("CODEX_PLUGIN_ROOT")
        )
        if not root:
            # <root>/skills/sumcli/scripts/client_context.py → <root>
            root = str(pathlib.Path(__file__).resolve().parents[3])
        manifest = pathlib.Path(root) / "plugin.json"
        if manifest.is_file():
            declared = json.loads(manifest.read_text(encoding="utf-8")).get("version")
            if isinstance(declared, str) and declared.strip():
                version = declared.strip()
        return f"{token}/{version}"
    except Exception:
        return token


def main() -> None:
    sys.stdout.write(client_context())


if __name__ == "__main__":
    main()
