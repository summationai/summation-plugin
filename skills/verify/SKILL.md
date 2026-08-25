---
name: verify
description: Grade a report file the user already has (HTML, PDF, xlsx, pptx, Markdown). Use when they drop in a report, ask if it is safe to share, want errors in a recap, or run /summation:verify. No Summation login required.
---

# Summation Verify

Grade a file on disk. You conduct. Local scripts compute. Do not call `claude -p`. Do not clone `alg-deploy`. Do not ask them to sign in to Summation first.

If they name a report that already lives in Summation (no disk file), run the `validate` skill instead.

## First two minutes

1. Before any grading: `command -v uv` succeeds, or `python3 -c "import jsonschema"` succeeds. If neither, resolve that with the user now. Do not start a long run that dies at render.
2. Ask which file. If they already attached one, use it.
3. Read the report. Write `claims.json` now, before you gather evidence. After `html_arith.py` runs, read `inventory` in `findings.json`. Cover every material inventory item plus every other load-bearing claim: `{"report_period": "week ending April 4, 2026", "report_date": "2026-04-04", "claims": [{"id": "L1", "quote": "exact visible text", "importance": "material"}]}`. `importance` is `material` or `supporting`. Quotes are visible text. `report_period` is the display string. `report_date` is ISO `YYYY-MM-DD`. Leave either field out when the report does not name a period.
4. If a nearby `evidence/` folder exists, ask once whether to use it. Do not scan their whole disk.
5. If GitHub, Snowflake, Slack, or similar tools are already connected in this session, ask once whether to query them. Save raw tool results as files under the run `evidence/` folder. Do not ask them to sign in to Summation to get evidence.
6. State duration, then work:
   - File plus local evidence only: about 2–5 minutes.
   - Also using connections already in this session: about 10–15 minutes.
7. Then stay quiet except for brief progress. Do not narrate layers, error codes, tenant IDs, or check names.

## Run directory

Create a run folder next to the report (or in `/tmp/summation-verify-<id>/`):

```text
run/
  report/          original file
  report-visible.txt   required when the file is not HTML, Markdown, or plain text
  evidence/        unchanged tool results and user files
  claims.json      you write this first: every load-bearing claim
  checks.json      you write this after evidence
  findings.json    html_arith.py writes this
  receipts.json    accept.py writes this
  artifact/        render.py writes grade-artifact.html + .json
```

For PDF, xlsx, pptx, or images: extract visible text yourself into `report-visible.txt`. Do not install OfficeCLI or Poppler.

## Scripts

`VERIFY="${PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/skills/verify"`

If those variables are empty, resolve `VERIFY` from this skill’s directory.

```bash
python3 "$VERIFY/scripts/html_arith.py" \
  --report "$RUN/report/<file>" --out "$RUN/findings.json"
```

If the report is HTML, Markdown, or plain text:

```bash
python3 "$VERIFY/scripts/accept.py" \
  --report "$RUN/report/<file>" \
  --claims "$RUN/claims.json" \
  --checks "$RUN/checks.json" \
  --findings "$RUN/findings.json" \
  --evidence-dir "$RUN/evidence" \
  --out "$RUN/receipts.json"
```

If the report is PDF, xlsx, pptx, or an image, write `report-visible.txt` first. Then:

```bash
python3 "$VERIFY/scripts/accept.py" \
  --report "$RUN/report/<file>" \
  --report-text "$RUN/report-visible.txt" \
  --claims "$RUN/claims.json" \
  --checks "$RUN/checks.json" \
  --findings "$RUN/findings.json" \
  --evidence-dir "$RUN/evidence" \
  --out "$RUN/receipts.json"
```

Then:

```bash
uv run --with jsonschema python3 "$VERIFY/scripts/render.py" \
  --findings "$RUN/findings.json" \
  --layer2 "$RUN/receipts.json" \
  --out-dir "$RUN/artifact"
```

If `uv` is missing and `jsonschema` already imports, run `python3` on `render.py`. Do not `pip install` without asking.

