"""Fail-closed artifact for the verify skill."""
from __future__ import annotations

import html
import importlib.util
import json
import pathlib
import re
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "verify" / "scripts"
FIX = ROOT / "tests" / "fixtures" / "verify" / "tiny-findings.json"
PLANTED = ROOT / "tests" / "fixtures" / "verify" / "weekly-sales-snapshot.html"

sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("verify_render", SCRIPTS / "render.py")
render = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(render)

try:
    import jsonschema  # noqa: F401
except ImportError:
    jsonschema = None

HAS_JSONSCHEMA = jsonschema is not None

accept_spec = importlib.util.spec_from_file_location(
    "verify_accept", SCRIPTS / "accept.py")
accept = importlib.util.module_from_spec(accept_spec)
assert accept_spec.loader is not None
accept_spec.loader.exec_module(accept)

arith_spec = importlib.util.spec_from_file_location(
    "verify_html_arith", SCRIPTS / "html_arith.py")
html_arith = importlib.util.module_from_spec(arith_spec)
assert arith_spec.loader is not None
arith_spec.loader.exec_module(html_arith)


def write_incomplete_md_findings(folder: pathlib.Path, extra: dict | None = None) -> None:
    """Ledger tests that skip extract.py must not pick up a complete Markdown inventory."""
    doc = {
        "findings": [],
        "coverage": {
            "claims_in_ledger": 0,
            "claims_reached_by_a_check": 0,
            "extractor_checkable_fraction": 1.0,
            "engine_checkable_fraction": 1.0,
            "checks_registered": 0,
            "checks_with_findings": 0,
            "checks_found_nothing": 0,
            "checks_errored": 0,
        },
        "source": {"path": "report.md", "format": "md", "sha256": "abc"},
        "findings_truncated": False,
        "inventory": {
            "reader": "md",
            "complete": False,
            "items": [],
            "reason": "synthetic ledger test",
        },
    }
    if extra:
        doc.update(extra)
    (folder / "findings.json").write_text(json.dumps(doc))


def claims_from_checks(checks_path: pathlib.Path) -> pathlib.Path:
    doc = json.loads(checks_path.read_text())
    items = doc if isinstance(doc, list) else list(doc.get("checks") or [])
    claims = []
    for index, check in enumerate(items, 1):
        check.setdefault("claim_id", f"L{index}")
        claims.append({
            "id": check["claim_id"],
            "quote": check.get("report_quote") or "",
            "importance": check.get("importance") or "material",
        })
    if isinstance(doc, dict):
        doc["checks"] = items
        checks_path.write_text(json.dumps(doc))
    else:
        checks_path.write_text(json.dumps({"checks": items}))
    path = checks_path.parent / "claims.json"
    path.write_text(json.dumps({"claims": claims}))
    return path


def pad_inventory(folder: pathlib.Path, report: pathlib.Path | None = None) -> None:
    """Give every material inventory item a not_checkable claim so HTML can render."""
    import inventory as invmod
    claims_path = folder / "claims.json"
    checks_path = folder / "checks.json"
    if not claims_path.is_file():
        return
    report = report or folder / "report.html"
    if not report.is_file():
        htmls = list(folder.glob("*.html"))
        report = htmls[0] if htmls else report
    items = invmod.inventory_for(report).get("items") or []
    claims_doc = json.loads(claims_path.read_text())
    claims = list(claims_doc.get("claims") or [])
    if checks_path.is_file():
        checks_doc = json.loads(checks_path.read_text())
        if isinstance(checks_doc, dict):
            checks = list(checks_doc.get("checks") or [])
            wrap = True
        else:
            checks = list(checks_doc)
            wrap = False
            checks_doc = {}
    else:
        checks, wrap, checks_doc = [], True, {}
    referenced = set()
    for claim in claims:
        referenced.update(invmod.claim_inventory_ids(claim))
    checked = {str(row.get("claim_id") or "") for row in checks}
    n = 0
    for item in items:
        if item.get("importance") != "material":
            continue
        iid = str(item.get("id") or "")
        shown = str(item.get("displayed") or "")
        if not iid:
            continue
        hit = next(
            (claim for claim in claims
             if iid in invmod.claim_inventory_ids(claim)),
            None,
        )
        if hit is not None and str(hit.get("id") or "") in checked:
            continue
        n += 1
        if hit is None:
            cid = f"P{n}"
            claims.append({
                "id": cid,
                "quote": shown,
                "importance": "material",
                "inventory_ids": [iid],
            })
            referenced.add(iid)
        else:
            cid = str(hit.get("id") or f"P{n}")
        checks.append({
            "id": f"PC{n}",
            "claim_id": cid,
            "type": "semantic",
            "basis": "report",
            "verdict": "not_checkable",
            "importance": "material",
            "report_quote": shown,
            "explanation": "No evidence file covers this inventory item.",
        })
        checked.add(cid)
    claims_doc["claims"] = claims
    claims_path.write_text(json.dumps(claims_doc))
    if wrap:
        checks_doc["checks"] = checks
        checks_path.write_text(json.dumps(checks_doc))
    else:
        checks_path.write_text(json.dumps(checks))


