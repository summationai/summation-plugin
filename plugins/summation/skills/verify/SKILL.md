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
3. Run `extract.py` first. Read the neutral `inventory` in `findings.json` and `report-visible.txt`. Every raw item begins `unclassified`; code does not infer meaning from prose, tags, labels, keys, locations, formulas, or value overlap. Claim-takers classify every assigned occurrence exactly once as `material_claim`, `supporting_provenance`, or `structural_context`. For a material occurrence, they enumerate each independently verifiable clause with an opaque id, exact visible quote, and public label. Missing, duplicate, or uncovered occurrence or clause membership fails closed. Then the coordinator receives every partition result, the complete inventory, report metadata, and opaque internal candidates. It maps every clause ref to one canonical claim. Multiple clauses may share one canonical claim only when one evidence-verifier receipt addresses every member clause. Code checks ids and declared coverage only; it never finds clauses in prose. Evidence verifiers receive canonical claims only. `report_period` is the visible display string. `report_date` is ISO `YYYY-MM-DD`; omit either when the report does not state it. Do not write claims from PowerPoint speaker notes.
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

Then write the coordinator handoff in `claims.json` and evidence-verifier results in `checks.json`. Every canonical material claim must have exactly one accepted completed outcome. A report-basis check may use explicit arithmetic, rank, percentage, or consistency operands selected by the agent. The code recomputes only the declared mechanics; the presence of a displayed value or machine candidate never confirms a claim. Use `not_checkable` when no grounded evidence answers the claim or when an exact source conflict cannot establish the same report population. Convert every unresolved material claim to an honest `not_checkable` result before `render.py`. Do not leave `not_reached` rows. A remaining material `not_checkable` claim prevents `safe_to_share`.

Before acceptance, run the same `accept.py` command shown below with `--preflight-only` and change `--out` to `$RUN/preflight.json`. For PDF, xlsx, and pptx, keep `--report-text`. Preflight uses the final acceptance path and returns the complete exact repair reasons for coordinator membership, substantive supporting or structural reasons, public numeric calculation results, declared numeric comparison mechanics, source deduplication, source links, source consideration, privacy, and grounding. The run has one total repair pass. Give the responsible role only its original input, its prior output, and the exact mechanical reasons. Do not prescribe replacement classifications, verdicts, severities, ids, labels, operands, calculations, precision or tolerance choices, counts, score, a source-side winner, or action text. Rerun that failed validation once, and stop if any reason remains.

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

For a separate invariant audit of those exact files, include the accepted private mechanics without exposing them in the public artifact:

```bash
uv run --with jsonschema python3 "$VERIFY/scripts/artifact_audit.py" \
  "$RUN/artifact/grade-artifact.json" \
  "$RUN/artifact/grade-artifact.html" \
  "$RUN/receipts.json"
```

If `uv` is missing and `jsonschema` already imports, run `python3` on `render.py`. Do not `pip install` without asking.

`extract.py` writes visible text and a raw machine inventory with stable ids, displayed values, and internal coordinates. It does not select rank direction, financial meaning, percentage-point meaning, formulas, operands, totals, claims, or verdicts. Arithmetic is recomputed only when the evidence verifier supplies an explicit `public_receipt.calculation`; arithmetic-use metadata never completes a claim.

The host agent owns claim importance, same-population decisions, semantic verdicts, public operand labels and locations, explanations, whether evidence answers a claim, public-safe source labels, numeric comparison mode and precision, source relevance, and source exclusion reasons. `accept.py` owns file and digest checks, pointer resolution, exact values and dates, restricted arithmetic recomputation, declared numeric comparison, source deduplication, source-link and consideration validation, and ledger reconciliation. It never turns a candidate or arithmetic input into a semantic outcome. `render.py` copies accepted public fields and serializes accepted mechanical display results; it does not infer labels, explanations, source mode, precision, or verdicts.

If the one repair pass has already been used and `accept.py` or `render.py` still rejects classification, coordinator membership, grounding, or a material outcome, stop. Do not synthesize another handoff or public receipt.

Read every inventory occurrence in full. The claim-taker, not Python, decides whether it is a material assertion, supporting provenance, or structural context. `material_claim` requires exact ids, exact quote, `importance: material`, and a public-safe label. `supporting_provenance` requires exact ids, exact quote, `importance: supporting`, public-safe label, and a substantive reason; it remains outside material totals. `structural_context` requires exactly one inventory id, its exact quote, `importance: supporting`, and a substantive reason. It creates no check or card and is stripped before public artifact serialization. A missing classification fails closed.

## Agent roles

On hosts with native subagents, use claim-takers, the coordinator, and evidence verifiers as the primary path. Claim-takers receive bounded report partitions and neutral inventory. The coordinator receives all partition outputs and declares canonical claims plus exact opaque membership. Evidence verifiers receive canonical claims only, author every complete receipt, verdict, severity, and retained source record, and copy `public_label` to `public_receipt.report_operand.label`. The coordinator deduplicates returned source records and authors complete `source_consideration`. Initial role prompts may contain only the report, neutral inventory, approved sources appropriate to that role, and the role contracts. They must not contain a semantic answer key, an expected precision or tolerance, a source-side winner, expected counts, or a prior grade artifact. On hosts without native subagents, perform the same three roles sequentially with identical input and output contracts. Never start a hidden `claude -p`, a second login, or another unaudited agent process. See [references/roles.md](references/roles.md) for the role rules and [references/role-contracts.json](references/role-contracts.json) for the exact handoff fields. These contracts do not claim that a host route has executed.

