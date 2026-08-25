"""Public artifact must show the proof: values, calculation, and one explanation."""
from __future__ import annotations

import json
import pathlib
import re
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "verify" / "scripts"
FIX = pathlib.Path("/Users/ericjaffe/Documents/GitHub/alg-deploy/fixtures-format")
X1 = "Note: gross margin improved 3% week over week."
XLSX_MATERIAL = (
    "412,385.22", "428,919.75", "247,431.13", "244,483.26",
    "164,954.09", "184,436.49", "40.0%", "43.0%",
)
XLSX_PLANTED = FIX / "xlsx-margin/twin/weekly-margin-summary-twin.xlsx"
GENERIC = re.compile(
    r'The report claim\s+(?:&quot;|").*?(?:&quot;|")\s+is (?:confirmed|contradicted)',
    re.I,
)

sys_path_setup = True
import sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(SCRIPTS))
from test_verify_formats import grade  # noqa: E402
from test_verify_render import render  # noqa: E402
import internal  # noqa: E402
import inventory  # noqa: E402


def audit_page(page: str, art: dict) -> list[str]:
    problems = []
    if GENERIC.search(page):
        problems.append("generic verdict prose in HTML")
    cards = re.findall(
        r'<div class="card (?:err|ok)" data-kind="[^"]+">(.*?)</div>\s*(?=<div class="card|</section>|$)',
        page, re.S)
    for card in cards:
        explanations = re.findall(r"<p>(.*?)</p>", card, re.S)
        if len(explanations) > 1:
            problems.append("more than one explanation paragraph in a card")
        receipt = re.search(
            r'<div class="k">[^<]*</div><div class="q">(.*?)</div>\s*'
            r'<div class="k">[^<]*</div><div class="q">(.*?)</div>',
            card, re.S)
        if receipt and explanations:
            evidence = re.sub(r"<[^>]+>", " ", receipt.group(2))
            why = re.sub(r"<[^>]+>", " ", explanations[0])
            if evidence.strip() and why.strip() and evidence.strip() == why.strip():
                problems.append("receipt duplicates the explanation paragraph")
        if 'data-kind="error"' in card or "class=\"card err\"" in card:
            if "40.0%" in page and X1 in page:
                if "percentage-point" not in card and "percentage points" not in card:
                    problems.append("INT9 card missing percentage-point calculation")
    coverage = art.get("evidence_coverage") or {}
    total = int(coverage.get("document_claims_total") or 0)
    reached = int(coverage.get("document_claims_reached") or 0)
    if total and "All" in page and "were checked" in page and reached < total:
        problems.append("headline says all claims were checked while coverage is partial")
    h1 = re.search(r"<h1>(.*?)</h1>", page, re.S)
    if h1 and "All" in h1.group(1) and reached < total:
        problems.append("h1 all-checked contradicts coverage")
    score = art.get("score") or {}
    contradicted = int(coverage.get("contradicted") or 0)
    if contradicted and score.get("kind") == "tier_d_per_100_claims":
        if float(score.get("value") or 0) == 0:
            problems.append("score is 0 despite material contradictions")
    return problems