def run_mod(mod, name: str, args: list[str]) -> int:
    args = list(args)
    if name == "accept.py" and "--claims" not in args and "--checks" in args:
        checks_path = pathlib.Path(args[args.index("--checks") + 1])
        args.extend(["--claims", str(claims_from_checks(checks_path))])
    if name == "accept.py" and "--findings" not in args and "--checks" in args:
        sibling = pathlib.Path(args[args.index("--checks") + 1]).parent / "findings.json"
        if sibling.is_file():
            args.extend(["--findings", str(sibling)])
    argv = sys.argv
    sys.argv = [name, *args]
    try:
        return mod.main()
    finally:
        sys.argv = argv


class RenderVerdictTests(unittest.TestCase):
    def test_tiny_fixture_verdict_is_fix_first(self) -> None:
        raw = json.loads(FIX.read_text())
        self.assertEqual(render.verdict_of(raw), "fix_first")

    def test_d_finding_is_fix_first_without_a_synthetic_ledger(self) -> None:
        raw = {
            "findings": [{
                "check_id": "ari_total_footing",
                "family": "internal_arithmetic",
                "tier": "D",
                "statement": "gap",
                "claim_ids": [],
            }],
            "coverage": {
                "claims_in_ledger": 0,
                "claims_reached_by_a_check": 0,
                "extractor_checkable_fraction": 1.0,
                "engine_checkable_fraction": 1.0,
                "checks_registered": 2,
                "checks_with_findings": 1,
                "checks_found_nothing": 1,
                "checks_errored": 0,
            },
            "source": {"path": "report.html", "format": "html"},
            "findings_truncated": False,
        }
        self.assertEqual(render.verdict_of(raw), "fix_first")


SCHEMA = ROOT / "skills" / "verify" / "schema.v1.json"


def schema_claim_verdicts() -> list:
    schema = json.loads(SCHEMA.read_text())
    return list(
        schema["properties"]["evidence_checks"]["items"]["properties"]["verdict"]["enum"]
    )


def _minimal_art(evidence_checks: list) -> dict:
    contradicted = [row for row in evidence_checks if row.get("verdict") == "contradicted"]
    return {
        "schema_version": "grade-artifact/v1",
        "run_id": "parity",
        "generated_at": "2026-08-23T00:00:00Z",
        "source": {"path": "report.md", "format": "md"},
        "source_result": None,
        "verdict": "needs_review",
        "score": None,
        "findings": [],
        "evidence_checks": evidence_checks,
        "evidence_findings": contradicted,
        "evidence_coverage": {
            "document_claims_total": len(evidence_checks),
            "document_claims_reached": len(evidence_checks),
            "claim_outcomes_proposed": len(evidence_checks),
            "material_claims_reviewed": len(evidence_checks),
            "supporting_claims_reviewed": 0,
            "confirmed": 0,
            "contradicted": 0,
            "not_checkable": 0,
            "evidence_confirmed": 0,
            "evidence_contradicted": 0,
            "evidence_not_checkable": 0,
            "report_confirmed": 0,
            "report_contradicted": 0,
            "report_not_checkable": 0,
            "validated_outcomes": len(evidence_checks),
            "receipt_failures": 0,
            "evidence_files_supplied": 0,
            "evidence_files_cited": [],
            "provenance_groups": [],
            "source_independence": "not_assessed",
        },
        "decision": None,
        "actions": [],
        "decision_limits": [],
        "diagnostics": [],
        "checks": {
            "registered": 0,
            "with_findings": 0,
            "found_nothing": 0,
            "errored": 0,
            "skipped_note": "",
        },
        "verification": {
            "document": {"status": "not_run", "detail": None},
            "semantic": {"status": "complete", "detail": None},
            "live_source": {"status": "not_run", "detail": None},
        },
        "limitations": [],
        "offer": {"text": "Next: stop.", "accepted": None},
        "claims": [],
    }


DESIGN = ROOT / "tests" / "design"
SECTION_ORDER = [
    "Errors: fix these first",
    "Confirmed correct",
    "Today’s value differs",
    "What we could not check, and why",
    "What ran",
]
EM_EN_DASH = re.compile(r"[\u2013\u2014]")
E2E = ROOT / "tests" / "fixtures" / "verify" / "e2e"
_COUNT_WORDS = {
    "no": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9,
}


def prose_claim_total(page: str) -> int:
    match = re.search(r"The report makes ([^.]+?) claims?\.", page)
    test_msg = "page does not state a claim total"
    if not match:
        raise AssertionError(test_msg)
    raw = match.group(1).strip().lower().replace(",", "")
    if raw in _COUNT_WORDS:
        return _COUNT_WORDS[raw]
    return int(raw)


def tile_counts(page: str) -> dict[str, int | None]:
    found = re.findall(r'data-bucket="([^"]+)" data-count="([^"]+)"', page)
    out = {}
    for slug, count in found:
        out[slug] = None if count == "not-run" else int(count)
    return out


def _headings(page: str) -> list[str]:
    raw = re.findall(r"<h2>(.*?)</h2>", page, flags=re.S)
    out = []
    for item in raw:
        text = re.sub(r"<[^>]+>", "", item)
        text = (text.replace("&rsquo;", "’").replace("&#8217;", "’")
                .replace("&ldquo;", "“").replace("&rdquo;", "”"))
        out.append(re.sub(r"\s+", " ", text).strip())
    return out