`html_arith.py` is best-effort table footing on HTML and writes the machine claim inventory. Other formats still get a `findings.json` stub with an incomplete inventory reader. Always run it. If `render.py` exits 2 because claims miss an inventory item, add the missing quote and run `accept.py` then `render.py` again.

## You write checks.json

After evidence, write one outcome per claim you actually checked. Each row names `claim_id`:

```json
{"checks": [{
  "id": "C1",
  "claim_id": "L1",
  "type": "semantic",
  "basis": "evidence",
  "verdict": "confirmed",
  "importance": "material",
  "severity": null,
  "report_quote": "exact visible text from the report",
  "metric_label": "Units",
  "location": "Headline tile, Units",
  "evidence_file": "relative/name.json",
  "evidence_quote": "exact text from that evidence file",
  "evidence_json": [{"pointer": "/path", "value": "exact value"}],
  "report_quote_2": null,
  "explanation": "One complete sentence."
}],
  "presentation": {
    "summary": "One paragraph the reader can use.",
    "check_ids": ["C1"],
    "actions": [{
      "id": "A1",
      "text": "What to do next.",
      "report_quote": "exact visible text",
      "check_ids": ["C1"]
    }],
    "limits": []
  }
}
```

`presentation` is optional. Put it on the checks file next to the `checks` array. Every summary, action, and limit names the accepted check ids that support it. `accept.py` keeps a statement when every `report_quote` is visible text and every named id is a grounded check.

- `verdict`: `confirmed` | `contradicted` | `not_checkable`. `changed_since_report` is a last resort (see live source below). Never omit verdict.
- `type`: `semantic` | `staleness` | `internal` | `logic` | `arithmetic` | `units` | `selection`.
- `basis`: `evidence` or `report`. Report-only contradictions need `report_quote` and `report_quote_2`.
- Quotes are visible text, after whitespace normalize. Never quote HTML tags.
- `metric_label` names the figure (for example `Units`). `location` names the spot on the page (for example `Headline tile, Orders`). Leave either field out when you do not have it.
- Prefer `evidence_json` pointers for JSON files.
- `not_checkable` needs a specific reason. Do not attach a fake receipt.
- Subagents per section are optional. Hosts without subagents do the same writes in sequence.

### Live source (closed period first)

`changed_since_report` is never the first answer.

1. If the claim names a closed period, re-query with that period filter. Verdict is `confirmed` or `contradicted` for that period. If today's warehouse shows a different value for that same closed period, that is a restatement or a report error: `contradicted`, with both values and both dates in the explanation.
2. If the claim is point-in-time ("inventory on hand is 4,200"), reconstruct the as-of value (time travel, snapshot, history table, or a date column). If reconstruction works, verdict is `confirmed` or `contradicted` as of the report date.
3. Only when reconstruction is impossible: `changed_since_report`. The row must include `reconstruction_attempt` (what you tried and why it failed), `current_value`, `current_as_of`, and an evidence receipt for the current value.

Then run `accept.py`. If it discards rows, fix only those quotes once and run `accept.py` again. Stop after two passes. Discarded rows stay discarded. Do not invent a quote so a row will pass.

## After render.py

If you could not obtain the report text, say that in the conversation and stop. Do not run `render.py`. Do not write an artifact.

Open `artifact/grade-artifact.html`. Read `verdict` from `grade-artifact.json`. Say that in plain language. Do not add findings the file does not contain. Do not hand-write HTML. If the page names a next step, repeat that step. Do not offer a schedule, upload, or sign-in.

## Laws

- A finding ships only when `accept.py` kept it. Code is the scorecard.
- `not_checkable` means the check ran and lacked evidence. `not_run` means you never reached it. Never present the second as the first.
- No letter grade. No “Layer 1” / “Layer 2”. No internal bug ids.
- Accept the file they have. If you cannot obtain the report text, say so in the conversation and stop. Do not render a page. Do not refuse PDF, xlsx, or pptx because of the format.
- Zero Summation login for the local grade.
