"""Answer-keyed MD/PDF/XLSX/PPTX extraction and grade regressions."""
from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "verify" / "scripts"
FIX = pathlib.Path("/Users/ericjaffe/Documents/GitHub/alg-deploy/fixtures-format")
ART = pathlib.Path("/private/tmp/alg-verify-format-impl-artifacts")

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(SCRIPTS))
from test_verify_render import run_mod, accept, render  # noqa: E402
import inventory  # noqa: E402

EXTRACT = SCRIPTS / "extract.py"

MD_CLEAN = FIX / "markdown-status/clean/weekly-project-status.md"
MD_PLANTED = FIX / "markdown-status/stale/weekly-project-status.md"
MD_EV = FIX / "markdown-status/stale/evidence"
PDF_CLEAN = FIX / "pdf-top5/clean/top-5-segments-clean.pdf"
PDF_PLANTED = FIX / "pdf-top5/twin/top-5-segments-twin.pdf"
XLSX_CLEAN = FIX / "xlsx-margin/clean/weekly-margin-summary-clean.xlsx"
XLSX_PLANTED = FIX / "xlsx-margin/twin/weekly-margin-summary-twin.xlsx"
PPTX_CLEAN = FIX / "pptx-kpi/clean/operations-kpi-clean.pptx"
PPTX_PLANTED = FIX / "pptx-kpi/twin/operations-kpi-twin.pptx"

M1 = "Data is current through August 11, 2026."
M2 = "Active projects: 10"
M3 = "Projects at risk: 1"
M4 = "The at-risk list is unchanged from the prior week."
P1 = "Ranked from highest to lowest revenue."
X1 = "Note: gross margin improved 3% week over week."
T1 = "96%"
PDF_SOURCE = "Source snapshot: CRM revenue export, 2026-07-05."
MD_SOURCE = "Source snapshot: `evidence/project-status.json`."
SPEAKER_NOTE = (
    "The headline must match 94 on-time deliveries out of 100 total."
)
XLSX_MATERIAL = (
    "412,385.22", "428,919.75", "247,431.13", "244,483.26",
    "164,954.09", "184,436.49", "40.0%", "43.0%",
)


def run_extract(report: pathlib.Path, visible: pathlib.Path, findings: pathlib.Path) -> int:
    proc = subprocess.run(
        ["uv", "run", str(EXTRACT), "--report", str(report),
         "--visible", str(visible), "--out", str(findings)],
        capture_output=True, text=True,
    )
    if proc.returncode not in {0, 2}:
        raise AssertionError(proc.stderr or proc.stdout)
    return proc.returncode


def material_shown(findings: dict) -> list[str]:
    return [
        item["displayed"]
        for item in findings["inventory"]["items"]
        if item.get("importance") == "material"
    ]


def grade(folder: pathlib.Path, report: pathlib.Path, *,
          claims: list, checks: list, evidence_dir: pathlib.Path | None,
          run_id: str) -> tuple[dict, str]:
    visible = folder / "report-visible.txt"
    findings_path = folder / "findings.json"
    self_code = run_extract(report, visible, findings_path)
    if self_code != 0:
        raise AssertionError("extract failed")
    findings = json.loads(findings_path.read_text())
    by_shown = {
        item["displayed"]: item
        for item in findings["inventory"]["items"]
    }
    for claim in claims:
        shown = claim["quote"]
        item = by_shown[shown]
        claim["inventory_ids"] = [item["id"]]
        if claim.get("classification") == "supporting_provenance":
            claim["importance"] = "supporting"
        else:
            claim.setdefault("importance", item.get("importance") or "material")
    (folder / "claims.json").write_text(json.dumps({"claims": claims}))
    (folder / "checks.json").write_text(json.dumps({"checks": checks}))
    ev = evidence_dir if evidence_dir is not None else folder
    code = run_mod(accept, "accept.py", [
        "--report", str(report),
        "--report-text", str(visible),
        "--claims", str(folder / "claims.json"),
        "--checks", str(folder / "checks.json"),
        "--findings", str(findings_path),
        "--evidence-dir", str(ev),
        "--out", str(folder / "receipts.json"),
    ])
    if code != 0:
        raise AssertionError("accept failed")
    out = folder / "artifact"
    code = run_mod(render, "render.py", [
        "--findings", str(findings_path),
        "--layer2", str(folder / "receipts.json"),
        "--out-dir", str(out),
        "--run-id", run_id,
    ])
    if code != 0:
        raise AssertionError("render failed: " + (folder / "receipts.json").read_text()[:2000])
    art = json.loads((out / "grade-artifact.json").read_text())
    page = (out / "grade-artifact.html").read_text()
    dest = ART / run_id
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "grade-artifact.json").write_text((out / "grade-artifact.json").read_text())
    (dest / "grade-artifact.html").write_text(page)
    return art, page


