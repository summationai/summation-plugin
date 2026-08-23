---
name: verify
description: Grade a report file the user already has (HTML, PDF, xlsx, pptx, Markdown). Use when they drop in a report, ask if it is safe to share, want errors in a recap, or run /summation:verify. No Summation login required.
---

# Summation Verify

Grade a file on disk. You conduct. Local scripts compute. Do not call `claude -p`. Do not clone `alg-deploy`. Do not ask them to sign in to Summation first.

If they name a report that already lives in Summation (no disk file), run the `validate` skill instead.

## First two minutes

1. Ask which file. If they already attached one, use it.
2. If a nearby `evidence/` folder exists, ask once whether to use it. Do not scan their whole disk.
3. If GitHub, Snowflake, Slack, or similar tools are already connected in this session, ask once whether to query them. Save raw tool results as files under the run `evidence/` folder. Do not ask them to sign in to Summation to get evidence.
4. State duration, then work:
   - File plus local evidence only: about 2–5 minutes.
   - Also using connections already in this session: about 10–15 minutes.
5. Then stay quiet except for brief progress. Do not narrate layers, error codes, tenant IDs, or check names.

## Run directory

Create a run folder next to the report (or in `/tmp/summation-verify-<id>/`):

```text
run/
  report/          original file
  report-visible.txt   required when the file is not HTML, Markdown, or plain text
  evidence/        unchanged tool results and user files
  checks.json      you write this
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

python3 "$VERIFY/scripts/accept.py" \
  --report "$RUN/report/<file>" \
  --report-text "$RUN/report-visible.txt" \
  --checks "$RUN/checks.json" \
  --evidence-dir "$RUN/evidence" \
  --out "$RUN/receipts.json"

uv run --with jsonschema python3 "$VERIFY/scripts/render.py" \
  --findings "$RUN/findings.json" \
  --layer2 "$RUN/receipts.json" \
  --out-dir "$RUN/artifact"
```

If `uv` is missing, run `python3` on `render.py` when `jsonschema` is already installed. Do not `pip install` without asking.

`html_arith.py` is best-effort table footing on HTML. Other formats still get a `findings.json` stub. Always run it.

## You write checks.json

After you read the report (and evidence, if they said yes), write:

```json
{"checks": [{
  "id": "C1",
  "type": "semantic",
  "basis": "evidence",
  "verdict": "confirmed",
  "importance": "material",
  "severity": null,
  "report_quote": "exact visible text from the report",
  "evidence_file": "relative/name.json",
  "evidence_quote": "exact text from that evidence file",
  "evidence_json": [{"pointer": "/path", "value": "exact value"}],
  "report_quote_2": null,
  "explanation": "One complete sentence."
}]}
```

- `verdict`: `confirmed` | `contradicted` | `not_checkable` only. Use `changed_since_report` only when live data moved after the report date.
- `type`: `semantic` | `staleness` | `internal` | `logic` | `arithmetic` | `units` | `selection`.
- `basis`: `evidence` or `report`. Report-only contradictions need `report_quote` and `report_quote_2`.
- Quotes are visible text, after whitespace normalize. Never quote HTML tags.
- Prefer `evidence_json` pointers for JSON files.
- `not_checkable` needs a specific reason. Do not attach a fake receipt.
- Subagents per section are optional. Hosts without subagents do the same writes in sequence.

Then run `accept.py`. If it discards rows, fix only those quotes once and run `accept.py` again. Stop after two passes. Discarded rows stay discarded. Do not invent a quote so a row will pass.

## After render.py

Open `artifact/grade-artifact.html`. Read `verdict` and `offer` from `grade-artifact.json`. Say those in plain language. Do not add findings the file does not contain. Do not hand-write HTML.

Then one offer, if they have not already declined:

> I can put this in Summation so it re-checks on a schedule. Want that?

If they decline, stop. If they accept, hand off to `start` (sign in, then data). This skill is over.

## Laws

- A finding ships only when `accept.py` kept it. Code is the scorecard.
- `not_checkable` means the check ran and lacked evidence. `not_run` means you never reached it. Never present the second as the first.
- No letter grade. No “Layer 1” / “Layer 2”. No internal bug ids.
- Accept the file they have. If you cannot read it, the artifact says so. Do not refuse PDF, xlsx, or pptx.
- Zero Summation login for the local grade.
