"""Deterministic internal checks on format fixtures. Answer keys are frozen."""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "verify" / "scripts"
EXTRACT = SCRIPTS / "extract.py"
FIX = pathlib.Path("/Users/ericjaffe/Documents/GitHub/alg-deploy/fixtures-format")

sys.path.insert(0, str(SCRIPTS))
import internal  # noqa: E402
import inventory  # noqa: E402


def extract_inventory(report: pathlib.Path) -> dict:
    with tempfile.TemporaryDirectory() as raw:
        folder = pathlib.Path(raw)
        proc = subprocess.run(
            ["uv", "run", str(EXTRACT), "--report", str(report),
             "--visible", str(folder / "v.txt"), "--out", str(folder / "f.json")],
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            raise AssertionError(proc.stderr or proc.stdout)
        return json.loads((folder / "f.json").read_text())["inventory"]

P1 = "Ranked from highest to lowest revenue."
X1 = "Note: gross margin improved 3% week over week."
X1_CLEAN = "Note: gross margin improved 3 percentage points week over week."
T1 = "96%"


@unittest.skipUnless(FIX.is_dir(), "alg-deploy fixtures are not present")
class InternalCheckTests(unittest.TestCase):
    def test_pdf_clean_confirms_rank_and_inventories_source_line(self) -> None:
        path = FIX / "pdf-top5/clean/top-5-segments-clean.pdf"
        inv = extract_inventory(path)
        source = [
            item for item in inv["items"]
            if str(item.get("displayed") or "").lower().startswith("source snapshot")]
        self.assertTrue(source)
        self.assertTrue(all(item.get("importance") == "material" for item in source))
        outcomes = internal.check_inventory(inv)
        by_quote = {row["report_quote"]: row for row in outcomes}
        self.assertEqual(by_quote[P1]["verdict"], "confirmed")
        self.assertNotIn(
            "contradicted",
            {row["verdict"] for row in outcomes if row.get("importance") == "material"},
        )

    def test_pdf_twin_contradicts_declared_sort(self) -> None:
        path = FIX / "pdf-top5/twin/top-5-segments-twin.pdf"
        outcomes = internal.check_inventory(extract_inventory(path))
        hits = [
            row for row in outcomes
            if row.get("verdict") == "contradicted" and row.get("report_quote") == P1]
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["check_id"], "sel_declared_sort_violated")

    def test_xlsx_clean_confirms_note_and_margins(self) -> None:
        path = FIX / "xlsx-margin/clean/weekly-margin-summary-clean.xlsx"
        outcomes = internal.check_inventory(extract_inventory(path))
        notes = [row for row in outcomes if row.get("report_quote") == X1_CLEAN]
        self.assertTrue(notes)
        self.assertTrue(all(row["verdict"] == "confirmed" for row in notes))
        self.assertNotIn(X1, {row.get("report_quote") for row in outcomes})

    def test_xlsx_twin_contradicts_percent_labelled_point_move(self) -> None:
        path = FIX / "xlsx-margin/twin/weekly-margin-summary-twin.xlsx"
        outcomes = internal.check_inventory(extract_inventory(path))
        hits = [
            row for row in outcomes
            if row.get("verdict") == "contradicted" and row.get("report_quote") == X1]
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["check_id"], "uni_percent_vs_points")

    def test_pptx_clean_confirms_headline_ratio(self) -> None:
        path = FIX / "pptx-kpi/clean/operations-kpi-clean.pptx"
        outcomes = internal.check_inventory(extract_inventory(path))
        headlines = [
            row for row in outcomes if row.get("report_quote") == "94%"]
        self.assertTrue(headlines)
        self.assertTrue(all(row["verdict"] == "confirmed" for row in headlines))

    def test_pptx_twin_contradicts_headline(self) -> None:
        path = FIX / "pptx-kpi/twin/operations-kpi-twin.pptx"
        outcomes = internal.check_inventory(extract_inventory(path))
        hits = [
            row for row in outcomes
            if row.get("verdict") == "contradicted" and row.get("report_quote") == T1]
        self.assertEqual(len(hits), 1)


class SourceSnapshotInventoryTests(unittest.TestCase):
    LINES = (
        "Source snapshot: CRM revenue export, 2026-07-05",
        "Source snapshot: warehouse stale",
        "Source snapshot: dataset incomplete",
        "Source snapshot: export missing rows",
        "Source snapshot: active projects 12",
        "Source snapshot: corrupt CRM database",
        "Source snapshot: Funky warehouse",
        "Source snapshot: conversion lagged target",
    )

    def test_inventories_all_source_snapshot_lines_as_material(self) -> None:
        self.assertFalse(hasattr(inventory, "source_snapshot_importance"))
        with tempfile.TemporaryDirectory() as raw:
            path = pathlib.Path(raw) / "report.md"
            path.write_text("\n".join(self.LINES) + "\n")
            inv = inventory.inventory_for(path)
            by_shown = {item["displayed"]: item for item in inv["items"]}
            ids = []
            for line in self.LINES:
                self.assertIn(line, by_shown)
                item = by_shown[line]
                self.assertEqual(item["importance"], "material")
                self.assertTrue(item.get("id"))
                self.assertTrue(item.get("location"))
                ids.append(item["id"])
            self.assertEqual(len(ids), len(set(ids)))


