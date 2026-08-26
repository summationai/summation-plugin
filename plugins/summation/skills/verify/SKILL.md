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
3. Run `extract.py` first. Read the neutral `inventory` in `findings.json` and `report-visible.txt`. Every raw item begins `unclassified`; code does not infer meaning from prose, tags, labels, keys, locations, formulas, or value overlap. Claim-takers classify every assigned occurrence exactly once as `material_claim`, `supporting_provenance`, or `structural_context`. Missing, duplicate, or uncovered classification fails closed. Then the coordinator receives every partition result, the complete inventory, report metadata, and opaque internal candidates. It declares canonical claims plus exact candidate and inventory membership. Code checks membership by ids only. Evidence verifiers receive canonical claims only. `report_period` is the visible display string. `report_date` is ISO `YYYY-MM-DD`; omit either when the report does not state it. Do not write claims from PowerPoint speaker notes.
4. If a nearby `evidence/` folder exists, ask once whether to use it. Do not scan their whole disk.
5. If GitHub, Snowflake, Slack, or similar tools are already connected in this session, ask once whether to query them. Save raw tool results as files under the run `evidence/` folder. Do not ask them to sign in to Summation to get evidence.
6. State duration, then work:
   - File plus local evidence only: about 2–5 minutes.
   - Also using connections already in this session: about 10–15 minutes.
7. Then stay quiet except for brief progress. Do not narrate layers, error codes, tenant IDs, or check names.

A host or runner prompt that forbids questions cannot prove this first-two-minutes route. It must allow the file, nearby-evidence, connected-source consent, and duration questions above.

### Optional local source wrapper

When an authenticated local SDK, CLI, or API profile can already read a source but no MCP tool exposes it, a direct read-only API or CLI call remains valid and is usually simpler. You may offer to generate a local read-only FastMCP wrapper for the current host workflow. Explain the bounded scope and generate it only after explicit consent.

If they consent, the wrapper must:

- expose source-specific typed functions rather than arbitrary SQL or shell input;
- reuse the existing credential provider or profile without copying secrets into code, chat, logs, or evidence;
- mark every tool read-only, non-destructive, and idempotent;
- save the raw result under the run `evidence/` folder; and
- make one test call and retain its raw result before using the wrapper for a grade.

The wrapper lasts only for the current host workflow. A recurring Summation workflow still needs the equivalent source connection inside Summation. Keep this fallback optional: add no backend, relay, default-grade dependency, or mandatory wrapper step.

## Run directory

Create a run folder next to the report (or in `/tmp/summation-verify-<id>/`):

