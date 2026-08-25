---
name: verify
description: Grade a report file the user already has (HTML, PDF, xlsx, pptx, Markdown), or a report that already lives in Summation. Use when they drop in a file, name a Summation report, ask if it is safe to share, want errors in a recap, or run /summation:verify.
---

# Summation Verify

Grade a file on disk. You conduct. Local scripts compute. Do not call `claude -p`. Do not clone `alg-deploy`. Do not ask them to sign in to Summation first.

If they named a report that already lives in Summation and there is no disk file, go to **Connected path**.

## First two minutes

1. Before any grading: `command -v uv` succeeds, or `python3 -c "import jsonschema"` succeeds. If neither, resolve that with the user now. Do not start a long run that dies at render.
2. Ask which file. If they already attached one, use it.
3. Run `extract.py` first. Read `inventory` in `findings.json` and `report-visible.txt`. Then write `claims.json`. Cover every material inventory item plus every other load-bearing claim. Each claim names the inventory ids it covers. One claim may list two ids only when the quote names both locations. Set `classification` to `material_claim` or `supporting_provenance`. A missing classification is `material_claim`. Quotes are visible text. `report_period` is the display string. `report_date` is ISO `YYYY-MM-DD`. Leave either field out when the report does not name a period. Do not write claims from PowerPoint speaker notes. Example: `{"report_period": "week ending April 4, 2026", "report_date": "2026-04-04", "claims": [{"id": "L1", "quote": "exact visible text", "importance": "material", "classification": "material_claim", "inventory_ids": ["INV1"]}]}`.
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
  report-visible.txt   extract.py writes this
  evidence/        unchanged tool results and user files
  claims.json      you write this after inventory: every load-bearing claim
  checks.json      you write this after evidence
  findings.json    extract.py writes this
  receipts.json    accept.py writes this
  artifact/        render.py writes grade-artifact.html + .json
```

Do not install OfficeCLI or Poppler. Do not copy speaker notes into claims.

## Scripts

`VERIFY="${PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/skills/verify"`

If those variables are empty, resolve `VERIFY` from this skill’s directory.

```bash
uv run "$VERIFY/scripts/extract.py" \
  --report "$RUN/report/<file>" \
  --visible "$RUN/report-visible.txt" \
  --out "$RUN/findings.json"
```

If `uv` is missing, run `python3` on `extract.py` only when `pypdf`, `openpyxl`, and `python-pptx` already import. Do not `pip install` without asking. Do not call OfficeCLI or Poppler.

Then write `claims.json` and `checks.json`. Every material inventory id must have one accepted completed outcome. Confirm every claim that you can prove from the report itself: arithmetic, rank order, percentages, displayed values, and internal consistency. Use `basis: report` and `verdict: confirmed` for those claims. External evidence is not required for them. `not_checkable` is only for a fact that needs an external source and has no grounded evidence. Convert every unresolved material claim to an honest `not_checkable` result before `render.py`. Do not leave `not_reached` rows. A remaining material `not_checkable` claim prevents `safe_to_share`.

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

If the report is PDF, xlsx, or pptx:

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

`extract.py` writes visible text, the machine inventory, and deterministic internal outcomes (rank order, arithmetic/ratio, percent versus points, direction, period display). `accept.py` merges those outcomes into the ledger. A deterministic confirmed or contradicted result is authoritative only for the same inventory ids. Quote overlap does not move that result onto a different id. The host cannot downgrade or reverse it. `accept.py` rejects a conflicting host outcome with reason `deterministic-conflict`. `accept.py` also rejects `supporting_provenance` on an id that already has a confirmed or contradicted internal result. The reason is `deterministic-conflict`. The item stays material. The host only grades semantic or external claims that code cannot prove. A claim without inventory ids stays host-owned.

If `render.py` exits 2 because a material inventory item is missing or a claim is `not_reached`, repair that claim and run `accept.py` then `render.py` again.

Read every `Source snapshot:` inventory line in full. If the line names only source identity or an extraction date, write `classification: supporting_provenance` with the exact inventory id, the exact quote, `importance: supporting`, and a reason. If the line states a status, quality, completeness, KPI, count, comparison, or other analytical result, write `classification: material_claim` and grade it as a material claim. Code does not classify these lines from word lists. A missing classification stays material. If extract already confirmed or contradicted that inventory id, write `material_claim`. `accept.py` rejects `supporting_provenance` on a proven id with reason `deterministic-conflict`. `supporting_provenance` accounts for that inventory id. It does not count as a confirmed analytical result. For a clean PDF, classify `Source snapshot: CRM revenue export, 2026-07-05.` as supporting provenance when it names only that export and date.

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

### Data-currency dates

A report claim that names a data-currency or as-of date must be compared with a supplied evidence date field. Accept generic field names such as `latest_complete_date`, `as_of`, and `date`. Parse ISO days and month-name days. If the report date and the grounded evidence date differ, write `verdict: contradicted` with `type: staleness`, a JSON pointer receipt, and `basis: evidence`. Do not write `not_checkable` for that claim. `accept.py` applies this rule when the host omits it.

### Live source (closed period first)

`changed_since_report` is never the first answer.

1. If the claim names a closed period, re-query with that period filter. Verdict is `confirmed` or `contradicted` for that period. If today's warehouse shows a different value for that same closed period, that is a restatement or a report error: `contradicted`, with both values and both dates in the explanation.
2. If the claim is point-in-time ("inventory on hand is 4,200"), reconstruct the as-of value (time travel, snapshot, history table, or a date column). If reconstruction works, verdict is `confirmed` or `contradicted` as of the report date.
3. Only when reconstruction is impossible: `changed_since_report`. The row must include `reconstruction_attempt` (what you tried and why it failed), `current_value`, `current_as_of`, and an evidence receipt for the current value.

Then run `accept.py`. If it discards rows, fix only those quotes once and run `accept.py` again. Stop after two passes. Discarded rows stay discarded. Do not invent a quote so a row will pass.

## After render.py

If you could not obtain the report text, say that in the conversation and stop. Do not run `render.py`. Do not write an artifact.

Open `artifact/grade-artifact.html`. Read `verdict` from `grade-artifact.json`. Say that in plain language. Do not add findings the file does not contain. Do not hand-write HTML. If the page names a next step, repeat that step. If they want this in Summation, go to **Connected path**. Do not start that path during the local grade.

## Laws

- A finding ships only when `accept.py` kept it. Code is the scorecard.
- `not_checkable` means the check ran and lacked evidence. `not_run` means you never reached it. Never present the second as the first.
- No letter grade. No “Layer 1” / “Layer 2”. No internal bug ids.
- Accept the file they have. If you cannot obtain the report text, say so in the conversation and stop. Do not render a page. Do not refuse PDF, xlsx, or pptx because of the format.
- Zero Summation login for the local grade.

## Connected path

Use this after the local grade, or when they named a report that already lives in Summation and there is no disk file. This continues in the project chat with Addison. It is not the local `grade-artifact.html`.

Do this path once. Do not invoke the `validate` alias.

1. Itemized consent first. Name each file you would upload, or the Summation report they named. Wait for an explicit yes on those items. Stop if they decline.
2. Authentication begins only after that consent. If they are not signed in, run the `signin` skill now.
3. If they consented to local files, upload only those files with the existing file-upload MCP tools: `request_file_upload`, `upload_file`, `finalize_file_upload`.
4. Continue in the project chat with Addison. Addison authors playbooks and verifies project reports through its existing skills.
5. If they ask for a cadence, use the existing Workflow tools (the `schedule` skill).

Never soften flags Addison returns. If that verification failed, the report is not safe to share.