def assert_page_structure(test, page: str, *, expect_errors: bool, expect_csr: bool) -> None:
    test.assertNotIn('class="sample"', page)
    test.assertNotIn("Design sample", page)
    test.assertIn("Summation", page)
    test.assertIn("/ Verify", page)
    expected_next = 1 if expect_errors else 0
    test.assertEqual(
        page.count('class="next"') + page.count("class='next'"), expected_next)
    if expected_next:
        test.assertIn("<b>Next:</b>", page)
    else:
        test.assertNotIn("<b>Next:</b>", page)
    test.assertIsNone(EM_EN_DASH.search(page), "em or en dash in generated page")
    test.assertNotIn("changed since", page.lower())
    test.assertNotIn("differs from source", page.lower())
    test.assertNotIn("NEEDS REVIEW", page)
    test.assertIn("Technical detail", page)
    test.assertIn("Checked automatically by Summation Verify", page)
    headings = _headings(page)
    allowed = list(SECTION_ORDER)
    if not expect_errors:
        allowed.remove("Errors: fix these first")
    if not expect_csr:
        allowed.remove("Today’s value differs")
    test.assertEqual(headings, allowed)
    buckets = re.findall(r'data-bucket="([^"]+)" data-count="([^"]+)"', page)
    test.assertEqual([item[0] for item in buckets], [
        "errors", "confirmed", "today-differs", "not-checkable"])
    numeric = 0
    for _slug, count in buckets:
        if count != "not-run":
            numeric += int(count)
    data_ledger = int(re.search(r'data-ledger="(\d+)"', page).group(1))
    test.assertEqual(numeric, data_ledger)
    test.assertEqual(prose_claim_total(page), data_ledger)
    if "listed under technical detail" in page:
        test.assertIn("<details>", page)
        test.assertIn("<li>", page)
    for match in re.finditer(r'<div class="card [^"]+" data-kind="[^"]+">', page):
        chunk = page[match.start(): match.start() + 1600]
        test.assertIn('class="tag"', chunk)
        test.assertIn("<h3>", chunk)
        test.assertIn("Checked by a program:", chunk)


def _check(verdict: str, **extra) -> dict:
    row = {
        "id": f"id-{verdict}",
        "type": "semantic",
        "basis": "evidence",
        "verdict": verdict,
        "importance": "material",
        "severity": "high" if verdict == "contradicted" else None,
        "report_quote": f"Visible quote for {verdict}.",
        "report_quote_2": None,
        "evidence_file": "live.json",
        "evidence_quote": f"evidence for {verdict}",
        "evidence_json": [],
        "evidence_receipts": [],
        "evidence_receipt_mode": "verbatim",
        "explanation": f"Explanation for {verdict}.",
        "reconstruction_attempt": None,
        "current_value": None,
        "current_as_of": None,
    }
    row.update(extra)
    return row