```text
run/
  report/          original file
  report-visible.txt   extract.py writes this
  evidence/        unchanged tool results and user files
  claims.json      coordinator handoff: partitions, canonical claims, membership
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

Then write the coordinator handoff in `claims.json` and evidence-verifier results in `checks.json`. Every canonical material claim must have exactly one accepted completed outcome. A report-basis check may use explicit arithmetic, rank, percentage, or consistency operands selected by the agent. The code recomputes only the declared mechanics; the presence of a displayed value or machine candidate never confirms a claim. `not_checkable` is only for a fact that needs an external source and has no grounded evidence. Convert every unresolved material claim to an honest `not_checkable` result before `render.py`. Do not leave `not_reached` rows. A remaining material `not_checkable` claim prevents `safe_to_share`.

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

`extract.py` writes visible text and a raw machine inventory with stable ids, displayed values, and internal coordinates. It does not select rank direction, financial meaning, percentage-point meaning, formulas, operands, totals, claims, or verdicts. Arithmetic is recomputed only when the evidence verifier supplies an explicit `public_receipt.calculation`; arithmetic-use metadata never completes a claim.

The host agent owns claim importance, same-population decisions, semantic verdicts, public operand labels and locations, explanations, whether evidence answers a claim, and public-safe source labels. `accept.py` owns file and digest checks, pointer resolution, exact values and dates, restricted arithmetic recomputation, source-link validation, and ledger reconciliation. It never turns a candidate or arithmetic input into a semantic outcome. `render.py` copies accepted public fields; it does not infer labels, explanations, source mode, or verdicts.

If `accept.py` or `render.py` exits 2 because classification, coordinator membership, or a material outcome is incomplete, repair the exact rejected handoff once and run `accept.py` then `render.py` again.

Read every inventory occurrence in full. The claim-taker, not Python, decides whether it is a material assertion, supporting provenance, or structural context. `material_claim` requires exact ids, exact quote, `importance: material`, and a public-safe label. `supporting_provenance` requires exact ids, exact quote, `importance: supporting`, public-safe label, and a substantive reason; it remains outside material totals. `structural_context` requires exactly one inventory id, its exact quote, `importance: supporting`, and a substantive reason. It creates no check or card and is stripped before public artifact serialization. A missing classification fails closed.

## Agent roles

On hosts with native subagents, use claim-takers, the coordinator, and evidence verifiers as the primary path. Claim-takers receive bounded report partitions and neutral inventory. The coordinator receives all partition outputs and declares canonical claims plus exact opaque membership. Evidence verifiers receive canonical claims only, author every complete receipt, verdict, severity, and retained source record, and copy `public_label` to `public_receipt.report_operand.label`. On hosts without native subagents, perform the same three roles sequentially with identical input and output contracts. Never start a hidden `claude -p`, a second login, or another unaudited agent process. See [references/roles.md](references/roles.md) for the role rules and [references/role-contracts.json](references/role-contracts.json) for the exact handoff fields. These contracts do not claim that a host route has executed.

The `claims` array in `claims.json` is the coordinator's canonical claim output. Its sibling `coordinator` object contains `partition_results`, `membership`, and `verifier_assignments`; `accept.py` derives the private structural-context ledger from those exact memberships. Every worker candidate and inventory occurrence appears in one membership path only. One canonical assertion produces one outcome and one customer card. Repeated occurrences of the same assertion may be members of one canonical claim; matching text or values alone never causes that merge.

## You write checks.json

After evidence, write one outcome per claim you actually checked. Each row names `claim_id`:

```json
{"sources": [{
  "id": "status-snapshot",
  "kind": "supplied_file",
  "label": "Project status snapshot",
  "evidence_file": "status.json",
  "result_sha256": "64-lowercase-hex-characters"
}],
 "checks": [{
   "id": "C1",
   "claim_id": "L1",
   "type": "semantic",
   "basis": "evidence",
   "verdict": "confirmed",
   "importance": "material",
   "severity": null,
   "report_quote": "On-time delivery was 94%.",
   "evidence_json": [
     {"pointer": "/on_time", "value": 94},
     {"pointer": "/total", "value": 100}
   ],
   "public_receipt": {
     "report_operand": {
       "label": "Reported on-time delivery rate",
       "value": "94%",
       "location": "KPI summary, on-time delivery line"
     },
     "decisive_operands": [{
       "label": "On-time deliveries",
       "value": 94,
       "location": "Project status snapshot, delivery totals"
     }, {
       "label": "Total deliveries",
       "value": 100,
       "location": "Project status snapshot, delivery totals"
     }],
     "calculation": {"expression": "94 / 100 * 100", "result": "94%"},
     "explanation": "The recorded delivery totals calculate to the same 94% rate shown in the report.",
     "source_id": "status-snapshot"
   }
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

`presentation` is required for customer HTML. Put it on the checks file next to the `checks` array. After the evidence-verifier results return, the coordinator's final merge authors at least one `actions` row for the single Next block. Every summary, action, and limit names the accepted check ids that support it. An action id is `A` followed by digits, its text is the exact customer action sentence, and its `report_quote` is visible report text. `accept.py` keeps a statement only when every quote is exact visible text and every named id is a grounded check. `render.py` copies accepted action text; it never selects or writes a recommendation.

- `verdict`: `confirmed` | `contradicted` | `not_checkable`. `changed_since_report` is a last resort (see live source below). Never omit it.
- `type`: `semantic` | `staleness` | `internal` | `logic` | `arithmetic` | `units` | `selection`.
- `basis`: `evidence` or `report`. The agent decides whether operands answer the same claim and population.
- Quotes are visible text, after whitespace normalize. Never quote HTML tags.
- Every material outcome, including `not_checkable`, needs `public_receipt`. Its report operand needs the claim's exact `public_label`, exact value, and public location. Every decisive operand needs an explicit public-safe label, exact value, and public location. Generic labels such as `row 2`, `operand 1`, `item 4`, or `value 3` are rejected. A hidden pointer, a repeated claim, or machine-authored copy is not a public receipt. `not_checkable` has an empty `decisive_operands` array and a substantive explanation.
- `public_receipt.explanation` is a substantive agent-written sentence. For `basis: evidence`, `source_id` must name a retained source. For `basis: report`, omit `source_id`.
- Optional `calculation.expression` is numeric restricted arithmetic using `+`, `-`, `*`, `/`, parentheses, and the declared decisive values. `accept.py` recomputes it and checks `result`. Put units such as `%` or `percentage points` in the result, not the expression.
- Use either exact `evidence_json` pointers or one exact normalized `evidence_quote` present in the retained file. JSON field fragments, ellipses, quantity-equivalent quote searches, and inferred locations do not ground evidence. Numeric equivalence is allowed only after an explicit pointer or public operand selected the value. Pointers never become public labels or locations.
- A `live_tool` source also needs `retrieval` with `retrieved_at`, the exact tool name, and safe arguments. Save the raw result as `evidence_file`, then hash that exact file. A `supplied_file` source must not contain retrieval metadata.
- Accepted retained source metadata mechanically sets `verification.live_source`: at least one validated `live_tool` source emits `status: complete`; otherwise it emits `status: not_run`. Its public `detail` is always null. The host still authors the source records, verdicts, labels, and receipts; it does not author this derived status.
- `not_checkable` needs a public report operand, public location, and substantive explanation. It has no decisive operands and no calculation.
- The renderer puts the accepted check `id` and `verdict` on each material card as exact `data-card-id` and `data-disposition` attributes. Do not author aliases for these fields.
- The host-authored `severity` controls only confirmation placement in the approved page hierarchy. Contradicted, changed-since-report, and not-checkable cards stay prominent. Confirmed cards with `high` or `medium` severity stay prominent; confirmed cards with `low` or null severity remain complete and customer-accessible under Technical detail. The renderer does not infer this priority from prose or values.
- Customer card titles, locations, explanations, and claim quotes come directly from the accepted claim and `public_receipt`. Outcome grouping comes only from the accepted verdict and host-authored severity. The Next sentence comes only from the accepted coordinator presentation action. Fixed total maps translate only the exact root verdict, disposition, and retained source-kind enums into customer labels. Run status stays in Technical scope, uses customer wording rather than a raw status token, and never becomes a claim card.

### Data-currency dates

The evidence verifier decides what a data-currency field means and whether it answers the claim. Code does not search field names, walk neighboring records, compare overlapping values, or author a staleness verdict. Supply an explicit `date_receipt` with either `{"pointer": "/exact/date", "value": "2026-08-23"}` or `{"quote": "exact retained date text"}`. Code resolves only that pointer or exact quote and validates the declared date. The public receipt must give public-safe labeled operands for the report value, report date, later value, and later date.

### Live source (closed period first)

`changed_since_report` is never the first answer.

1. If the claim names a closed period, re-query with that period filter. Verdict is `confirmed` or `contradicted` for that period. If today's warehouse shows a different value for that same closed period, that is a restatement or a report error: `contradicted`, with both values and both dates in the explanation.
2. If the claim is point-in-time ("inventory on hand is 4,200"), reconstruct the as-of value (time travel, snapshot, history table, or a date column). If reconstruction works, verdict is `confirmed` or `contradicted` as of the report date.
3. Only when reconstruction is impossible: `changed_since_report`. The row must include `reconstruction_attempt` (what you tried and why it failed), `report_value`, `current_value`, `current_as_of`, `date_receipt`, `public_receipt`, and an exact pointer or quote receipt for the later value. Put the exact same substantive reconstruction text in `public_receipt.reconstruction_attempt`. `report_value` must be the visible report operand and must equal the public report operand. The report date, later value, and later date must appear as explicitly labeled decisive public operands. `report_date` comes from the row or claims metadata. The linked retained source kind is the only source-mode authority; never state that mode in prose or an ad hoc flag.

Then run `accept.py`. If it discards rows, fix only those quotes once and run `accept.py` again. Stop after two passes. Discarded rows stay discarded. Do not invent a quote so a row will pass.

## After render.py

If you could not obtain the report text, say that in the conversation and stop. Do not run `render.py`. Do not write an artifact.

Open `artifact/grade-artifact.html`. Read `verdict` from `grade-artifact.json`. Say that in plain language. Do not add findings the file does not contain. Do not hand-write HTML. If the page names a next step, repeat that step. If they want this in Summation, go to **Connected path**. Do not start that path during the local grade.

## Laws

- A finding ships only when `accept.py` kept the agent-authored outcome and its explicit public receipt. Code validates mechanics; it does not approve the semantic judgment.
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