The `claims` array in `claims.json` is the coordinator's canonical claim output. Its sibling `coordinator` object contains `partition_results`, clause-level `membership`, and `verifier_assignments`; `accept.py` derives the private structural-context ledger from those exact memberships. Every worker candidate and inventory occurrence is classified once, and every material clause ref appears in one membership path only. Canonical `supporting_provenance` rows retain a substantive reason; each private structural-context row also retains its exact quote and substantive reason. One canonical assertion produces one outcome and one customer card. Repeated occurrences of the same assertion may be members of one canonical claim; matching text or values alone never causes that merge. A compound occurrence produces separate canonical claims unless one assigned receipt declares every member in `addressed_clause_refs` and substantively answers all of them.

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
 "source_consideration": [{
   "source_id": "status-snapshot",
   "claim_ids": ["L1"]
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
    "summary": "The accepted delivery receipt supports sharing this report value.",
    "check_ids": ["C1"],
    "actions": [{
      "id": "A1",
      "kind": "review_before_share",
      "text": "Review the accepted delivery receipt before sharing this report.",
      "report_quote": "On-time delivery was 94%.",
      "check_ids": ["C1"]
    }],
    "limits": []
  }
}
```

`presentation` is required for customer HTML. Put it on the checks file next to the `checks` array. The coordinator's final merge authors one concise customer verdict summary and grounds it with accepted `check_ids`. If confirmed outcomes exist, those ids must include at least one decision-relevant confirmation; confirmed ids in this list are the explicit visible-confirmation selection. The coordinator also authors at least one `actions` row for the single Next block. An action id is `A` followed by digits, its `kind` is `correct_report`, `reconcile_before_change`, or `review_before_share`, its text is the exact customer action sentence, and its `report_quote` is visible report text. Every summary, action, and limit names the accepted check ids that support it. `accept.py` validates the declared action kind against those checks. `render.py` copies the accepted summary and action text; it never selects or writes their meaning.

- `verdict`: `confirmed` | `contradicted` | `not_checkable`. `changed_since_report` is a last resort (see live source below). Never omit it.
- `type`: `semantic` | `staleness` | `internal` | `logic` | `arithmetic` | `units` | `selection`.
- `basis`: `evidence` or `report`. The agent decides whether operands answer the same claim and population.
- Quotes are visible text, after whitespace normalize. Never quote HTML tags.
- Every material outcome, including `not_checkable`, needs `public_receipt`. Its report operand needs the claim's exact `public_label`, exact value, and public location. Every decisive operand needs an explicit public-safe label, exact value, and public location. Generic labels such as `row 2`, `operand 1`, `item 4`, or `value 3` are rejected by the generic receipt contract. The host must also replace raw identifiers such as `SEGMENT_ALPHA` and generic locations such as `narrative note` with customer-safe wording such as `Segment Alpha` and a precise visible location. Python does not detect or rewrite those content patterns; the customer-page review enforces that host responsibility. A hidden pointer, a repeated claim, or machine-authored copy is not a public receipt. `not_checkable` has an empty `decisive_operands` array and a substantive explanation.
- `public_receipt.explanation` is a substantive agent-written sentence. For `basis: evidence`, `source_id` must name a retained source. For `basis: report`, omit `source_id`.
- Optional `calculation.expression` is numeric restricted arithmetic using `+`, `-`, `*`, `/`, parentheses, and the declared decisive values. `accept.py` recomputes it and checks `result`. The result must be a numeric public value such as `12`, `$350,490.34`, `94%`, or `2 percentage points`; semantic counts such as `1 project` are rejected. Put units such as `%` or `percentage points` in the result, not the expression.
- A confirmed or contradicted report-basis arithmetic check also needs private `numeric_comparison`. Choose `{"mode":"rounded","rounding":"half_up","decimal_places":1}` or the same with `half_even`, or choose `{"mode":"absolute_tolerance","tolerance":0}` with the tolerance the report actually warrants. The evidence verifier chooses; Python never derives the rule from prose, formatting, units, or value overlap. Code recomputes the selected operands and rejects a verdict that disagrees under the declaration. The metadata is absent from public JSON and customer text. A rounded comparison displays both the exact calculated result and the mechanical customer-rounded result.
- Copy the canonical claim's complete opaque member list into `addressed_clause_refs`. A missing, extra, or partial clause set fails coordinator preflight. This field is internal and is stripped from the public artifact.
- When a contradicted report-basis calculation corrects one canonical assertion repeated in more than one member occurrence, author `correction_notice` with `statement`, `report_value`, `replacement_value`, and one public-safe label per `locations` entry. The statement must name every location and both exact values, state that every occurrence must change, and appear verbatim inside `public_receipt.explanation`. The coordinator must also copy it verbatim into an action that cites that check. Python validates exact copies and values; it does not author the statement.
- Use either exact `evidence_json` pointers or one exact normalized `evidence_quote` present in the retained file. JSON field fragments, ellipses, quantity-equivalent quote searches, and inferred locations do not ground evidence. Numeric equivalence is allowed only after an explicit pointer or public operand selected the value. Pointers never become public labels or locations.
- For a confirmed or contradicted evidence-basis outcome on a report with a period or date, add agent-authored `population_alignment`. `same_population` requires a substantive reason plus one or more `links`; each link names `report_period`, `as_of_date`, `scope`, or `population_key`, an exact visible `report_quote`, and an exact retained-source pointer or quote in `source_receipt`. If the source conflict cannot supply that link, use `status: unreconciled`, list `missing_dimensions`, retain exact `conflict_receipts`, and author a substantive `reconciliation_action`. That row is `not_checkable`, and its cited `reconcile_before_change` action must tell the customer to reconcile the source and report before changing either. Python resolves receipts and enforces the declared status/verdict/action relationship; it does not decide whether populations match.
- Retain one source record per exact `kind`, `evidence_file`, and `result_sha256`. Duplicate identities fail preflight with all duplicate ids in one reason; the coordinator chooses the surviving id and public label and updates check references. Add one `source_consideration` row for every approved retained source. It contains `source_id` plus exactly one non-empty `claim_ids` list for accepted checks that cite it, or a substantive `exclusion_reason`. Code validates ids and complete citation coverage only. The host decides relevance. Exclusion reasons appear in Technical scope; cited sources remain card-local and are not duplicated there.
- A `live_tool` source also needs `retrieval` with `retrieved_at`, the exact tool name, and safe arguments. Save the raw result as `evidence_file`, then hash that exact file. A `supplied_file` source must not contain retrieval metadata.
- Accepted retained source metadata mechanically sets `verification.live_source`: at least one validated `live_tool` source emits `status: complete`; otherwise it emits `status: not_run`. Its public `detail` is always null. The host still authors the source records, verdicts, labels, and receipts; it does not author this derived status.
- `not_checkable` needs a public report operand, public location, and substantive explanation. It has no decisive operands and no calculation.
- The renderer puts the accepted check `id` and `verdict` on each material card as exact `data-card-id` and `data-disposition` attributes. Do not author aliases for these fields.
- Host-authored `severity` remains a customer-priority field but does not control placement. The coordinator's accepted presentation ids select visible confirmations. At least one confirmation must be visible when confirmed outcomes exist. Other confirmations and all complete not-checkable receipt cards remain accessible under Technical detail. The main not-checkable section is a compact list of each exact claim quote and its substantive host explanation.
- Customer card titles, locations, explanations, and claim quotes come directly from the accepted claim and `public_receipt`. Outcome grouping comes only from the accepted verdict. The verdict summary and Next sentence come only from the accepted coordinator presentation. For an explicit calculation, the renderer lays the accepted decisive operand labels and values above fixed `Calculated result`, optional mechanically accepted `Customer-rounded result`, and `Report shows` rows, then retains the exact expression as secondary receipt detail. Fixed total maps translate only the exact root verdict, disposition, and retained source-kind enums into customer labels. Run status stays in Technical scope, uses customer wording rather than a raw status token, and never becomes a claim card.

### Data-currency dates

The evidence verifier decides what a data-currency field means and whether it answers the claim. Code does not search field names, walk neighboring records, compare overlapping values, or author a staleness verdict. Supply an explicit `date_receipt` with either `{"pointer": "/exact/date", "value": "2026-08-23"}` or `{"quote": "exact retained date text"}`. Code resolves only that pointer or exact quote and validates the declared date. The public receipt must give public-safe labeled operands for the report value, report date, later value, and later date.

### Live source (closed period first)

`changed_since_report` is never the first answer.

1. If the claim names a closed period, re-query with that period filter. Verdict is `confirmed` or `contradicted` for that period. If today's warehouse shows a different value for that same closed period, that is a restatement or a report error: `contradicted`, with both values and both dates in the explanation.
2. If the claim is point-in-time ("inventory on hand is 4,200"), reconstruct the as-of value (time travel, snapshot, history table, or a date column). If reconstruction works, verdict is `confirmed` or `contradicted` as of the report date.
3. Only when reconstruction is impossible: `changed_since_report`. The row must include `reconstruction_attempt` (what you tried and why it failed), `report_value`, `current_value`, `current_as_of`, `date_receipt`, `public_receipt`, and an exact pointer or quote receipt for the later value. Put the exact same substantive reconstruction text in `public_receipt.reconstruction_attempt`. `report_value` must be the visible report operand and must equal the public report operand. The report date, later value, and later date must appear as explicitly labeled decisive public operands. `report_date` comes from the row or claims metadata. The linked retained source kind is the only source-mode authority; never state that mode in prose or an ad hoc flag.

Then run `accept.py`. If it discards rows and the run's single repair pass is still unused, repair only the exact stated problems and run `accept.py` once more. Otherwise stop. Discarded rows stay discarded. Do not invent a quote so a row will pass.

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