@unittest.skipUnless(FIX.is_dir(), "alg-deploy fixtures are not present")
class Int9PublicEvidenceTests(unittest.TestCase):
    def test_xlsx_planted_int9_shows_points_not_percent(self) -> None:
        quotes = list(XLSX_MATERIAL) + [X1]
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            claims = [{"id": f"L{i}", "quote": q} for i, q in enumerate(quotes, 1)]
            checks = [
                {
                    "id": f"C{i}",
                    "claim_id": f"L{i}",
                    "type": "semantic",
                    "basis": "report",
                    "verdict": "confirmed",
                    "importance": "material",
                    "report_quote": q,
                    "explanation": "Matches the report.",
                }
                for i, q in enumerate(quotes, 1)
            ]
            checks[-1]["verdict"] = "contradicted"
            checks[-1]["severity"] = "high"
            checks[-1]["report_quote_2"] = "43.0%"
            art, page = grade(
                folder, XLSX_PLANTED, claims=claims, checks=checks,
                evidence_dir=None, run_id="xlsx-int9-evidence")
            self.assertEqual(art["verdict"], "fix_first")
            self.assertIn(X1, page)
            self.assertIn("40.0%", page)
            self.assertIn("43.0%", page)
            self.assertIn("3.0 percentage-point", page)
            self.assertIn("not a 3% relative", page)
            self.assertIn("Weekly Margin sheet", page)
            self.assertNotRegex(page, GENERIC)
            self.assertNotIn("The report claim", page)
            row = next(
                item for item in art["evidence_checks"]
                if item.get("verdict") == "contradicted")
            self.assertIn("percentage-point", row.get("explanation") or "")
            comparison = row.get("comparison") or {}
            self.assertEqual(comparison.get("prior"), "40.0%")
            self.assertEqual(comparison.get("current"), "43.0%")
            self.assertIn("3.0", str(comparison.get("result") or ""))
            score = art.get("score") or {}
            self.assertEqual(score.get("kind"), "tier_d_per_100_claims")
            self.assertAlmostEqual(float(score["value"]), 100.0 / 9, places=3)
            problems = audit_page(page, art)
            self.assertEqual(problems, [])
            receipts = json.loads((folder / "receipts.json").read_text())
            int9 = next(
                item for item in receipts["checks"]
                if item.get("report_quote") == X1)
            self.assertTrue(int9.get("comparison"))

    def test_confirmed_cards_show_matching_value_not_verdict_stamp(self) -> None:
        quotes = list(XLSX_MATERIAL) + [X1]
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            claims = [{"id": f"L{i}", "quote": q} for i, q in enumerate(quotes, 1)]
            checks = [
                {
                    "id": f"C{i}",
                    "claim_id": f"L{i}",
                    "type": "semantic",
                    "basis": "report",
                    "verdict": "confirmed" if q != X1 else "contradicted",
                    "importance": "material",
                    "report_quote": q,
                    "severity": "high" if q == X1 else None,
                    "report_quote_2": "43.0%" if q == X1 else None,
                    "explanation": "Matches the report.",
                }
                for i, q in enumerate(quotes, 1)
            ]
            art, page = grade(
                folder, XLSX_PLANTED, claims=claims, checks=checks,
                evidence_dir=None, run_id="xlsx-confirmed-evidence")
            confirmed = [
                row for row in art["evidence_checks"]
                if row.get("verdict") == "confirmed"]
            self.assertTrue(confirmed)
            for row in confirmed:
                expl = row.get("explanation") or ""
                self.assertFalse(GENERIC.search(expl), expl)
                self.assertTrue(
                    row.get("comparison") or row.get("observed") or expl,
                    row.get("id"),
                )
            self.assertIn("412,385.22", page)
            self.assertIn("Calculation", page)


class CoverageAndScoreTests(unittest.TestCase):
    def test_safe_headline_does_not_claim_all_when_supporting_unreached(self) -> None:
        from test_verify_render import _minimal_art, _check
        art = _minimal_art([_check("confirmed")])
        art["verdict"] = "safe_to_share"
        art["claims"] = [
            {
                "id": "L1", "quote": "Ranked from highest to lowest revenue.",
                "importance": "material", "outcome": "confirmed", "check_id": "id-confirmed",
            },
            {
                "id": "L2", "quote": "Source snapshot: CRM revenue export, 2026-07-05.",
                "importance": "supporting", "classification": "supporting_provenance",
                "outcome": "not_reached", "check_id": None,
            },
        ]
        art["evidence_coverage"]["document_claims_total"] = 1
        art["evidence_coverage"]["document_claims_reached"] = 1
        art["evidence_coverage"]["supporting_claims_reviewed"] = 1
        page = render.html_of(art)
        self.assertNotIn("All 2 claims were checked", page)
        self.assertNotIn("All two claims were checked", page)
        self.assertIn("material claim", page)
        self.assertIn("supporting", page.lower())
        self.assertEqual(audit_page(page, art), [])

    def test_score_uses_material_contradictions(self) -> None:
        raw = {
            "claims": [
                {"id": f"L{i}", "importance": "material",
                 "outcome": "contradicted" if i == 1 else "confirmed"}
                for i in range(1, 10)
            ],
            "coverage": {},
            "headline": {"tier_d_per_100_claims": 0},
            "findings": [],
        }
        score = render._public_score(raw, [], raw["headline"])
        self.assertAlmostEqual(score["value"], 100.0 / 9, places=5)


class ContentAuditHelpers(unittest.TestCase):
    def test_generic_verdict_is_an_audit_failure(self) -> None:
        page = (
            '<h1>Fix one error</h1>'
            '<div class="card err" data-kind="error">'
            "<p>The report claim &quot;x&quot; is contradicted.</p></div>"
        )
        art = {
            "evidence_coverage": {
                "document_claims_total": 1,
                "document_claims_reached": 1,
                "contradicted": 1,
            },
            "score": {"kind": "tier_d_per_100_claims", "value": 0},
        }
        problems = audit_page(page, art)
        self.assertTrue(any("generic" in item for item in problems))
        self.assertTrue(any("score is 0" in item for item in problems))


if __name__ == "__main__":
    unittest.main()