class HtmlParityTests(unittest.TestCase):
    def test_every_schema_claim_verdict_appears_in_html(self) -> None:
        verdicts = schema_claim_verdicts()
        self.assertTrue(verdicts)
        rows = []
        for verdict in verdicts:
            extra = {}
            if verdict == "changed_since_report":
                extra = {
                    "reconstruction_attempt": "No history table remains.",
                    "current_value": 10613,
                    "current_as_of": "2026-08-23",
                }
            rows.append(_check(verdict, **extra))
        page = render.html_of(_minimal_art(rows))
        for row in rows:
            with self.subTest(verdict=row["verdict"]):
                self.assertIn(
                    row["report_quote"], page,
                    f"{row['verdict']} quote missing from HTML",
                )
                self.assertIn(
                    html.escape(render.public_explanation(row)), page,
                    f"{row['verdict']} mechanical explanation missing from HTML",
                )
                self.assertNotIn(
                    row["explanation"], page,
                    f"{row['verdict']} host explanation leaked into HTML",
                )

    def test_unhandled_verdict_still_renders_a_card(self) -> None:
        row = _check("unmodeled_verdict")
        page = render.html_of(_minimal_art([row]))
        self.assertIn(row["report_quote"], page)
        self.assertIn(html.escape(render.public_explanation(row)), page)
        self.assertNotIn(row["explanation"], page)
        self.assertIn("unmodeled_verdict", page)

    def test_html_has_exactly_one_next_block(self) -> None:
        art = _minimal_art([_check("contradicted")])
        art["verdict"] = "fix_first"
        page = render.html_of(art)
        self.assertEqual(page.count('class="next"') + page.count("class='next'"), 1)
        safe = render.html_of(_minimal_art([_check("confirmed")]))
        self.assertEqual(safe.count('class="next"') + safe.count("class='next'"), 0)

    def test_needs_review_is_shown_as_share_with_caveats(self) -> None:
        art = _minimal_art([_check("confirmed")])
        art["verdict"] = "needs_review"
        page = render.html_of(art)
        self.assertIn("SHARE WITH CAVEATS", page)
        self.assertNotIn("NEEDS REVIEW", page)
        self.assertNotIn("needs_review", page)

    def test_design_samples_are_the_frozen_reference(self) -> None:
        files = {
            "grade-artifact-exemplar.html": "FIX FIRST",
            "grade-artifact-exemplar-safe.html": "SAFE TO SHARE",
            "grade-artifact-exemplar-caveats.html": "SHARE WITH CAVEATS",
        }
        for name, chip in files.items():
            page = (DESIGN / name).read_text()
            self.assertIn(chip, page)
            self.assertIn("Design sample", page)
            self.assertIn("Confirmed correct", page)
            self.assertIn("What we could not check, and why", page)
            self.assertIn("What ran", page)
            self.assertIn("Technical detail", page)
            self.assertEqual(page.count('class="next"'), 1)

    def test_named_missing_inputs_exit_2(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            findings = folder / "findings.json"
            findings.write_text(json.dumps({
                "findings": [],
                "coverage": {
                    "claims_in_ledger": 0,
                    "claims_reached_by_a_check": 0,
                    "extractor_checkable_fraction": 1.0,
                    "engine_checkable_fraction": 1.0,
                    "checks_registered": 0,
                    "checks_with_findings": 0,
                    "checks_found_nothing": 0,
                    "checks_errored": 0,
                },
                "source": {"path": "report.md", "format": "md"},
                "findings_truncated": False,
            }))
            out = folder / "artifact"
            self.assertEqual(run_mod(render, "render.py", [
                "--findings", str(folder / "no-findings.json"),
                "--out-dir", str(out),
            ]), 2)
            self.assertEqual(run_mod(render, "render.py", [
                "--findings", str(findings),
                "--layer2", str(folder / "no-layer2.json"),
                "--out-dir", str(out),
            ]), 2)
            self.assertEqual(run_mod(render, "render.py", [
                "--findings", str(findings),
                "--claims", str(folder / "no-claims.json"),
                "--out-dir", str(out),
            ]), 2)


@unittest.skipUnless(HAS_JSONSCHEMA, "jsonschema is not installed")
class RenderArtifactTests(unittest.TestCase):
    def test_tiny_fixture_is_fix_first(self) -> None:
        raw = json.loads(FIX.read_text())
        art = render.artifact_from_findings(
            raw, run_id="sf-001", generated_at="2026-08-17T00:00:00Z")
        self.assertEqual(art["source"]["path"], "2026-04-04-weekly-sales-snapshot.html")
        page = render.html_of(art)
        self.assertNotIn("/Users/", page)
        self.assertNotIn("Layer 1", page)
        self.assertNotIn("Layer 2", page)

    def test_receipted_contradiction_is_fix_first(self) -> None:
        raw = {
            "findings": [],
            "coverage": {
                "claims_in_ledger": 11,
                "claims_reached_by_a_check": 11,
                "extractor_checkable_fraction": 1.0,
                "engine_checkable_fraction": 1.0,
                "checks_registered": 1,
                "checks_with_findings": 0,
                "checks_found_nothing": 1,
                "checks_errored": 0,
            },
            "source": {"path": "clean.html", "format": "html", "sha256": "abc"},
            "findings_truncated": False,
        }
        layer2 = [{
            "id": "C1",
            "type": "semantic",
            "basis": "evidence",
            "verdict": "contradicted",
            "importance": "material",
            "severity": "high",
            "report_quote": "The kickoff is Thursday.",
            "evidence_file": "evidence.json",
            "evidence_quote": "kickoff Wednesday",
            "explanation": "The report names the wrong day.",
        }]
        art = render.artifact_from_findings(
            raw, run_id="t", generated_at="2026-08-20T00:00:00Z", layer2=layer2)
        self.assertEqual(art["verdict"], "fix_first")
        page = render.html_of(art, raw)
        self.assertIn("FIX FIRST", page)
        self.assertIn("The kickoff is Thursday.", page)

    def test_cli_writes_html_and_json(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            out = pathlib.Path(raw)
            code = run_mod(render, "render.py", [
                "--findings", str(FIX),
                "--out-dir", str(out),
                "--run-id", "test-run",
            ])
            self.assertEqual(code, 0)
            html = (out / "grade-artifact.html").read_text()
            art = json.loads((out / "grade-artifact.json").read_text())
            self.assertEqual(art["verdict"], "fix_first")
            self.assertIn("Summation", html)
            self.assertIn("FIX FIRST", html)
            self.assertNotIn('class="sample"', html)

    def test_changed_since_report_writes_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            report = folder / "report.md"
            report.write_text("Inventory on hand is 4,200.")
            (folder / "live.json").write_text(
                '{"on_hand": 5100, "as_of": "2026-08-23"}\n')
            checks = {
                "checks": [{
                    "id": "C11",
                    "type": "staleness",
                    "basis": "evidence",
                    "verdict": "changed_since_report",
                    "importance": "material",
                    "report_quote": "Inventory on hand is 4,200.",
                    "evidence_file": "live.json",
                    "evidence_json": [{"pointer": "/on_hand", "value": 5100}],
                    "explanation": "Current on-hand is 5100 as of 2026-08-23.",
                    "reconstruction_attempt": (
                        "Queried inventory_history and the daily snapshot table; "
                        "neither retains 2026-04-04 on-hand."
                    ),
                    "current_value": 5100,
                    "current_as_of": "2026-08-23",
                }]
            }
            (folder / "checks.json").write_text(json.dumps(checks))
            write_incomplete_md_findings(folder, {
                "agentic_only": True,
                "agentic_scan_completed": True,
                "extraction_method": "host-agent visible text",
                "coverage": {
                    "claims_in_ledger": 0,
                    "claims_reached_by_a_check": 0,
                    "extractor_checkable_fraction": 0.0,
                    "engine_checkable_fraction": 0.0,
                    "checks_registered": 0,
                    "checks_with_findings": 0,
                    "checks_found_nothing": 0,
                    "checks_errored": 0,
                },
            })
            self.assertEqual(run_mod(accept, "accept.py", [
                "--report", str(report),
                "--checks", str(folder / "checks.json"),
                "--evidence-dir", str(folder),
                "--out", str(folder / "receipts.json"),
            ]), 0)
            out = folder / "artifact"
            code = run_mod(render, "render.py", [
                "--findings", str(folder / "findings.json"),
                "--layer2", str(folder / "receipts.json"),
                "--out-dir", str(out),
                "--run-id", "csr-run",
            ])
            self.assertEqual(code, 0)
            self.assertTrue((out / "grade-artifact.html").is_file())
            art = json.loads((out / "grade-artifact.json").read_text())
            verdicts = {row["verdict"] for row in art["evidence_checks"]}
            self.assertIn("changed_since_report", verdicts)
            receipts = json.loads((folder / "receipts.json").read_text())
            self.assertTrue(receipts["checks"][0]["reconstruction_attempt"])
            self.assertEqual(receipts["checks"][0]["current_value"], 5100)
            self.assertNotIn("reconstruction_attempt", art["evidence_checks"][0])
            self.assertNotIn("current_value", art["evidence_checks"][0])
            assert_page_structure(
                self, (out / "grade-artifact.html").read_text(),
                expect_errors=False, expect_csr=True)

    def test_ledger_count_matches_proposed_checks(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            report = folder / "report.md"
            report.write_text("Alpha is 1. Beta is 2. Gamma is 3. Delta is 4. Epsilon is 5.")
            (folder / "ev.json").write_text(json.dumps({
                "alpha": 1, "beta": 2, "gamma": 3, "delta": 4, "epsilon": 5,
            }))
            rows = []
            for i, (name, quote) in enumerate([
                ("Alpha", "Alpha is 1."),
                ("Beta", "Beta is 2."),
                ("Gamma", "Gamma is 3."),
                ("Delta", "Delta is 4."),
                ("Epsilon", "Epsilon is 5."),
            ], start=1):
                rows.append({
                    "id": f"C{i}",
                    "type": "semantic",
                    "basis": "evidence",
                    "verdict": "confirmed",
                    "importance": "material",
                    "report_quote": quote,
                    "evidence_file": "ev.json",
                    "evidence_json": [{"pointer": f"/{name.lower()}", "value": i}],
                    "explanation": f"{name} matches.",
                })
            (folder / "checks.json").write_text(json.dumps({"checks": rows}))
            write_incomplete_md_findings(folder, {
                "agentic_only": True,
                "agentic_scan_completed": True,
            })
            self.assertEqual(run_mod(accept, "accept.py", [
                "--report", str(report),
                "--checks", str(folder / "checks.json"),
                "--evidence-dir", str(folder),
                "--out", str(folder / "receipts.json"),
            ]), 0)
            receipts = json.loads((folder / "receipts.json").read_text())
            self.assertEqual(receipts["proposed"], 5)
            out = folder / "artifact"
            self.assertEqual(run_mod(render, "render.py", [
                "--findings", str(folder / "findings.json"),
                "--layer2", str(folder / "receipts.json"),
                "--out-dir", str(out),
                "--run-id", "ledger-run",
            ]), 0)
            art = json.loads((out / "grade-artifact.json").read_text())
            self.assertEqual(art["evidence_coverage"]["document_claims_total"], 5)
            self.assertEqual(art["evidence_coverage"]["claim_outcomes_proposed"], 5)

    def test_planted_html_with_changed_since_report_is_fix_first(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            report = folder / "report.html"
            report.write_text(PLANTED.read_text())
            (folder / "live.json").write_text(
                '{"units_now": 10613, "as_of": "2026-08-23"}\n')
            (folder / "note.json").write_text(
                '{"note": "Both segments moved in the same direction."}\n')
            self.assertEqual(run_mod(html_arith, "html_arith.py", [
                "--report", str(report),
                "--out", str(folder / "findings.json"),
            ]), 0)
            findings = json.loads((folder / "findings.json").read_text())
            footing = [
                f for f in findings["findings"] if f["check_id"] == "ari_total_footing"]
            self.assertTrue(footing)
            self.assertAlmostEqual(abs(footing[0]["detail"]["discrepancy"]), 9000.0)
            (folder / "claims.json").write_text(json.dumps({
                "claims": [
                    {"id": "L19", "quote": "Both segments moved in the same direction.",
                     "importance": "material"},
                    {"id": "L20", "quote": "10,481", "importance": "material"},
                ],
            }))
            (folder / "checks.json").write_text(json.dumps({"checks": [
                {
                    "id": "C19",
                    "claim_id": "L19",
                    "type": "semantic",
                    "basis": "evidence",
                    "verdict": "confirmed",
                    "importance": "material",
                    "report_quote": "Both segments moved in the same direction.",
                    "evidence_file": "note.json",
                    "evidence_quote": "Both segments moved in the same direction.",
                    "explanation": "The evidence repeats the segment direction claim.",
                },
                {
                    "id": "C20",
                    "claim_id": "L20",
                    "type": "staleness",
                    "basis": "evidence",
                    "verdict": "changed_since_report",
                    "importance": "material",
                    "report_quote": "10,481",
                    "evidence_file": "live.json",
                    "evidence_json": [{"pointer": "/units_now", "value": 10613}],
                    "explanation": "Current units are 10613 as of 2026-08-23.",
                    "reconstruction_attempt": (
                        "The source was re-queried with the week ending April 4 "
                        "as the filter; the units source has no date column, so "
                        "the April 4 value could not be rebuilt."
                    ),
                    "current_value": 10613,
                    "current_as_of": "2026-08-23",
                },
            ]}))
            pad_inventory(folder)
            self.assertEqual(run_mod(accept, "accept.py", [
                "--report", str(report),
                "--claims", str(folder / "claims.json"),
                "--checks", str(folder / "checks.json"),
                "--findings", str(folder / "findings.json"),
                "--evidence-dir", str(folder),
                "--out", str(folder / "receipts.json"),
            ]), 0)
            receipts = json.loads((folder / "receipts.json").read_text())
            self.assertGreaterEqual(receipts["grounded"], 2)
            out = folder / "artifact"
            self.assertEqual(run_mod(render, "render.py", [
                "--findings", str(folder / "findings.json"),
                "--layer2", str(folder / "receipts.json"),
                "--out-dir", str(out),
                "--run-id", "planted-csr",
            ]), 0)
            art = json.loads((out / "grade-artifact.json").read_text())
            self.assertEqual(art["verdict"], "fix_first")
            self.assertIn(
                "changed_since_report",
                {row["verdict"] for row in art["evidence_checks"]},
            )
            page = (out / "grade-artifact.html").read_text()
            self.assertIn("9,000", page)
            self.assertIn("SEGMENT_ALPHA", page)
            self.assertIn("218,385.67", page)
            self.assertIn("SEGMENT_BETA", page)
            self.assertIn("Confirmed correct", page)
            self.assertIn("Both segments moved in the same direction.", page)
            self.assertIn("Today&rsquo;s value differs", page)
            self.assertNotIn("changed since", page.lower())
            self.assertNotIn("differs from source", page.lower())
            self.assertNotIn("10613", page)
            self.assertIn("10,481", page)
            self.assertEqual(page.count('class="next"') + page.count("class='next'"), 1)
            self.assertGreaterEqual(art["evidence_coverage"]["document_claims_total"], 1)
            assert_page_structure(self, page, expect_errors=True, expect_csr=True)

    def test_fifty_claim_ledger_shows_one_of_fifty(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            quotes = [f"Claim number {index} holds." for index in range(1, 51)]
            (folder / "report.md").write_text(" ".join(quotes))
            claims = [
                {"id": f"L{index}", "quote": quote, "importance": "material"}
                for index, quote in enumerate(quotes, 1)
            ]
            (folder / "claims.json").write_text(json.dumps({"claims": claims}))
            (folder / "ev.json").write_text('{"ok": true, "n": 1}\n')
            (folder / "checks.json").write_text(json.dumps({"checks": [{
                "id": "C1",
                "claim_id": "L1",
                "type": "semantic",
                "basis": "evidence",
                "verdict": "confirmed",
                "importance": "material",
                "report_quote": quotes[0],
                "evidence_file": "ev.json",
                "evidence_quote": '"ok": true',
                "explanation": "The first claim matches.",
            }]}))
            write_incomplete_md_findings(folder)
            self.assertEqual(run_mod(accept, "accept.py", [
                "--report", str(folder / "report.md"),
                "--claims", str(folder / "claims.json"),
                "--checks", str(folder / "checks.json"),
                "--evidence-dir", str(folder),
                "--out", str(folder / "receipts.json"),
            ]), 0)
            receipts = json.loads((folder / "receipts.json").read_text())
            self.assertEqual(receipts["claims_in_ledger"], 50)
            self.assertEqual(receipts["claims_reached_by_a_check"], 1)
            out = folder / "artifact"
            self.assertEqual(run_mod(render, "render.py", [
                "--findings", str(folder / "findings.json"),
                "--layer2", str(folder / "receipts.json"),
                "--out-dir", str(out),
                "--run-id", "fifty",
            ]), 0)
            art = json.loads((out / "grade-artifact.json").read_text())
            self.assertEqual(art["evidence_coverage"]["document_claims_total"], 50)
            self.assertEqual(art["evidence_coverage"]["document_claims_reached"], 1)
            page = (out / "grade-artifact.html").read_text()
            self.assertIn('data-ledger="50"', page)
            self.assertIn('data-bucket="confirmed" data-count="1"', page)

    def test_clean_report_all_material_confirmed_is_safe_to_share(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            report = folder / "report.html"
            report.write_text(
                (ROOT / "tests" / "fixtures" / "verify"
                 / "weekly-sales-snapshot-clean.html").read_text())
            self.assertEqual(run_mod(html_arith, "html_arith.py", [
                "--report", str(report),
                "--out", str(folder / "findings.json"),
            ]), 0)
            quote = "Both segments moved in the same direction."
            (folder / "note.json").write_text(json.dumps({"note": quote}))
            findings_doc = json.loads((folder / "findings.json").read_text())
            claims = [{"id": "L0", "quote": quote, "importance": "supporting"}]
            checks = [{
                "id": "C0",
                "claim_id": "L0",
                "type": "semantic",
                "basis": "evidence",
                "verdict": "confirmed",
                "importance": "supporting",
                "report_quote": quote,
                "evidence_file": "note.json",
                "evidence_quote": quote,
                "explanation": "The note matches the report.",
            }]
            ev = {"note": quote}
            for index, item in enumerate(findings_doc.get("inventory", {}).get("items") or [], 1):
                shown = item["displayed"]
                cid = f"L{index}"
                key = f"v{index}"
                claims.append({
                    "id": cid,
                    "quote": shown,
                    "importance": "material",
                    "inventory_ids": [item["id"]],
                })
                ev[key] = shown
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
            (folder / "ev.json").write_text(json.dumps(ev) + "\n")
            (folder / "claims.json").write_text(json.dumps({"claims": claims}))
            (folder / "checks.json").write_text(json.dumps({"checks": checks}))
            self.assertEqual(run_mod(accept, "accept.py", [
                "--report", str(report),
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
                "--run-id", "clean-complete",
            ]), 0)
            art = json.loads((out / "grade-artifact.json").read_text())
            self.assertEqual(art["verdict"], "safe_to_share")
            self.assertEqual(art["verification"]["semantic"]["status"], "complete")
            assert_page_structure(
                self, (out / "grade-artifact.html").read_text(),
                expect_errors=False, expect_csr=False)

    def test_half_material_unreached_is_partial(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            (folder / "report.md").write_text("Alpha is 1. Beta is 2.")
            (folder / "ev.json").write_text('{"alpha": 1}\n')
            (folder / "claims.json").write_text(json.dumps({"claims": [
                {"id": "L1", "quote": "Alpha is 1.", "importance": "material"},
                {"id": "L2", "quote": "Beta is 2.", "importance": "material"},
            ]}))
            (folder / "checks.json").write_text(json.dumps({"checks": [{
                "id": "C1",
                "claim_id": "L1",
                "type": "semantic",
                "basis": "evidence",
                "verdict": "confirmed",
                "importance": "material",
                "report_quote": "Alpha is 1.",
                "evidence_file": "ev.json",
                "evidence_json": [{"pointer": "/alpha", "value": 1}],
                "explanation": "Alpha matches.",
            }]}))
            write_incomplete_md_findings(folder)
            self.assertEqual(run_mod(accept, "accept.py", [
                "--report", str(folder / "report.md"),
                "--claims", str(folder / "claims.json"),
                "--checks", str(folder / "checks.json"),
                "--evidence-dir", str(folder),
                "--out", str(folder / "receipts.json"),
            ]), 0)
            receipts = json.loads((folder / "receipts.json").read_text())
            self.assertEqual(receipts["semantic_status"], "partial")
            out = folder / "artifact"
            self.assertEqual(run_mod(render, "render.py", [
                "--findings", str(folder / "findings.json"),
                "--layer2", str(folder / "receipts.json"),
                "--out-dir", str(out),
                "--run-id", "partial",
            ]), 0)
            art = json.loads((out / "grade-artifact.json").read_text())
            self.assertEqual(art["verification"]["semantic"]["status"], "partial")
            self.assertEqual(art["evidence_coverage"]["document_claims_total"], 2)
            self.assertEqual(art["evidence_coverage"]["document_claims_reached"], 1)

    def test_not_checkable_is_reached_not_confirmed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            (folder / "report.md").write_text("Alpha is 1.")
            (folder / "claims.json").write_text(json.dumps({
                "claims": [{"id": "L1", "quote": "Alpha is 1.", "importance": "material"}],
            }))
            (folder / "checks.json").write_text(json.dumps({"checks": [{
                "id": "C1",
                "claim_id": "L1",
                "type": "semantic",
                "basis": "report",
                "verdict": "not_checkable",
                "importance": "material",
                "report_quote": "Alpha is 1.",
                "explanation": "No warehouse snapshot remains for this figure.",
            }]}))
            write_incomplete_md_findings(folder)
            self.assertEqual(run_mod(accept, "accept.py", [
                "--report", str(folder / "report.md"),
                "--claims", str(folder / "claims.json"),
                "--checks", str(folder / "checks.json"),
                "--out", str(folder / "receipts.json"),
            ]), 0)
            receipts = json.loads((folder / "receipts.json").read_text())
            self.assertEqual(receipts["claims_reached_by_a_check"], 1)
            self.assertEqual(receipts["claims"][0]["outcome"], "not_checkable")
            out = folder / "artifact"
            self.assertEqual(run_mod(render, "render.py", [
                "--findings", str(folder / "findings.json"),
                "--layer2", str(folder / "receipts.json"),
                "--out-dir", str(out),
                "--run-id", "uncheckable",
            ]), 0)
            art = json.loads((out / "grade-artifact.json").read_text())
            self.assertEqual(art["evidence_coverage"]["document_claims_reached"], 1)
            self.assertEqual(art["evidence_coverage"]["confirmed"], 0)
            self.assertEqual(art["evidence_coverage"]["not_checkable"], 1)

    def test_repro_ledger_tiles_match_receipts_not_bucket_sum(self) -> None:
        """The 3-claim sloppy e2e input must not invent a fifth claim."""
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            report = folder / "weekly-sales-snapshot.html"
            report.write_text(PLANTED.read_text())
            evidence = folder / "evidence"
            evidence.mkdir()
            for name in ("q3.json", "live-units.json"):
                (evidence / name).write_text((E2E / "evidence" / name).read_text())
            claims = folder / "claims.json"
            checks = folder / "checks.json"
            findings = folder / "findings.json"
            claims.write_text((E2E / "claims-r5.json").read_text())
            checks.write_text((E2E / "checks-r5.json").read_text())
            findings.write_text((E2E / "findings.json").read_text())
            pad_inventory(folder, report)
            self.assertEqual(run_mod(accept, "accept.py", [
                "--report", str(report),
                "--claims", str(claims),
                "--checks", str(checks),
                "--findings", str(findings),
                "--evidence-dir", str(evidence),
                "--out", str(folder / "receipts.json"),
            ]), 0)
            receipts = json.loads((folder / "receipts.json").read_text())
            ledger_n = int(receipts["claims_in_ledger"])
            self.assertGreaterEqual(ledger_n, 4)
            outcomes = {row["id"]: row.get("outcome") for row in receipts["claims"]}
            self.assertEqual(outcomes["L1"], "changed_since_report")
            self.assertEqual(outcomes["L2"], "not_checkable")
            self.assertIn(outcomes["L3"], {"not_reached", "not_checkable"})
            synthetic = [row for row in receipts["claims"] if row.get("found_by") == "arithmetic"]
            self.assertEqual(len(synthetic), 1)
            self.assertEqual(synthetic[0]["outcome"], "error")
            out = folder / "artifact"
            self.assertEqual(run_mod(render, "render.py", [
                "--findings", str(findings),
                "--layer2", str(folder / "receipts.json"),
                "--out-dir", str(out),
            ]), 0)
            page = (out / "grade-artifact.html").read_text()
            self.assertEqual(prose_claim_total(page), ledger_n)
            tiles = tile_counts(page)
            numeric = sum(v or 0 for v in tiles.values())
            self.assertEqual(numeric, ledger_n)
            self.assertEqual(tiles["errors"], 1)
            self.assertEqual(tiles["confirmed"], 0)
            self.assertEqual(tiles["today-differs"], 1)
            self.assertGreaterEqual(tiles["not-checkable"], 2)
            self.assertIn("week ending April 4, 2026", page)
            self.assertIn("April 4, 2026", page)
            self.assertNotIn("The claim matches your evidence", page)
            footer = re.search(r"Run ([^<]+)", page).group(1)
            self.assertRegex(footer, r"sf-[0-9a-f]{6}")
            art = json.loads((out / "grade-artifact.json").read_text())
            self.assertRegex(art["run_id"], r"^sf-[0-9a-f]{6}$")

    def test_unreconciled_findings_exit_2(self) -> None:
        """accept without --findings, then render with findings, must not write a page."""
        with tempfile.TemporaryDirectory() as raw:
            folder = pathlib.Path(raw)
            report = folder / "weekly-sales-snapshot.html"
            report.write_text(PLANTED.read_text())
            evidence = folder / "evidence"
            evidence.mkdir()
            for name in ("q3.json", "live-units.json"):
                (evidence / name).write_text((E2E / "evidence" / name).read_text())
            (folder / "claims.json").write_text((E2E / "claims-r5.json").read_text())
            (folder / "checks.json").write_text((E2E / "checks-r5.json").read_text())
            self.assertEqual(run_mod(accept, "accept.py", [
                "--report", str(report),
                "--claims", str(folder / "claims.json"),
                "--checks", str(folder / "checks.json"),
                "--evidence-dir", str(evidence),
                "--out", str(folder / "receipts.json"),
            ]), 0)
            receipts = json.loads((folder / "receipts.json").read_text())
            self.assertFalse(any(
                row.get("found_by") == "arithmetic" for row in receipts["claims"]))
            (folder / "findings.json").write_text((E2E / "findings.json").read_text())
            out = folder / "artifact"
            code = run_mod(render, "render.py", [
                "--findings", str(folder / "findings.json"),
                "--layer2", str(folder / "receipts.json"),
                "--out-dir", str(out),
            ])
            self.assertEqual(code, 2)
            self.assertFalse((out / "grade-artifact.html").is_file())

    def test_artifact_verdict_is_a_public_value(self) -> None:
        raw = {
            "findings": [],
            "coverage": {
                "claims_in_ledger": 2,
                "claims_reached_by_a_check": 0,
                "extractor_checkable_fraction": 1.0,
                "engine_checkable_fraction": 1.0,
                "checks_registered": 0,
                "checks_with_findings": 0,
                "checks_found_nothing": 0,
                "checks_errored": 0,
            },
            "source": {"path": "report.md", "format": "md"},
            "findings_truncated": False,
        }
        self.assertEqual(render.verdict_of(raw), "needs_review")
        art = render.artifact_from_findings(
            raw, run_id="v", generated_at="2026-08-24T00:00:00Z")
        self.assertIn(art["verdict"], {
            "safe_to_share", "share_with_caveats", "fix_first", "unable_to_grade"})
        self.assertNotEqual(art["verdict"], "needs_review")
        schema = json.loads(
            (ROOT / "skills" / "verify" / "schema.v1.json").read_text())
        self.assertEqual(
            set(schema["properties"]["verdict"]["enum"]),
            {"safe_to_share", "share_with_caveats", "fix_first", "unable_to_grade"},
        )


class FillerAndAddendTests(unittest.TestCase):
    def test_render_source_has_no_filler_strings(self) -> None:
        src = (SCRIPTS / "render.py").read_text()
        self.assertNotIn("The claim matches your evidence", src)
        self.assertNotIn("In the report", src)

    def test_unlabeled_check_uses_quote_as_title(self) -> None:
        art = _minimal_art([_check("confirmed")])
        art["claims"] = [{
            "id": "L1",
            "quote": "Visible quote for confirmed.",
            "importance": "material",
            "outcome": "confirmed",
            "check_id": "id-confirmed",
        }]
        art["evidence_checks"][0]["claim_id"] = "L1"
        page = render.html_of(art)
        self.assertIn("Visible quote for confirmed.", page)
        self.assertNotIn("The claim matches your evidence", page)
        self.assertNotIn(">In the report<", page)
        self.assertNotIn('class="where"', page)


if __name__ == "__main__":
    unittest.main()
