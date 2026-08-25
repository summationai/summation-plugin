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
SENTINEL = "SECRET_EVIDENCE_TOKEN"

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(SCRIPTS))
from test_verify_render import PLANTED, run_mod, accept, render, html_arith  # noqa: E402
import inventory  # noqa: E402

PROMISE_WORDS = (
    "on a schedule", "workflow", "live-query", "live source query",
    "upload this", "put this on a schedule",
)
BARE_HTML = """<!doctype html>
<html><body>
<p>Revenue is $100.</p>
<p>On hand: 42 units.</p>
</body></html>
"""
DUP_HTML = """<!doctype html>
<html><body>
<table>
<tr><th>Name</th><th>Value</th></tr>
<tr><td>Alpha</td><td>1,000</td></tr>
<tr><td>Beta</td><td>1,000</td></tr>
<tr><td>Total</td><td>2,000</td></tr>
</table>
</body></html>
"""
MALICIOUS_SUMMARY = (
    "Summation can put this on a schedule and run a live-query workflow. "
    "Connect and upload this."
)
MALICIOUS_ACTION = (
    "Put this on a schedule. Start a workflow. Run a live-query. Upload this."
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
            "inventory_ids": [item["id"]],
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

    def test_bare_number_and_unit_word_are_inventoried(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            report = folder / "report.html"
            report.write_text(BARE_HTML)
            items = inventory.inventory_for(report)["items"]
            shown = {item["displayed"] for item in items}
            self.assertIn("$100", shown)
            self.assertIn("42 units", shown)
            self.assertGreaterEqual(len(shown), 2)
            ids = {item["displayed"]: item["id"] for item in items}
            self.assertNotEqual(ids["$100"], ids["42 units"])

    def test_omit_revenue_or_units_writes_no_artifact(self) -> None:
        for omit in ("$100", "42 units"):
            with self.subTest(omit=omit), tempfile.TemporaryDirectory() as raw:
                folder = pathlib.Path(raw)
                report = folder / "report.html"
                report.write_text(BARE_HTML)
                keep = "42 units" if omit == "$100" else "$100"
                keep_id = "INV2" if keep == "42 units" else "INV1"
                (folder / "ev.json").write_text(json.dumps({"v": keep}))
                (folder / "claims.json").write_text(json.dumps({
                    "claims": [{
                        "id": "L1",
                        "quote": keep,
                        "importance": "material",
                        "inventory_ids": [keep_id],
                    }],
                }))
                (folder / "checks.json").write_text(json.dumps({"checks": [{
                    "id": "C1",
                    "claim_id": "L1",
                    "type": "semantic",
                    "basis": "evidence",
                    "verdict": "confirmed",
                    "importance": "material",
                    "report_quote": keep,
                    "evidence_file": "ev.json",
                    "evidence_json": [{"pointer": "/v", "value": keep}],
                    "explanation": f"The evidence matches {keep}.",
                }]}))
                self.assertEqual(run_mod(html_arith, "html_arith.py", [
                    "--report", str(report),
                    "--out", str(folder / "findings.json"),
                ]), 0)
                findings = json.loads((folder / "findings.json").read_text())
                shown = {
                    item["displayed"]
                    for item in findings["inventory"]["items"]
                }
                self.assertIn("$100", shown)
                self.assertIn("42 units", shown)
                self.assertEqual(run_mod(accept, "accept.py", [
                    "--report", str(report),
                    "--claims", str(folder / "claims.json"),
                    "--checks", str(folder / "checks.json"),
                    "--findings", str(folder / "findings.json"),
                    "--evidence-dir", str(folder),
                    "--out", str(folder / "receipts.json"),
                ]), 0)
                receipts = json.loads((folder / "receipts.json").read_text())
                missing_shown = {
                    row.get("displayed") for row in receipts["inventory_missing"]
                }
                self.assertIn(omit, missing_shown)
                out = folder / "artifact"
                code = run_mod(render, "render.py", [
                    "--findings", str(folder / "findings.json"),
                    "--layer2", str(folder / "receipts.json"),
                    "--out-dir", str(out),
                ])
                self.assertEqual(code, 2)
                self.assertFalse((out / "grade-artifact.html").is_file())
                self.assertFalse((out / "grade-artifact.json").is_file())

    def test_duplicate_thousand_one_claim_leaves_named_id_missing(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            report = folder / "report.html"
            report.write_text(DUP_HTML)
            (folder / "ev.json").write_text(json.dumps({
                "thousand": "1,000", "total": "2,000",
            }))
            (folder / "claims.json").write_text(json.dumps({
                "claims": [
                    {
                        "id": "L1",
                        "quote": "1,000",
                        "importance": "material",
                        "inventory_ids": ["INV1"],
                    },
                    {
                        "id": "L2",
                        "quote": "2,000",
                        "importance": "material",
                        "inventory_ids": ["INV3"],
                    },
                ],
            }))
            (folder / "checks.json").write_text(json.dumps({"checks": [
                {
                    "id": "C1",
                    "claim_id": "L1",
                    "type": "semantic",
                    "basis": "evidence",
                    "verdict": "confirmed",
                    "importance": "material",
                    "report_quote": "1,000",
                    "evidence_file": "ev.json",
                    "evidence_json": [{"pointer": "/thousand", "value": "1,000"}],
                    "explanation": "Alpha matches.",
                },
                {
                    "id": "C2",
                    "claim_id": "L2",
                    "type": "semantic",
                    "basis": "evidence",
                    "verdict": "confirmed",
                    "importance": "material",
                    "report_quote": "2,000",
                    "evidence_file": "ev.json",
                    "evidence_json": [{"pointer": "/total", "value": "2,000"}],
                    "explanation": "Total matches.",
                },
            ]}))
            self.assertEqual(run_mod(html_arith, "html_arith.py", [
                "--report", str(report),
                "--out", str(folder / "findings.json"),
            ]), 0)
            items = json.loads(
                (folder / "findings.json").read_text())["inventory"]["items"]
            by_loc = {item["location"]: item for item in items}
            self.assertIn("table1/Alpha/Value", by_loc)
            self.assertIn("table1/Beta/Value", by_loc)
            self.assertIn("table1/Total/Value", by_loc)
            self.assertEqual(by_loc["table1/Alpha/Value"]["displayed"], "1,000")
            self.assertEqual(by_loc["table1/Beta/Value"]["displayed"], "1,000")
            self.assertEqual(run_mod(accept, "accept.py", [
                "--report", str(report),
                "--claims", str(folder / "claims.json"),
                "--checks", str(folder / "checks.json"),
                "--findings", str(folder / "findings.json"),
                "--evidence-dir", str(folder),
                "--out", str(folder / "receipts.json"),
            ]), 0)
            receipts = json.loads((folder / "receipts.json").read_text())
            missing_ids = {row.get("id") for row in receipts["inventory_missing"]}
            self.assertIn(by_loc["table1/Beta/Value"]["id"], missing_ids)
            out = folder / "artifact"
            code = run_mod(render, "render.py", [
                "--findings", str(folder / "findings.json"),
                "--layer2", str(folder / "receipts.json"),
                "--out-dir", str(out),
            ])
            self.assertEqual(code, 2)
            self.assertFalse((out / "grade-artifact.html").is_file())
            self.assertFalse((out / "grade-artifact.json").is_file())

    def test_unreadable_pdf_without_receipts_writes_no_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            report = folder / "board.pdf"
            report.write_bytes(b"%PDF-fake")
            self.assertEqual(run_mod(html_arith, "html_arith.py", [
                "--report", str(report),
                "--out", str(folder / "findings.json"),
            ]), 0)
            findings = json.loads((folder / "findings.json").read_text())
            self.assertTrue(findings["agentic_only"])
            self.assertFalse(findings["agentic_scan_completed"])
            out = folder / "artifact"
            code = run_mod(render, "render.py", [
                "--findings", str(folder / "findings.json"),
                "--out-dir", str(out),
            ])
            self.assertEqual(code, 2)
            self.assertFalse((out / "grade-artifact.html").is_file())
            self.assertFalse((out / "grade-artifact.json").is_file())
            code = run_mod(render, "render.py", [
                "--findings", str(folder / "findings.json"),
                "--layer2", str(folder / "receipts.json"),
                "--out-dir", str(out),
            ])
            self.assertEqual(code, 2)
            self.assertFalse((out / "grade-artifact.html").is_file())
            self.assertFalse((out / "grade-artifact.json").is_file())

    def test_confidential_sentinel_stays_private(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            report = folder / "report.html"
            report.write_text(BARE_HTML)
            ev_name = f"{SENTINEL}.json"
            (folder / ev_name).write_text(json.dumps({
                SENTINEL: SENTINEL,
                "revenue": "$100",
                "units": "42 units",
            }) + "\n")
            (folder / "claims.json").write_text(json.dumps({
                "claims": [
                    {
                        "id": "L1",
                        "quote": "$100",
                        "importance": "material",
                        "inventory_ids": ["INV1"],
                    },
                    {
                        "id": "L2",
                        "quote": "42 units",
                        "importance": "material",
                        "inventory_ids": ["INV2"],
                    },
                ],
            }))
            (folder / "checks.json").write_text(json.dumps({"checks": [
                {
                    "id": "C1",
                    "claim_id": "L1",
                    "type": "semantic",
                    "basis": "evidence",
                    "verdict": "confirmed",
                    "importance": "material",
                    "report_quote": "$100",
                    "evidence_file": ev_name,
                    "evidence_quote": SENTINEL,
                    "evidence_json": [
                        {"pointer": "/revenue", "value": "$100"},
                        {"pointer": f"/{SENTINEL}", "value": SENTINEL},
                    ],
                    "explanation": "Revenue matches.",
                    "reconstruction_attempt": SENTINEL,
                },
                {
                    "id": "C2",
                    "claim_id": "L2",
                    "type": "semantic",
                    "basis": "evidence",
                    "verdict": "confirmed",
                    "importance": "material",
                    "report_quote": "42 units",
                    "evidence_file": ev_name,
                    "evidence_quote": SENTINEL,
                    "evidence_json": [{"pointer": "/units", "value": "42 units"}],
                    "explanation": "Units match.",
                },
            ]}))
            self.assertEqual(run_mod(html_arith, "html_arith.py", [
                "--report", str(report),
                "--out", str(folder / "findings.json"),
            ]), 0)
            findings = json.loads((folder / "findings.json").read_text())
            findings["source"]["path"] = f"/secret/{SENTINEL}/report.html"
            (folder / "findings.json").write_text(json.dumps(findings))
            self.assertEqual(run_mod(accept, "accept.py", [
                "--report", str(report),
                "--claims", str(folder / "claims.json"),
                "--checks", str(folder / "checks.json"),
                "--findings", str(folder / "findings.json"),
                "--evidence-dir", str(folder),
                "--out", str(folder / "receipts.json"),
            ]), 0)
            receipts_text = (folder / "receipts.json").read_text()
            self.assertIn(SENTINEL, receipts_text)
            source_doc = {
                "status": "complete",
                "error": None,
                "provider": "sum-api",
                "profile": SENTINEL,
                "source_identity": {"name": SENTINEL},
                "suggested_source": SENTINEL,
                "generated_at": "2026-08-24T00:00:00Z",
                "tables": [SENTINEL],
                "confirmed": 1,
                "contradicted": 0,
                "not_run": 0,
                "checks": [{"id": "SRC1", "verdict": "confirmed",
                            "secret": SENTINEL}],
            }
            (folder / "source.json").write_text(json.dumps(source_doc))
            out = folder / "artifact"
            self.assertEqual(run_mod(render, "render.py", [
                "--findings", str(folder / "findings.json"),
                "--layer2", str(folder / "receipts.json"),
                "--source", str(folder / "source.json"),
                "--out-dir", str(out),
            ]), 0)
            public = (
                (out / "grade-artifact.json").read_text()
                + (out / "grade-artifact.html").read_text()
            )
            self.assertNotIn(SENTINEL, public)
            art = json.loads((out / "grade-artifact.json").read_text())
            self.assertIsNone(art.get("source_result"))
            self.assertNotIn("presentation", art)
            for row in art.get("evidence_checks") or []:
                self.assertNotIn("evidence_json", row)
                self.assertNotIn("reconstruction_attempt", row)
                quote = str(row.get("evidence_quote") or "")
                self.assertNotIn(SENTINEL, quote)
                self.assertNotIn("/", quote)
                if row.get("evidence_file"):
                    self.assertNotIn(SENTINEL, str(row["evidence_file"]))

    def test_malicious_presentation_absent_from_safe_and_caveated(self) -> None:
        cases = (
            ("safe", "confirmed", "safe_to_share"),
            ("caveats", "not_checkable", "share_with_caveats"),
        )
        for label, units_verdict, expected in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as raw:
                folder = pathlib.Path(raw)
                report = folder / "report.html"
                report.write_text(BARE_HTML)
                (folder / "ev.json").write_text(json.dumps({
                    "revenue": "$100", "units": "42 units",
                }))
                (folder / "claims.json").write_text(json.dumps({
                    "claims": [
                        {
                            "id": "L1",
                            "quote": "$100",
                            "importance": "material",
                            "inventory_ids": ["INV1"],
                        },
                        {
                            "id": "L2",
                            "quote": "42 units",
                            "importance": "material",
                            "inventory_ids": ["INV2"],
                        },
                    ],
                }))
                units_check = {
                    "id": "C2",
                    "claim_id": "L2",
                    "type": "semantic",
                    "basis": "report" if units_verdict == "not_checkable"
                    else "evidence",
                    "verdict": units_verdict,
                    "importance": "material",
                    "report_quote": "42 units",
                    "explanation": "Units could not be checked."
                    if units_verdict == "not_checkable" else "Units match.",
                }
                if units_verdict == "confirmed":
                    units_check["evidence_file"] = "ev.json"
                    units_check["evidence_json"] = [
                        {"pointer": "/units", "value": "42 units"}]
                (folder / "checks.json").write_text(json.dumps({
                    "checks": [
                        {
                            "id": "C1",
                            "claim_id": "L1",
                            "type": "semantic",
                            "basis": "evidence",
                            "verdict": "confirmed",
                            "importance": "material",
                            "report_quote": "$100",
                            "evidence_file": "ev.json",
                            "evidence_json": [{"pointer": "/revenue", "value": "$100"}],
                            "explanation": "Revenue matches.",
                        },
                        units_check,
                    ],
                    "presentation": {
                        "summary": MALICIOUS_SUMMARY,
                        "check_ids": ["C1"],
                        "actions": [{
                            "id": "A1",
                            "text": MALICIOUS_ACTION,
                            "report_quote": "Revenue is $100.",
                            "check_ids": ["C1"],
                        }],
                        "limits": [{
                            "id": "L1",
                            "text": MALICIOUS_ACTION,
                            "report_quote": "Revenue is $100.",
                            "check_ids": ["C1"],
                        }],
                    },
                }))
                self.assertEqual(run_mod(html_arith, "html_arith.py", [
                    "--report", str(report),
                    "--out", str(folder / "findings.json"),
                ]), 0)
                self.assertEqual(run_mod(accept, "accept.py", [
                    "--report", str(report),
                    "--claims", str(folder / "claims.json"),
                    "--checks", str(folder / "checks.json"),
                    "--findings", str(folder / "findings.json"),
                    "--evidence-dir", str(folder),
                    "--out", str(folder / "receipts.json"),
                ]), 0)
                receipts = json.loads((folder / "receipts.json").read_text())
                self.assertEqual(receipts["inventory_missing"], [])
                out = folder / "artifact"
                self.assertEqual(run_mod(render, "render.py", [
                    "--findings", str(folder / "findings.json"),
                    "--layer2", str(folder / "receipts.json"),
                    "--out-dir", str(out),
                    "--run-id", f"pres-{label}",
                ]), 0)
                art = json.loads((out / "grade-artifact.json").read_text())
                self.assertEqual(art["verdict"], expected)
                page = (out / "grade-artifact.html").read_text()
                self.assertNotIn("<b>Next:</b>", page)
                blob = (
                    (out / "grade-artifact.json").read_text() + page
                ).lower()
                for word in PROMISE_WORDS:
                    self.assertNotIn(word, blob, word)
                self.assertNotIn(MALICIOUS_SUMMARY.lower(), blob)
                self.assertNotIn(MALICIOUS_ACTION.lower(), blob)
                self.assertNotIn("presentation", art)

    def test_run_shaped_host_prose_stays_private(self) -> None:
        internal_path = "/var/summation/INTERNAL_PATH/report.html"
        pointer = "/units_now"
        leaks = (
            "receipts.json", internal_path, pointer, SENTINEL,
        )
        leak = " ".join(leaks)
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            report = folder / "report.html"
            report.write_text(PLANTED.read_text())
            (folder / "q3.json").write_text(
                json.dumps({"revenue_yoy": 0.098, "units": 10481, SENTINEL: SENTINEL})
                + "\n")
            (folder / "live-units.json").write_text(
                json.dumps({"units_now": 10613, "queried_at": "2026-08-23"}) + "\n")
            self.assertEqual(run_mod(html_arith, "html_arith.py", [
                "--report", str(report),
                "--out", str(folder / "findings.json"),
            ]), 0)
            findings = json.loads((folder / "findings.json").read_text())
            claims = []
            checks = []
            for index, item in enumerate(findings["inventory"]["items"], 1):
                shown = item["displayed"]
                cid = f"L{index}"
                claims.append({
                    "id": cid,
                    "quote": shown,
                    "importance": "material",
                    "inventory_ids": [item["id"]],
                })
                row = {
                    "id": f"C{index}",
                    "claim_id": cid,
                    "type": "semantic",
                    "importance": "material",
                    "report_quote": shown,
                    "explanation": leak,
                }
                if shown == "10,481":
                    row.update({
                        "basis": "evidence",
                        "verdict": "confirmed",
                        "evidence_file": "q3.json",
                        "evidence_json": [{"pointer": "/units", "value": 10481}],
                    })
                elif shown == "4.6%":
                    row.update({
                        "basis": "evidence",
                        "verdict": "contradicted",
                        "severity": "high",
                        "evidence_file": "q3.json",
                        "evidence_json": [{"pointer": "/revenue_yoy", "value": 0.098}],
                    })
                else:
                    row.update({
                        "basis": "report",
                        "verdict": "not_checkable",
                    })
                checks.append(row)
            (folder / "claims.json").write_text(json.dumps({"claims": claims}))
            (folder / "checks.json").write_text(json.dumps({
                "checks": checks,
                "presentation": {
                    "summary": leak,
                    "check_ids": [checks[0]["id"]],
                    "actions": [{
                        "id": "A1",
                        "text": leak,
                        "report_quote": "10,481",
                        "check_ids": [checks[0]["id"]],
                    }],
                    "limits": [{
                        "id": "L1",
                        "text": leak,
                        "report_quote": "10,481",
                        "check_ids": [checks[0]["id"]],
                    }],
                },
            }))
            findings["source"]["path"] = internal_path
            (folder / "findings.json").write_text(json.dumps(findings))
            self.assertEqual(run_mod(accept, "accept.py", [
                "--report", str(report),
                "--claims", str(folder / "claims.json"),
                "--checks", str(folder / "checks.json"),
                "--findings", str(folder / "findings.json"),
                "--evidence-dir", str(folder),
                "--out", str(folder / "receipts.json"),
            ]), 0)
            receipts_text = (folder / "receipts.json").read_text()
            for item in leaks:
                self.assertIn(item, receipts_text, item)
            (folder / "source.json").write_text(json.dumps({
                "status": "complete",
                "error": None,
                "provider": "sum-api",
                "profile": leak,
                "source_identity": {"path": internal_path},
                "suggested_source": leak,
                "generated_at": "2026-08-25T00:00:00Z",
                "tables": ["q3.json", "live-units.json"],
                "confirmed": 1,
                "contradicted": 0,
                "not_run": 0,
                "checks": [{"id": "SRC1", "pointer": pointer, "secret": SENTINEL}],
            }))
            out = folder / "artifact"
            self.assertEqual(run_mod(render, "render.py", [
                "--findings", str(folder / "findings.json"),
                "--layer2", str(folder / "receipts.json"),
                "--source", str(folder / "source.json"),
                "--out-dir", str(out),
                "--run-id", "privacy-run",
            ]), 0)
            art_path = out / "grade-artifact.json"
            html_path = out / "grade-artifact.html"
            public = art_path.read_text() + html_path.read_text()
            for item in leaks:
                self.assertNotIn(item, public, item)
            self.assertIn("q3.json", public)
            self.assertNotIn("live-units.json", public)
            art = json.loads(art_path.read_text())
            self.assertEqual(art["verdict"], "fix_first")
            for row in art.get("evidence_checks") or []:
                self.assertEqual(row.get("explanation"), render.public_explanation(row))
                self.assertNotIn("q3.json", row.get("explanation") or "")
            page = html_path.read_text()
            self.assertIn("9,000", page)
            self.assertIn("FIX FIRST", page)
            self.assertIn("<b>Next:</b>", page)
            self.assertNotIn("receipts.json", page)

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
