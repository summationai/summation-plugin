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
SUM_API = ROOT / "skills" / "api" / "scripts" / "sum_api.py"


def _load(path: pathlib.Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


cc = _load(SCRIPT, "client_context")
api = _load(SUM_API, "sum_api")


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


class TokenParityTests(unittest.TestCase):
    """client_context() and client_user_agent() must emit the same token."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        (self.root / "plugin.json").write_text(
            json.dumps({"version": "1.0.2"}), encoding="utf-8"
        )

    def _assert_same(self, env: dict[str, str]) -> None:
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(cc.client_context(), api.client_user_agent())

    def test_claude_plugin_root(self) -> None:
        self._assert_same({"PLUGIN_ROOT": str(self.root)})

    def test_claude_plugin_root_alias(self) -> None:
        self._assert_same({"CLAUDE_PLUGIN_ROOT": str(self.root)})

    def test_codex_app(self) -> None:
        self._assert_same({"PLUGIN_ROOT": str(self.root), "CODEX_APP": "1"})

    def test_codex_plugin_root(self) -> None:
        self._assert_same(
            {"PLUGIN_ROOT": str(self.root), "CODEX_PLUGIN_ROOT": str(self.root)}
        )

    def test_codex_plugin_root_only(self) -> None:
        self._assert_same({"CODEX_PLUGIN_ROOT": str(self.root)})


if __name__ == "__main__":
    unittest.main()
