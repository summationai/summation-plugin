"""Trust corrections: inventory coverage, ungraded refuse, private receipts."""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "verify" / "scripts"
CLEAN = ROOT / "tests" / "fixtures" / "verify" / "weekly-sales-snapshot-clean.html"
SENTINEL = "SECRET_EVIDENCE_TOKEN_9f3a"

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(SCRIPTS))
from test_verify_render import run_mod, accept, render, html_arith  # noqa: E402
import inventory  # noqa: E402

PROMISE_WORDS = (
    "on a schedule", "workflow", "live-query", "live source query",
    "upload this", "put this on a schedule",
)


def _cover_clean(folder: pathlib.Path, *, omit: str | None = None) -> None:
    report = folder / "report.html"
    report.write_text(CLEAN.read_text())
    self_inv = inventory.inventory_for(report)
    claims = []
    checks = []
    evidence = {}
    for index, item in enumerate(self_inv["items"], start=1):
        shown = item["displayed"]
        if omit and shown == omit:
            continue
        cid = f"L{index}"
        claims.append({
            "id": cid,
            "quote": shown,
            "importance": "material",
        })
        key = f"v{index}"
        evidence[key] = shown
        checks.append({
            "id": f"C{index}",
            "claim_id": cid,
            "type": "semantic",
            "basis": "evidence",
            "verdict": "confirmed",
            "importance": "material",
            "report_quote": shown,
            "evidence_file": "ev.json",
            "evidence_json": [{"pointer": f"/{key}", "value": shown}],
            "explanation": f"The evidence matches {shown}.",
        })
    (folder / "ev.json").write_text(json.dumps(evidence) + "\n")
    (folder / "claims.json").write_text(json.dumps({
        "claims": claims,
        "report_period": "week ending April 4, 2026",
        "report_date": "2026-04-04",
    }))
    (folder / "checks.json").write_text(json.dumps({"checks": checks}))


