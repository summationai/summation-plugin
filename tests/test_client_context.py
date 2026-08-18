"""Unit tests for the sumcli caller-context script (stdlib only)."""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "sumcli" / "scripts" / "client_context.py"


def _load():
    spec = importlib.util.spec_from_file_location("client_context", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


cc = _load()


class ClientContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        (self.root / "plugin.json").write_text(
            json.dumps({"version": "1.0.2"}), encoding="utf-8"
        )

    def test_claude_token_includes_plugin_version(self) -> None:
        env = {"PLUGIN_ROOT": str(self.root)}
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(cc.client_context(), "claude-plugin/1.0.2")

    def test_codex_env_selects_codex_token(self) -> None:
        env = {"PLUGIN_ROOT": str(self.root), "CODEX_PLUGIN_ROOT": str(self.root)}
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(cc.client_context(), "codex-plugin/1.0.2")

    def test_codex_app_selects_codex_token(self) -> None:
        env = {"PLUGIN_ROOT": str(self.root), "CODEX_APP": "1"}
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(cc.client_context(), "codex-plugin/1.0.2")

    def test_missing_manifest_uses_fallback_version(self) -> None:
        empty = self.root / "empty"
        empty.mkdir()
        env = {"PLUGIN_ROOT": str(empty)}
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(cc.client_context(), "claude-plugin/0")


if __name__ == "__main__":
    unittest.main()
