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

    def test_parse_json_envelope(self) -> None:
        raw = json.dumps(
            {"ok": True, "command": "sumcli --version", "result": {"version": "0.1.3"}}
        )
        self.assertEqual(es.parse_installed_version(raw), "0.1.3")

    def test_parse_human_fallback(self) -> None:
        self.assertEqual(es.parse_installed_version("sumcli 0.1.3\n"), "0.1.3")
        self.assertIsNone(es.parse_installed_version(""))


class ContractTests(unittest.TestCase):
    def test_shipped_floor_is_013(self) -> None:
        spec = es.load_contract()
        self.assertEqual(spec["minVersion"], "0.1.3")
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


class EnsureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        os.environ["CLAUDE_PLUGIN_DATA"] = self.tmp.name
        os.environ.pop("SUMCLI_NO_AUTO_INSTALL", None)

    def test_silent_when_new_enough(self) -> None:
        with (
            patch.object(es, "which_sumcli", return_value="/bin/sumcli"),
            patch.object(es, "read_version", return_value="0.1.3"),
            patch.object(es, "run_bootstrap") as boot,
            patch.object(es, "run_update") as upd,
        ):
            self.assertIsNone(es.ensure())
            boot.assert_not_called()
            upd.assert_not_called()

    def test_opt_out_when_missing(self) -> None:
        os.environ["SUMCLI_NO_AUTO_INSTALL"] = "1"
        with patch.object(es, "which_sumcli", return_value=None), patch.object(es, "read_version", return_value=None):
            msg = es.ensure()
        self.assertIsNotNone(msg)
        assert msg is not None
        self.assertIn("not installed", msg)
        self.assertIn("SUMCLI_NO_AUTO_INSTALL", msg)

    def test_upgrade_when_too_old(self) -> None:
        with (
            patch.object(es, "which_sumcli", return_value="/bin/sumcli"),
            patch.object(es, "read_version", side_effect=["0.1.1", "0.1.3"]),
            patch.object(es, "run_update", return_value=(True, "")),
            patch.object(es, "run_bootstrap") as boot,
            patch.object(es, "prepend_tool_bins"),
        ):
            msg = es.ensure()
        boot.assert_not_called()
        self.assertIsNotNone(msg)
        assert msg is not None
        self.assertIn("0.1.1", msg)
        self.assertIn("0.1.3", msg)

    def test_install_when_missing(self) -> None:
        with (
            patch.object(es, "which_sumcli", side_effect=[None, "/bin/sumcli"]),
            patch.object(es, "read_version", return_value="0.1.3"),
            patch.object(es, "run_bootstrap", return_value=(True, "")),
            patch.object(es, "prepend_tool_bins"),
        ):
            msg = es.ensure()
        self.assertIsNotNone(msg)
        assert msg is not None
        self.assertIn("Installed", msg)
        self.assertIn("0.1.3", msg)


if __name__ == "__main__":
    unittest.main()