class GitEvidenceTests(unittest.TestCase):
    def _load(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "verify_git_evidence", SCRIPTS / "git_evidence.py")
        mod = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(mod)
        return mod

    def _git(self, repo: pathlib.Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        env = os.environ.copy()
        env.update({
            "GIT_AUTHOR_NAME": "Verify Test",
            "GIT_AUTHOR_EMAIL": "verify-test@example.com",
            "GIT_COMMITTER_NAME": "Verify Test",
            "GIT_COMMITTER_EMAIL": "verify-test@example.com",
            "GIT_TERMINAL_PROMPT": "0",
        })
        return subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True, text=True, env=env, check=check)

    def _init_repo(self, path: pathlib.Path) -> None:
        subprocess.run(
            ["git", "init", "-b", "main", str(path)],
            capture_output=True, text=True, check=True)
        self._git(path, "config", "user.email", "verify-test@example.com")
        self._git(path, "config", "user.name", "Verify Test")
        self._git(path, "config", "commit.gpgsign", "false")
        (path / "file.txt").write_text("one\n")
        self._git(path, "add", "file.txt")
        self._git(path, "commit", "-m", "one")

    def test_writes_head_branch_and_porcelain(self) -> None:
        mod = self._load()
        with tempfile.TemporaryDirectory() as raw:
            out = pathlib.Path(raw) / "git-evidence.json"
            code = None
            argv = sys.argv
            sys.argv = ["git_evidence.py", "--repo", str(ROOT), "--out", str(out)]
            try:
                code = mod.main()
            finally:
                sys.argv = argv
            self.assertEqual(code, 0)
            payload = json.loads(out.read_text())
            self.assertTrue(payload.get("head"))
            self.assertEqual(payload.get("branch"), "verify-skill")
            self.assertIn("status_porcelain", payload)
            self.assertIn("local_only", payload)
            self.assertIsNone(payload.get("local_only"))
            self.assertFalse(payload.get("live_remote_query"))

    def test_no_upstream_leaves_push_state_unknown(self) -> None:
        mod = self._load()
        with tempfile.TemporaryDirectory() as raw:
            repo = pathlib.Path(raw) / "repo"
            repo.mkdir()
            self._init_repo(repo)
            payload = mod.collect(repo)
            self.assertIsNone(payload["upstream"])
            self.assertIsNone(payload["local_only"])
            self.assertIsNone(payload["contained_in_upstream"])
            self.assertIsNone(payload["unpushed_commit_count"])
            self.assertEqual(payload["remote_query"], "none")
            self.assertFalse(payload["live_remote_query"])
            self.assertEqual(payload["remote_refs_containing_head"], [])

    def test_contained_remote_ref_from_local_tracking(self) -> None:
        mod = self._load()
        with tempfile.TemporaryDirectory() as raw:
            root = pathlib.Path(raw)
            repo = root / "repo"
            bare = root / "remote.git"
            repo.mkdir()
            self._init_repo(repo)
            subprocess.run(
                ["git", "init", "--bare", str(bare)],
                capture_output=True, text=True, check=True)
            self._git(repo, "remote", "add", "origin", str(bare))
            self._git(repo, "push", "-u", "origin", "main")
            payload = mod.collect(repo)
            self.assertFalse(payload["live_remote_query"])
            self.assertEqual(payload["remote_query"], "local_refs")
            self.assertTrue(
                any(name.endswith("/main") for name in payload["remote_refs_containing_head"]))
            self.assertEqual(payload.get("contained_in_upstream"), True)
            self.assertEqual(payload.get("unpushed_commit_count"), 0)

    def test_ahead_local_branch_does_not_claim_live_remote(self) -> None:
        mod = self._load()
        with tempfile.TemporaryDirectory() as raw:
            root = pathlib.Path(raw)
            repo = root / "repo"
            bare = root / "remote.git"
            repo.mkdir()
            self._init_repo(repo)
            subprocess.run(
                ["git", "init", "--bare", str(bare)],
                capture_output=True, text=True, check=True)
            self._git(repo, "remote", "add", "origin", str(bare))
            self._git(repo, "push", "-u", "origin", "main")
            (repo / "file.txt").write_text("two\n")
            self._git(repo, "add", "file.txt")
            self._git(repo, "commit", "-m", "two")
            payload = mod.collect(repo)
            self.assertFalse(payload["live_remote_query"])
            self.assertIsNone(payload["local_only"])
            self.assertGreaterEqual(
                max(payload["ahead_of_remote_refs"].values() or [0]), 1)
            self.assertFalse(
                any(name.endswith("/main") for name in payload["remote_refs_containing_head"]))
            self.assertEqual(payload.get("unpushed_commit_count"), 1)


if __name__ == "__main__":
    unittest.main()
