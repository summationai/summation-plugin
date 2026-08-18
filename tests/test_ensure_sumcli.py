"""Unit tests for the SessionStart sumcli ensure hook (stdlib only)."""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
HOOK = ROOT / "packaging" / "com.anthropic.claude" / "hooks" / "ensure_sumcli.py"


def _load():
    spec = importlib.util.spec_from_file_location("ensure_sumcli", HOOK)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


es = _load()


class VersionTests(unittest.TestCase):
    def test_meets_min(self) -> None:
        self.assertTrue(es.meets_min("0.1.3", "0.1.3"))
        self.assertTrue(es.meets_min("0.1.4", "0.1.3"))
        self.assertTrue(es.meets_min("0.2.0", "0.1.3"))
        self.assertFalse(es.meets_min("0.1.2", "0.1.3"))
        self.assertFalse(es.meets_min("0.1.10", "0.2.0"))
        self.assertFalse(es.meets_min("0.1.3rc1", "0.1.3"))
        self.assertIsNone(es.version_tuple("0.1.3rc1"))

    def test_parse_json_envelope(self) -> None:
        raw = json.dumps(
            {"ok": True, "command": "sumcli --version", "result": {"version": "0.1.3"}}
        )
        self.assertEqual(es.parse_installed_version(raw), "0.1.3")

    def test_parse_human_fallback(self) -> None:
        self.assertEqual(es.parse_installed_version("sumcli 0.1.3\n"), "0.1.3")
        self.assertIsNone(es.parse_installed_version(""))


class ContractTests(unittest.TestCase):
    def test_shipped_floor_is_014(self) -> None:
        spec = es.load_contract()
        self.assertEqual(spec["minVersion"], "0.1.4")
        self.assertEqual(spec["upgradePolicy"], "latest-is-compatible")
        self.assertIn("curl", spec["bootstrap"]["posix"])
        self.assertIn("sumcli.ps1", spec["bootstrap"]["powershell"])
        self.assertIn("powershell", spec["bootstrap"]["cmd"])


class ShellTests(unittest.TestCase):
    def test_posix_from_shell(self) -> None:
        env = {"SHELL": "/bin/zsh"}
        with patch.object(es, "is_windows", return_value=False), patch.dict(os.environ, env, clear=True):
            self.assertEqual(es.detect_shell(), "posix")

    def test_git_bash_msystem(self) -> None:
        env = {"MSYSTEM": "MINGW64", "SHELL": "/usr/bin/bash"}
        with patch.object(es, "is_windows", return_value=True), patch.dict(os.environ, env, clear=True):
            self.assertEqual(es.detect_shell(), "posix")

    def test_powershell(self) -> None:
        env = {"PSModulePath": r"C:\Program Files\PowerShell\Modules"}
        with patch.object(es, "is_windows", return_value=True), patch.dict(os.environ, env, clear=True):
            self.assertEqual(es.detect_shell(), "powershell")

    def test_cmd(self) -> None:
        env = {"ComSpec": r"C:\Windows\system32\cmd.exe"}
        with patch.object(es, "is_windows", return_value=True), patch.dict(os.environ, env, clear=True):
            self.assertEqual(es.detect_shell(), "cmd")

    def test_user_commands(self) -> None:
        spec = es.load_contract()
        self.assertTrue(es.install_command_for_user(spec, "posix").startswith("curl"))
        self.assertTrue(es.install_command_for_user(spec, "powershell").startswith("irm"))
        self.assertTrue(es.install_command_for_user(spec, "cmd").startswith("powershell"))


class DataDirTests(unittest.TestCase):
    def test_prefers_plugin_data(self) -> None:
        env = {"PLUGIN_DATA": "/tmp/plugin-data", "CLAUDE_PLUGIN_DATA": "/tmp/claude-data"}
        with patch.dict(os.environ, env, clear=False):
            self.assertEqual(es._data_dir(), pathlib.Path("/tmp/plugin-data"))

    def test_falls_back_to_claude_then_plugin_subdir(self) -> None:
        env = {"CLAUDE_PLUGIN_DATA": "/tmp/claude-data"}
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(es._data_dir(), pathlib.Path("/tmp/claude-data"))
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(es._data_dir(), pathlib.Path.home() / ".summation" / "plugin")


class EnsureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        os.environ["PLUGIN_DATA"] = self.tmp.name
        os.environ["CLAUDE_PLUGIN_DATA"] = self.tmp.name
        os.environ.pop("SUMCLI_AUTO_INSTALL", None)
        os.environ.pop("SUMCLI_NO_AUTO_INSTALL", None)

    def test_silent_when_new_enough(self) -> None:
        with (
            patch.object(es, "which_sumcli", return_value="/bin/sumcli"),
            patch.object(es, "read_version", return_value="0.1.4"),
            patch.object(es, "run_bootstrap") as boot,
            patch.object(es, "run_update") as upd,
        ):
            self.assertIsNone(es.ensure())
            boot.assert_not_called()
            upd.assert_not_called()

    def test_default_nudges_when_missing_and_does_not_install(self) -> None:
        with (
            patch.object(es, "which_sumcli", return_value=None),
            patch.object(es, "read_version", return_value=None),
            patch.object(es, "run_bootstrap") as boot,
            patch.object(es, "run_update") as upd,
        ):
            msg = es.ensure()
        boot.assert_not_called()
        upd.assert_not_called()
        self.assertIsNotNone(msg)
        assert msg is not None
        self.assertIn("not installed", msg)
        self.assertIn("MCP", msg)
        self.assertNotIn("SUMCLI_AUTO_INSTALL", msg)

    def test_default_nudge_is_once_per_day(self) -> None:
        with (
            patch.object(es, "which_sumcli", return_value=None),
            patch.object(es, "read_version", return_value=None),
        ):
            first = es.ensure()
            second = es.ensure()
        self.assertIsNotNone(first)
        self.assertIsNone(second)

    def test_upgrade_when_too_old_requires_opt_in(self) -> None:
        with (
            patch.object(es, "which_sumcli", return_value="/bin/sumcli"),
            patch.object(es, "read_version", return_value="0.1.1"),
            patch.object(es, "run_update") as upd,
            patch.object(es, "run_bootstrap") as boot,
        ):
            msg = es.ensure()
        boot.assert_not_called()
        upd.assert_not_called()
        self.assertIsNotNone(msg)
        assert msg is not None
        self.assertIn("0.1.1", msg)
        self.assertIn("sumcli update", msg)

    def test_opt_in_upgrade_when_too_old(self) -> None:
        os.environ["SUMCLI_AUTO_INSTALL"] = "1"
        with (
            patch.object(es, "which_sumcli", return_value="/bin/sumcli"),
            patch.object(es, "read_version", side_effect=["0.1.1", "0.1.4"]),
            patch.object(es, "run_update", return_value=(True, "")),
            patch.object(es, "run_bootstrap") as boot,
            patch.object(es, "prepend_tool_bins"),
            patch.object(es, "_on_login_path", return_value=True),
        ):
            msg = es.ensure()
        boot.assert_not_called()
        self.assertIsNotNone(msg)
        assert msg is not None
        self.assertIn("0.1.1", msg)
        self.assertIn("0.1.4", msg)

    def test_opt_in_install_when_missing(self) -> None:
        os.environ["SUMCLI_AUTO_INSTALL"] = "1"
        with (
            patch.object(es, "which_sumcli", side_effect=[None, "/bin/sumcli"]),
            patch.object(es, "read_version", return_value="0.1.4"),
            patch.object(es, "run_bootstrap", return_value=(True, "")),
            patch.object(es, "prepend_tool_bins"),
            patch.object(es, "_on_login_path", return_value=True),
        ):
            msg = es.ensure()
        self.assertIsNotNone(msg)
        assert msg is not None
        self.assertIn("Installed", msg)
        self.assertIn("0.1.4", msg)

    def test_not_uv_managed_does_not_bootstrap(self) -> None:
        os.environ["SUMCLI_AUTO_INSTALL"] = "1"
        detail = json.dumps({"error": {"code": "NOT_UV_MANAGED"}})
        with (
            patch.object(es, "which_sumcli", return_value="/opt/homebrew/bin/sumcli"),
            patch.object(es, "read_version", return_value="0.1.1"),
            patch.object(es, "run_update", return_value=(False, detail)),
            patch.object(es, "run_bootstrap") as boot,
        ):
            msg = es.ensure()
        boot.assert_not_called()
        self.assertIsNotNone(msg)
        assert msg is not None
        self.assertIn("not installed with uv", msg)
        self.assertIn("brew", msg)

    def test_install_mentions_path_when_not_on_login_path(self) -> None:
        os.environ["SUMCLI_AUTO_INSTALL"] = "1"
        with (
            patch.object(es, "which_sumcli", side_effect=[None, "/tmp/uv/sumcli"]),
            patch.object(es, "read_version", return_value="0.1.4"),
            patch.object(es, "run_bootstrap", return_value=(True, "")),
            patch.object(es, "prepend_tool_bins"),
            patch.object(es, "_on_login_path", return_value=False),
        ):
            msg = es.ensure()
        self.assertIsNotNone(msg)
        assert msg is not None
        self.assertIn("Installed", msg)
        self.assertIn("PATH", msg)

    def test_upgrade_passes_remaining_budget(self) -> None:
        os.environ["SUMCLI_AUTO_INSTALL"] = "1"
        with (
            patch.object(es, "which_sumcli", return_value="/bin/sumcli"),
            patch.object(es, "read_version", side_effect=["0.1.1", "0.1.4"]),
            patch.object(es, "run_update", return_value=(True, "")) as upd,
            patch.object(es, "run_bootstrap") as boot,
            patch.object(es, "prepend_tool_bins"),
            patch.object(es, "_on_login_path", return_value=True),
        ):
            es.ensure()
        boot.assert_not_called()
        self.assertIn("timeout", upd.call_args.kwargs)
        self.assertGreater(upd.call_args.kwargs["timeout"], 0)


if __name__ == "__main__":
    unittest.main()