def provenance_claim(cid: str, quote: str) -> dict:
    return {
        "id": cid,
        "quote": quote,
        "importance": "supporting",
        "classification": "supporting_provenance",
        "reason": (
            "The line names only a source identity or extraction date. "
            "It asserts no KPI, status, or other analytical result."
        ),
    }


def confirmed_report(cid: str, claim_id: str, quote: str) -> dict:
    return {
        "id": cid,
        "claim_id": claim_id,
        "type": "semantic",
        "basis": "report",
        "verdict": "confirmed",
        "importance": "material",
        "report_quote": quote,
        "explanation": "Matches the report.",
    }


def contradicted_report(cid: str, claim_id: str, quote: str, quote2: str) -> dict:
    return {
        "id": cid,
        "claim_id": claim_id,
        "type": "semantic",
        "basis": "report",
        "verdict": "contradicted",
        "severity": "high",
        "importance": "material",
        "report_quote": quote,
        "report_quote_2": quote2,
        "explanation": "The report contradicts itself.",
    }


def parse_date_value(value) -> tuple[int, int, int] | None:
    text = str(value or "")
    match = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    if not match:
        return None
    return tuple(int(part) for part in match.groups())


def contradicted_evidence(cid: str, claim_id: str, quote: str, pointer: str, value) -> dict:
    return {
        "id": cid,
        "claim_id": claim_id,
        "type": "semantic",
        "basis": "evidence",
        "verdict": "contradicted",
        "severity": "high",
        "importance": "material",
        "report_quote": quote,
        "evidence_file": "project-status.json",
        "evidence_json": [{"pointer": pointer, "value": value}],
        "explanation": "The evidence does not match.",
    }