class TrustCorrectionTests(unittest.TestCase):
    def test_complete_clean_html_is_safe_to_share(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            _cover_clean(folder)
            self.assertEqual(run_mod(html_arith, "html_arith.py", [
                "--report", str(folder / "report.html"),
                "--out", str(folder / "findings.json"),
            ]), 0)
            self.assertEqual(run_mod(accept, "accept.py", [
                "--report", str(folder / "report.html"),
                "--claims", str(folder / "claims.json"),
                "--checks", str(folder / "checks.json"),
                "--findings", str(folder / "findings.json"),
                "--evidence-dir", str(folder),
                "--out", str(folder / "receipts.json"),
            ]), 0)
            receipts = json.loads((folder / "receipts.json").read_text())
            self.assertEqual(receipts["inventory_missing"], [])
            self.assertEqual(receipts["extractor_checkable_fraction"], 1.0)
            self.assertEqual(receipts["engine_checkable_fraction"], 1.0)
            out = folder / "artifact"
            self.assertEqual(run_mod(render, "render.py", [
                "--findings", str(folder / "findings.json"),
                "--layer2", str(folder / "receipts.json"),
                "--out-dir", str(out),
                "--run-id", "clean-inv",
            ]), 0)
            art = json.loads((out / "grade-artifact.json").read_text())
            self.assertEqual(art["verdict"], "safe_to_share")
            page = (out / "grade-artifact.html").read_text()
            self.assertIn("SAFE TO SHARE", page)
            (folder / "generated-clean.json").write_text(json.dumps({
                "html": str(out / "grade-artifact.html"),
                "json": str(out / "grade-artifact.json"),
            }))

    def test_omitted_material_item_refuses_shareable_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            _cover_clean(folder, omit="4.6%")
            self.assertEqual(run_mod(html_arith, "html_arith.py", [
                "--report", str(folder / "report.html"),
                "--out", str(folder / "findings.json"),
            ]), 0)
            self.assertEqual(run_mod(accept, "accept.py", [
                "--report", str(folder / "report.html"),
                "--claims", str(folder / "claims.json"),
                "--checks", str(folder / "checks.json"),
                "--findings", str(folder / "findings.json"),
                "--evidence-dir", str(folder),
                "--out", str(folder / "receipts.json"),
            ]), 0)
            receipts = json.loads((folder / "receipts.json").read_text())
            self.assertTrue(receipts["inventory_missing"])
            out = folder / "artifact"
            code = run_mod(render, "render.py", [
                "--findings", str(folder / "findings.json"),
                "--layer2", str(folder / "receipts.json"),
                "--out-dir", str(out),
            ])
            self.assertEqual(code, 2)
            self.assertFalse((out / "grade-artifact.html").is_file())
            self.assertFalse((out / "grade-artifact.json").is_file())

    def test_unable_to_grade_writes_no_shareable_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            (folder / "findings.json").write_text(json.dumps({
                "findings": "not-a-list",
                "coverage": {},
                "source": {"path": "report.md", "format": "md"},
            }))
            out = folder / "artifact"
            code = run_mod(render, "render.py", [
                "--findings", str(folder / "findings.json"),
                "--out-dir", str(out),
            ])
            self.assertEqual(code, 2)
            self.assertFalse((out / "grade-artifact.html").is_file())
            self.assertFalse((out / "grade-artifact.json").is_file())
            self.assertNotEqual(
                render.customer_verdict("unable_to_grade"), "share_with_caveats")

    def test_confidential_sentinel_stays_private(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            _cover_clean(folder)
            ev = json.loads((folder / "ev.json").read_text())
            ev["secret"] = SENTINEL
            (folder / "ev.json").write_text(json.dumps(ev) + "\n")
            checks = json.loads((folder / "checks.json").read_text())
            checks["checks"][0]["evidence_quote"] = SENTINEL
            checks["checks"][0]["evidence_file"] = "ev.json"
            checks["checks"][0]["evidence_json"].append(
                {"pointer": "/secret", "value": SENTINEL})
            (folder / "checks.json").write_text(json.dumps(checks))
            self.assertEqual(run_mod(html_arith, "html_arith.py", [
                "--report", str(folder / "report.html"),
                "--out", str(folder / "findings.json"),
            ]), 0)
            self.assertEqual(run_mod(accept, "accept.py", [
                "--report", str(folder / "report.html"),
                "--claims", str(folder / "claims.json"),
                "--checks", str(folder / "checks.json"),
                "--findings", str(folder / "findings.json"),
                "--evidence-dir", str(folder),
                "--out", str(folder / "receipts.json"),
            ]), 0)
            receipts_text = (folder / "receipts.json").read_text()
            self.assertIn(SENTINEL, receipts_text)
            out = folder / "artifact"
            self.assertEqual(run_mod(render, "render.py", [
                "--findings", str(folder / "findings.json"),
                "--layer2", str(folder / "receipts.json"),
                "--out-dir", str(out),
            ]), 0)
            self.assertNotIn(SENTINEL, (out / "grade-artifact.json").read_text())
            self.assertNotIn(SENTINEL, (out / "grade-artifact.html").read_text())

    def test_shareable_artifact_has_no_schedule_promise(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            _cover_clean(folder)
            self.assertEqual(run_mod(html_arith, "html_arith.py", [
                "--report", str(folder / "report.html"),
                "--out", str(folder / "findings.json"),
            ]), 0)
            self.assertEqual(run_mod(accept, "accept.py", [
                "--report", str(folder / "report.html"),
                "--claims", str(folder / "claims.json"),
                "--checks", str(folder / "checks.json"),
                "--findings", str(folder / "findings.json"),
                "--evidence-dir", str(folder),
                "--out", str(folder / "receipts.json"),
            ]), 0)
            out = folder / "artifact"
            self.assertEqual(run_mod(render, "render.py", [
                "--findings", str(folder / "findings.json"),
                "--layer2", str(folder / "receipts.json"),
                "--out-dir", str(out),
            ]), 0)
            blob = (
                (out / "grade-artifact.json").read_text()
                + (out / "grade-artifact.html").read_text()
            ).lower()
            for word in PROMISE_WORDS:
                self.assertNotIn(word, blob, word)


if __name__ == "__main__":
    unittest.main()
