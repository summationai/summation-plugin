"""Deterministic internal checks on format fixtures. Answer keys are frozen."""
from __future__ import annotations

import json
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
    def test_pdf_clean_confirms_rank_and_marks_source_supporting(self) -> None:
        path = FIX / "pdf-top5/clean/top-5-segments-clean.pdf"
        inv = extract_inventory(path)
        source = [
            item for item in inv["items"]
            if str(item.get("displayed") or "").lower().startswith("source snapshot")]
        self.assertTrue(source)
        self.assertTrue(all(item.get("importance") == "supporting" for item in source))
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


class GitEvidenceTests(unittest.TestCase):
    def test_writes_head_branch_and_porcelain(self) -> None:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "verify_git_evidence", SCRIPTS / "git_evidence.py")
        mod = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(mod)
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
            payload = __import__("json").loads(out.read_text())
            self.assertTrue(payload.get("head"))
            self.assertEqual(payload.get("branch"), "verify-skill")
            self.assertIn("status_porcelain", payload)
            self.assertIn("local_only", payload)


if __name__ == "__main__":
    unittest.main()