@unittest.skipUnless(FIX.is_dir(), "alg-deploy fixtures are not present")
class FormatInventoryTests(unittest.TestCase):
    def test_md_planted_inventories_m1_to_m4(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            self.assertEqual(run_extract(
                MD_PLANTED, folder / "v.txt", folder / "f.json"), 0)
            shown = material_shown(json.loads((folder / "f.json").read_text()))
            for needle in (M1, M2, M3, M4):
                self.assertIn(needle, shown)

    def test_pptx_inventory_excludes_speaker_notes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            self.assertEqual(run_extract(
                PPTX_PLANTED, folder / "v.txt", folder / "f.json"), 0)
            blob = json.dumps(json.loads((folder / "f.json").read_text())["inventory"])
            self.assertNotIn(SPEAKER_NOTE, blob)
            shown = material_shown(json.loads((folder / "f.json").read_text()))
            self.assertIn(T1, shown)

    def test_xlsx_inventories_note_and_margin_cells(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            self.assertEqual(run_extract(
                XLSX_PLANTED, folder / "v.txt", folder / "f.json"), 0)
            shown = material_shown(json.loads((folder / "f.json").read_text()))
            self.assertIn(X1, shown)
            for cell in XLSX_MATERIAL:
                self.assertIn(cell, shown)


@unittest.skipUnless(FIX.is_dir(), "alg-deploy fixtures are not present")
class FormatGradeTests(unittest.TestCase):
    def test_md_clean_is_safe_to_share(self) -> None:
        quotes = [
            "Data is current through August 14, 2026.",
            "Active projects: 12",
            "Projects at risk: 3",
            "Projects blocked: 1",
            "The at-risk list increased by one project during the week.",
        ]
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            claims = [{"id": f"L{i}", "quote": q} for i, q in enumerate(quotes, 1)]
            claims.append(provenance_claim(f"L{len(quotes) + 1}", MD_SOURCE))
            checks = [
                confirmed_report(f"C{i}", f"L{i}", q) for i, q in enumerate(quotes, 1)]
            art, page = grade(
                folder, MD_CLEAN, claims=claims, checks=checks,
                evidence_dir=MD_EV, run_id="md-clean")
            self.assertEqual(art["verdict"], "safe_to_share")
            self.assertNotIn("<b>Next:</b>", page)

    def test_md_planted_finds_m1_m4(self) -> None:
        rows = [
            (M1, contradicted_evidence("C1", "L1", M1, "/latest_complete_date", "2026-08-14")),
            (M2, contradicted_evidence("C2", "L2", M2, "/active_projects", 12)),
            (M3, contradicted_evidence("C3", "L3", M3, "/at_risk_projects", 3)),
            ("Projects blocked: 1", confirmed_report("C4", "L4", "Projects blocked: 1")),
            (M4, contradicted_evidence("C5", "L5", M4, "/prior_week_at_risk_projects", 2)),
        ]
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            claims = [{"id": f"L{i}", "quote": q} for i, (q, _) in enumerate(rows, 1)]
            claims.append(provenance_claim(f"L{len(rows) + 1}", MD_SOURCE))
            checks = [row[1] for row in rows]
            art, page = grade(
                folder, MD_PLANTED, claims=claims, checks=checks,
                evidence_dir=MD_EV, run_id="md-planted")
            self.assertEqual(art["verdict"], "fix_first")
            self.assertIn("August 11, 2026", page)
            self.assertIn("<b>Next:</b>", page)

    def test_codex_m1_not_checkable_is_contradicted_with_m2_m4(self) -> None:
        """Prior Codex run inventoried M1 then marked it not_checkable. That fails."""
        rows = [
            (M1, {
                "id": "C1",
                "claim_id": "L1",
                "type": "staleness",
                "basis": "evidence",
                "verdict": "not_checkable",
                "importance": "material",
                "report_quote": M1,
                "explanation": "No live source was queried for the currency date.",
            }),
            (M2, contradicted_evidence("C2", "L2", M2, "/active_projects", 12)),
            (M3, contradicted_evidence("C3", "L3", M3, "/at_risk_projects", 3)),
            ("Projects blocked: 1", confirmed_report("C4", "L4", "Projects blocked: 1")),
            (M4, contradicted_evidence("C5", "L5", M4, "/prior_week_at_risk_projects", 2)),
        ]
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            claims = [{"id": f"L{i}", "quote": q} for i, (q, _) in enumerate(rows, 1)]
            claims.append(provenance_claim(f"L{len(rows) + 1}", MD_SOURCE))
            checks = [row[1] for row in rows]
            art, page = grade(
                folder, MD_PLANTED, claims=claims, checks=checks,
                evidence_dir=MD_EV, run_id="md-planted-codex-m1")
            receipts = json.loads((folder / "receipts.json").read_text())
            by_quote = {row.get("quote"): row for row in receipts["claims"]}
            self.assertEqual(by_quote[M1]["outcome"], "contradicted")
            self.assertEqual(by_quote[M2]["outcome"], "contradicted")
            self.assertEqual(by_quote[M3]["outcome"], "contradicted")
            self.assertEqual(by_quote[M4]["outcome"], "contradicted")
            m1_checks = [
                row for row in receipts["checks"]
                if row.get("claim_id") == "L1" and row.get("verdict") == "contradicted"]
            self.assertTrue(m1_checks)
            pointers = [
                item.get("pointer")
                for row in m1_checks
                for item in (row.get("evidence_json") or [])
            ]
            self.assertTrue(pointers)
            self.assertTrue(any(parse_date_value(item.get("value")) == (2026, 8, 14)
                                for row in m1_checks
                                for item in (row.get("evidence_json") or [])))
            self.assertEqual(art["verdict"], "fix_first")
            self.assertIn("August 11, 2026", page)

    def test_pdf_clean_is_safe_to_share(self) -> None:
        quotes = [
            "Top 5 customer segments - Q2 2026",
            P1,
            "Enterprise", "$520", "Mid-market", "$410", "SMB", "$305",
            "Startup", "$190", "Education", "$120",
            "The ranking is complete and follows the displayed revenue values.",
        ]
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            claims = [{"id": f"L{i}", "quote": q} for i, q in enumerate(quotes, 1)]
            claims.append(provenance_claim(f"L{len(quotes) + 1}", PDF_SOURCE))
            checks = [
                confirmed_report(f"C{i}", f"L{i}", q) for i, q in enumerate(quotes, 1)]
            art, page = grade(
                folder, PDF_CLEAN, claims=claims, checks=checks,
                evidence_dir=None, run_id="pdf-clean")
            self.assertEqual(art["verdict"], "safe_to_share")
            self.assertNotIn("<b>Next:</b>", page)

    def test_pdf_twin_finds_p1_only(self) -> None:
        quotes = [
            "Top 5 customer segments - Q2 2026",
            P1,
            "Enterprise", "$520", "SMB", "$305", "Mid-market", "$410",
            "Startup", "$190", "Education", "$120",
            "The ranking is presented as final for the quarter.",
        ]
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            claims = [{"id": f"L{i}", "quote": q} for i, q in enumerate(quotes, 1)]
            claims.append(provenance_claim(f"L{len(quotes) + 1}", PDF_SOURCE))
            checks = []
            for i, q in enumerate(quotes, 1):
                if q == P1:
                    checks.append(contradicted_report(
                        f"C{i}", f"L{i}", P1, "Mid-market"))
                else:
                    checks.append(confirmed_report(f"C{i}", f"L{i}", q))
            art, page = grade(
                folder, PDF_PLANTED, claims=claims, checks=checks,
                evidence_dir=None, run_id="pdf-planted")
            self.assertEqual(art["verdict"], "fix_first")
            self.assertIn(P1, page)
            contradicted = [
                row for row in art["evidence_checks"]
                if row.get("verdict") == "contradicted"]
            self.assertEqual(len(contradicted), 1)

    def test_xlsx_clean_completes_material_and_is_safe(self) -> None:
        note = "Note: gross margin improved 3 percentage points week over week."
        quotes = list(XLSX_MATERIAL) + [note]
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            claims = [{"id": f"L{i}", "quote": q} for i, q in enumerate(quotes, 1)]
            checks = [
                confirmed_report(f"C{i}", f"L{i}", q) for i, q in enumerate(quotes, 1)]
            art, page = grade(
                folder, XLSX_CLEAN, claims=claims, checks=checks,
                evidence_dir=None, run_id="xlsx-clean")
            self.assertEqual(art["verdict"], "safe_to_share")
            receipts = json.loads((folder / "receipts.json").read_text())
            material = [
                row for row in receipts["claims"] if row.get("importance") == "material"]
            self.assertGreaterEqual(len(material), 5)
            self.assertTrue(all(
                row.get("outcome") not in (None, "not_reached") for row in material))
            self.assertNotIn("<b>Next:</b>", page)

    def test_xlsx_twin_finds_x1_and_completes_material(self) -> None:
        quotes = list(XLSX_MATERIAL) + [X1]
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            claims = [{"id": f"L{i}", "quote": q} for i, q in enumerate(quotes, 1)]
            checks = []
            for i, q in enumerate(quotes, 1):
                if q == X1:
                    checks.append(contradicted_report(f"C{i}", f"L{i}", X1, "43.0%"))
                else:
                    checks.append(confirmed_report(f"C{i}", f"L{i}", q))
            art, page = grade(
                folder, XLSX_PLANTED, claims=claims, checks=checks,
                evidence_dir=None, run_id="xlsx-planted")
            self.assertEqual(art["verdict"], "fix_first")
            receipts = json.loads((folder / "receipts.json").read_text())
            material = [
                row for row in receipts["claims"] if row.get("importance") == "material"]
            self.assertTrue(all(
                row.get("outcome") not in (None, "not_reached") for row in material))
            self.assertIn("3%", page)
            self.assertIn("40.0%", page)
            self.assertIn("43.0%", page)
            self.assertIn("3.0 percentage-point", page)
            self.assertIn("not a 3% relative", page)
            self.assertNotIn("The report claim", page)
            contradicted = [
                row for row in art["evidence_checks"]
                if row.get("verdict") == "contradicted"]
            self.assertEqual(len(contradicted), 1)
            self.assertAlmostEqual(
                float((art.get("score") or {}).get("value") or 0),
                100.0 / 9, places=3)

    def test_pptx_clean_is_safe_to_share(self) -> None:
        quotes = [
            "Q2 operations review",
            "94%",
            "On-time deliveries in Q2",
            "Appendix: delivery calculation",
            "94 on-time deliveries / 100 total deliveries = 94%",
        ]
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            claims = [{"id": f"L{i}", "quote": q} for i, q in enumerate(quotes, 1)]
            checks = [
                confirmed_report(f"C{i}", f"L{i}", q) for i, q in enumerate(quotes, 1)]
            art, page = grade(
                folder, PPTX_CLEAN, claims=claims, checks=checks,
                evidence_dir=None, run_id="pptx-clean")
            self.assertEqual(art["verdict"], "safe_to_share")
            self.assertNotIn(SPEAKER_NOTE, page)
            self.assertNotIn("<b>Next:</b>", page)

    def test_md_omitted_material_writes_no_artifact(self) -> None:
        quotes = [
            "Data is current through August 14, 2026.",
            "Active projects: 12",
        ]
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            claims = [{"id": f"L{i}", "quote": q} for i, q in enumerate(quotes, 1)]
            checks = [
                confirmed_report(f"C{i}", f"L{i}", q) for i, q in enumerate(quotes, 1)]
            with self.assertRaises(AssertionError):
                grade(
                    folder, MD_CLEAN, claims=claims, checks=checks,
                    evidence_dir=MD_EV, run_id="md-omit")
            self.assertFalse((folder / "artifact" / "grade-artifact.html").is_file())
            self.assertFalse((folder / "artifact" / "grade-artifact.json").is_file())

    def test_pptx_twin_finds_t1_only_without_speaker_note_error(self) -> None:
        quotes = [
            "Q2 operations review",
            T1,
            "On-time deliveries in Q2",
            "Appendix: delivery calculation",
            "94 on-time deliveries / 100 total deliveries = 94%",
        ]
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            claims = [{"id": f"L{i}", "quote": q} for i, q in enumerate(quotes, 1)]
            checks = []
            for i, q in enumerate(quotes, 1):
                if q == T1:
                    checks.append(contradicted_report(
                        f"C{i}", f"L{i}", T1,
                        "94 on-time deliveries / 100 total deliveries = 94%"))
                else:
                    checks.append(confirmed_report(f"C{i}", f"L{i}", q))
            art, page = grade(
                folder, PPTX_PLANTED, claims=claims, checks=checks,
                evidence_dir=None, run_id="pptx-planted")
            self.assertEqual(art["verdict"], "fix_first")
            self.assertIn("96%", page)
            self.assertNotIn(SPEAKER_NOTE, page)
            contradicted = [
                row for row in art["evidence_checks"]
                if row.get("verdict") == "contradicted"]
            self.assertEqual(len(contradicted), 1)

    def test_codex_clean_pdf_xlsx_pptx_not_checkable_become_safe(self) -> None:
        cases = [
            (PDF_CLEAN, [
                "Top 5 customer segments - Q2 2026",
                P1, "Enterprise", "$520", "Mid-market", "$410", "SMB", "$305",
                "Startup", "$190", "Education", "$120",
                "The ranking is complete and follows the displayed revenue values.",
            ], "pdf-clean-codex"),
            (XLSX_CLEAN, list(XLSX_MATERIAL) + [
                "Note: gross margin improved 3 percentage points week over week.",
            ], "xlsx-clean-codex"),
            (PPTX_CLEAN, [
                "Q2 operations review", "94%", "On-time deliveries in Q2",
                "Appendix: delivery calculation",
                "94 on-time deliveries / 100 total deliveries = 94%",
            ], "pptx-clean-codex"),
        ]
        for report, quotes, run_id in cases:
            with self.subTest(run_id=run_id), tempfile.TemporaryDirectory() as raw:
                folder = pathlib.Path(raw)
                claims = [{"id": f"L{i}", "quote": q} for i, q in enumerate(quotes, 1)]
                if report == PDF_CLEAN:
                    claims.append(provenance_claim(f"L{len(quotes) + 1}", PDF_SOURCE))
                checks = [
                    {
                        "id": f"C{i}",
                        "claim_id": f"L{i}",
                        "type": "semantic",
                        "basis": "evidence",
                        "verdict": "not_checkable",
                        "importance": "material",
                        "report_quote": q,
                        "explanation": "No external source was supplied.",
                    }
                    for i, q in enumerate(quotes, 1)
                ]
                art, page = grade(
                    folder, report, claims=claims, checks=checks,
                    evidence_dir=None, run_id=run_id)
                self.assertEqual(art["verdict"], "safe_to_share")
                self.assertNotIn("<b>Next:</b>", page)
                receipts = json.loads((folder / "receipts.json").read_text())
                material = [
                    row for row in receipts["claims"]
                    if row.get("importance") == "material"]
                self.assertTrue(material)
                self.assertTrue(all(
                    row.get("outcome") not in (None, "not_reached", "not_checkable")
                    for row in material))

    def test_codex_planted_major_is_fix_first_in_json_and_html(self) -> None:
        cases = [
            (PDF_PLANTED, [
                "Top 5 customer segments - Q2 2026",
                P1, "Enterprise", "$520", "SMB", "$305", "Mid-market", "$410",
                "Startup", "$190", "Education", "$120",
                "The ranking is presented as final for the quarter.",
            ], P1, "pdf-planted-codex"),
            (XLSX_PLANTED, list(XLSX_MATERIAL) + [X1], X1, "xlsx-planted-codex"),
            (PPTX_PLANTED, [
                "Q2 operations review", T1, "On-time deliveries in Q2",
                "Appendix: delivery calculation",
                "94 on-time deliveries / 100 total deliveries = 94%",
            ], T1, "pptx-planted-codex"),
        ]
        for report, quotes, needle, run_id in cases:
            with self.subTest(run_id=run_id), tempfile.TemporaryDirectory() as raw:
                folder = pathlib.Path(raw)
                claims = [{"id": f"L{i}", "quote": q} for i, q in enumerate(quotes, 1)]
                if report == PDF_PLANTED:
                    claims.append(provenance_claim(f"L{len(quotes) + 1}", PDF_SOURCE))
                checks = []
                for i, q in enumerate(quotes, 1):
                    if q == needle:
                        second = {
                            P1: "Mid-market",
                            X1: "43.0%",
                            T1: "94 on-time deliveries / 100 total deliveries = 94%",
                        }[needle]
                        row = contradicted_report(f"C{i}", f"L{i}", q, second)
                        row["severity"] = "major"
                        checks.append(row)
                    else:
                        checks.append({
                            "id": f"C{i}",
                            "claim_id": f"L{i}",
                            "type": "semantic",
                            "basis": "evidence",
                            "verdict": "not_checkable",
                            "importance": "material",
                            "report_quote": q,
                            "explanation": "No external source was supplied.",
                        })
                art, page = grade(
                    folder, report, claims=claims, checks=checks,
                    evidence_dir=None, run_id=run_id)
                self.assertEqual(art["verdict"], "fix_first")
                self.assertIn("<b>Next:</b>", page)
                self.assertIn("FIX FIRST", page)
                self.assertIn(needle.split()[0] if needle != T1 else "96%", page)
                for row in art["evidence_checks"]:
                    if row.get("verdict") == "contradicted":
                        self.assertIn(row.get("severity"), {"high", "medium", "low"})

    def test_host_contradiction_cannot_override_clean_pdf_rank(self) -> None:
        quotes = [
            "Top 5 customer segments - Q2 2026",
            P1,
            "Enterprise", "$520", "Mid-market", "$410", "SMB", "$305",
            "Startup", "$190", "Education", "$120",
            "The ranking is complete and follows the displayed revenue values.",
        ]
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            claims = [{"id": f"L{i}", "quote": q} for i, q in enumerate(quotes, 1)]
            claims.append(provenance_claim(f"L{len(quotes) + 1}", PDF_SOURCE))
            checks = []
            for i, q in enumerate(quotes, 1):
                if q == P1:
                    checks.append(contradicted_report(
                        f"C{i}", f"L{i}", P1, "Mid-market"))
                else:
                    checks.append(confirmed_report(f"C{i}", f"L{i}", q))
            art, page = grade(
                folder, PDF_CLEAN, claims=claims, checks=checks,
                evidence_dir=None, run_id="pdf-clean-host-conflict")
            self.assertEqual(art["verdict"], "safe_to_share")
            self.assertNotIn("<b>Next:</b>", page)
            receipts = json.loads((folder / "receipts.json").read_text())
            rank = next(
                row for row in receipts["claims"] if row.get("quote") == P1)
            self.assertEqual(rank["outcome"], "confirmed")
            self.assertTrue(any(
                "deterministic-conflict" in str(row.get("problems"))
                for row in receipts["discarded"]))

    def test_host_confirmation_cannot_override_planted_pdf_rank(self) -> None:
        quotes = [
            "Top 5 customer segments - Q2 2026",
            P1,
            "Enterprise", "$520", "SMB", "$305", "Mid-market", "$410",
            "Startup", "$190", "Education", "$120",
            "The ranking is presented as final for the quarter.",
        ]
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            claims = [{"id": f"L{i}", "quote": q} for i, q in enumerate(quotes, 1)]
            claims.append(provenance_claim(f"L{len(quotes) + 1}", PDF_SOURCE))
            checks = [
                confirmed_report(f"C{i}", f"L{i}", q) for i, q in enumerate(quotes, 1)]
            art, page = grade(
                folder, PDF_PLANTED, claims=claims, checks=checks,
                evidence_dir=None, run_id="pdf-planted-host-override")
            self.assertEqual(art["verdict"], "fix_first")
            self.assertIn(P1, page)
            receipts = json.loads((folder / "receipts.json").read_text())
            rank = next(
                row for row in receipts["claims"] if row.get("quote") == P1)
            self.assertEqual(rank["outcome"], "contradicted")


if __name__ == "__main__":
    unittest.main()
