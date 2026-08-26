---
name: verify
description: Grade a report file the user already has (HTML, PDF, xlsx, pptx, Markdown), or a report that already lives in Summation. Use when they drop in a file, name a Summation report, ask if it is safe to share, want errors in a recap, or run /summation:verify.
---

# Summation Verify

Grade a file on disk. You conduct. Local scripts compute. Do not call `claude -p`. Do not clone `alg-deploy`. Do not ask them to sign in to Summation first.

If they named a report that already lives in Summation and there is no disk file, go to **Connected path**.

## First two minutes

1. Before any grading: `command -v uv` succeeds, or `python3 -c "import jsonschema"` succeeds. If neither, resolve that with the user now. Do not search the disk. Do not start a long run that dies at render.
2. Ask which file. If they already attached one, use it.
3. Run `extract.py` now. Do not read `accept.py`, `render.py`, or `role-contracts.json` before `findings.json` and `report-visible.txt` exist. Every raw inventory item begins `unclassified`; code does not infer meaning from prose, tags, labels, keys, locations, formulas, identifiers, or value overlap. `report_period` is the visible display string. `report_date` is ISO `YYYY-MM-DD`; omit either when the report does not state it. Do not write claims from PowerPoint speaker notes.
4. If a nearby `evidence/` folder exists, ask once whether to use it. Do not scan their whole disk.
5. If GitHub, Snowflake, Slack, or similar tools are already connected in this session, ask once whether to query them. Save raw tool results as files under the run `evidence/` folder. Do not ask them to sign in to Summation to get evidence.
6. State duration, then work:
   - File plus local evidence only: about 2–5 minutes.
   - Also using connections already in this session: about 10–15 minutes.
7. Then stay quiet except for brief progress. Do not narrate layers, error codes, tenant IDs, or check names.

After extract exists, follow [references/roles.md](references/roles.md). Each role writes its JSON with `write_role_output.py` into `run/role-outputs/` and stops. Do not paste role bundles into chat. Do not read all of `accept.py` to start grading.

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
  role-inputs/     read-only bounded JSON bundles, one per role run
  role-outputs/    exact JSON output bundles, one per role run
  claims.json      coordinator semantic plan and canonical claims
  checks.json      assessments, resolutions, checks, sources, presentation
  findings.json    extract.py writes this
  semantic-plan-preflight.json   pre-verifier plan result
  preflight.json   exact complete bundle digest and repair reasons
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

Each role output is a file. Do not paste the bundle into chat. Write it with:

```bash
python3 "$VERIFY/scripts/write_role_output.py" \
  --dir "$RUN/role-outputs" \
  --name <role-or-partition> \
  --json bundle.json
```

The script prints the written path. That path is the role output. Chat is not a role output.

Then run the private workflow in [references/roles.md](references/roles.md) and materialize the exact stage bundles in [references/role-contracts.json](references/role-contracts.json). Every canonical material claim has one final resolution, one accepted outcome, and one customer card. Assessments are private evidence or report-consistency judgments; they are not extra claims or cards. A report-basis assessment may use explicit arithmetic, rank, percentage, or consistency operands selected by the host. Code recomputes only declared mechanics. A displayed value, machine candidate, or arithmetic-use marker never confirms a claim. Use `not_checkable` when no grounded assessment answers the claim, an aligned assessment conflict remains, a relevant source is unreconciled, or a dependency is unresolved. Do not leave `not_reached` rows. A material `not_checkable` claim prevents `safe_to_share`.

After the coordinator semantic plan and before verifier fan-out, write a temporary v6 `checks.json` containing the canonical `sources` and an empty `checks` array. Run the relevant format command below with `--semantic-plan-only`, omit `--preflight-record`, and write `--out "$RUN/semantic-plan-preflight.json"`. This calls `validate_acceptance_bundle(validation_stage="semantic_plan")` and must report zero reasons before evidence verification starts. It validates classification review, canonical membership, population-requirement receipts, the complete source-by-claim plan, dependencies, and verifier ownership.

Before final acceptance, run the relevant format command below without `--preflight-record`, add `--preflight-only`, and write `--out "$RUN/preflight.json"`. For PDF, xlsx, and pptx, keep `--report-text`. Full preflight and final acceptance call the same pure `validate_acceptance_bundle()` path. The reason set covers the complete private bundle: classification review and membership, source identity and every source/claim pair, population declarations, dependencies and operand origins, assessment calculations and host numeric policy, resolutions, actions and dependency closure, role-bundle provenance, privacy, and grounding. The run has one total repair pass. Give the responsible role only its original read-only input bundle, its prior output, and the exact mechanical reasons. Do not prescribe replacement classifications, verdicts, severities, ids, labels, operands, calculations, dependencies, precision or tolerance choices, counts, score, a source-side winner, summary, or action. Regenerate affected descendants and rerun the full preflight once. Stop if any reason remains. Then run final acceptance against the unchanged files with `--preflight-record "$RUN/preflight.json"` exactly as shown.

If the report is HTML, Markdown, or plain text:

```bash
python3 "$VERIFY/scripts/accept.py" \
  --report "$RUN/report/<file>" \
  --claims "$RUN/claims.json" \
  --checks "$RUN/checks.json" \
  --findings "$RUN/findings.json" \
  --evidence-dir "$RUN/evidence" \
  --preflight-record "$RUN/preflight.json" \
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
  --preflight-record "$RUN/preflight.json" \
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

Read every inventory occurrence in full. The claim-taker and coordinator, not Python, decide whether it is a material assertion, supporting provenance, or structural context, and each decision declares the matching `analytical_role`. Report titles, owner identifiers, and reporting-period labels or dates are structural context. Statements that the report was prepared from a named source are supporting provenance. Keep them outside material totals unless an exact clause span identifies a separate load-bearing analytical assertion whose truth changes a conclusion or customer action. `material_claim` requires exact ids, exact quote, `importance: material`, a public-safe label, and `analytical_role: load_bearing_analytical_assertion`. `supporting_provenance` requires exact ids, exact quote, `importance: supporting`, public-safe label, a substantive reason, and the matching analytical role; it remains outside material totals. `structural_context` requires exactly one inventory id, its exact quote, `importance: supporting`, a substantive reason, and the matching analytical role. It creates no check or card and is stripped before public artifact serialization. A missing or inconsistent declaration fails closed. Python validates the declaration without classifying from words, tags, values, or locations.

## Agent roles

On hosts with native subagents, use that primary path. Claim-takers, coordinator semantic planning, dependency-ordered evidence verification, and coordinator global resolution use separate materialized JSON bundles. Each role writes its entire output as one JSON file under `run/role-outputs/` (one file per role run). Then that role stops. Do not paste the bundle into chat. Chat is not a role output. The coordinator reads those files; it does not rebuild them from the transcript. On hosts without native subagents, execute the same stages sequentially with the same input schema and the same output schema. Record every bundle path and SHA-256 plus allowed and observed read paths. A role may read only its bounded input and declared evidence. A prior artifact, prior page, evaluator control, unrelated partition, or product checkout is not a role input. Never start a hidden `claude -p`, a second login, or another unaudited agent process. See [references/roles.md](references/roles.md) for ownership and [references/role-contracts.json](references/role-contracts.json) for exact fields. These contracts are not execution proof.

Initial role bundles contain only the fields allowed for that stage. They do not prescribe classifications, verdicts, severity, check ids, public labels, operands, calculations, dependencies, expected counts, score, numeric precision, a source-side winner, summary, or action. A repair adds only `repair_context` with `repair_pass_id: 1`, the prior role output, and exact mechanical repair reasons; the original stage input remains unchanged. Top-level `role_provenance.repair_passes_used` is exactly `0` or `1`. All repaired inputs share pass id 1, a role target has at most one repaired generation, and the repair ledger is included in the full bundle digest. There is one repair maximum for the run.

The `claims` array in `claims.json` is the coordinator's canonical claim output. Its sibling `coordinator` object contains `partition_results`, one `classification_reviews` row per inventory occurrence, a complete pre-verifier `source_consideration_plan`, `claim_dependencies`, and `verifier_assignments`. Each material claim names its primary clause, complete member clause ids and occurrence ids, context occurrence ids, public label, and host-declared population requirements. One clause belongs to one canonical claim. Repeated occurrences of one assertion may share one claim only by explicit ids. Each independent clause remains separate unless one receipt will address all member clauses. Structural context stays private. Supporting provenance stays outside material totals. Python validates exact ids and coverage and never infers these decisions.

## You write checks.json

The final `checks.json` uses the same private workflow version and contains `sources`, `assessments`, the complete final `source_consideration` matrix, `whole_source_exclusions`, `resolutions`, one `checks` row per material claim, `presentation`, and `role_provenance`. Evidence verifiers propose assessments, resolutions, and checks. The coordinator performs the global merge. Python validates exact mechanics and does not author missing semantics.

- Canonicalize approved sources before verifier fan-out by exact `kind`, safe `evidence_file`, and `result_sha256`. The coordinator chooses the one stable id and public-safe label. A `live_tool` source also has retrieval time, exact tool, and safe arguments. A `supplied_file` source has no retrieval metadata. Accepted source metadata alone sets `verification.live_source` to `complete` or `not_run`, always with null detail.
- The coordinator plan has one `source_consideration_plan` row for every approved source and material claim. The final matrix has that same pair plus exact coordinator decision/reason, verifier decision/reason, and assessment ids. A considered pair has an assessment. An excluded pair has substantive reasons. Coordinator/verifier disagreement fails closed. Per-claim reasons stay private. A separate `whole_source_exclusions` row is required only when a source is excluded for every material claim; only that reason may appear in Technical scope.
- Each assessment declares `id`, `claim_id`, `basis`, `effect`, `depends_on_assessment_ids`, and `operand_bindings`. Exact report occurrences, exact source receipts, and accepted upstream `calculation.result` values are the only operand origins. Report/source population alignment and numeric comparison policy live on the assessment, never on the public check.
- The complete `claim_dependencies` set is a host-authored DAG. A cross-claim report occurrence requires a declared edge. A downstream assessment that relies on a corrected upstream value binds to the upstream assessment result. A stale contradicted occurrence, unknown edge, cycle, or changed descendant fails closed. An upstream `not_checkable` or `changed_since_report` state forces the downstream customer resolution to `not_checkable` until grounded, even if a private report-consistency assessment runs.
- The coordinator resolution contains the exact assessment ids, host-authored state, final verdict, reason, and required action kind. One resolution produces one public check. Relevant unreconciled evidence or aligned conflicting assessments resolve `not_checkable`. Python validates the declared state table and never chooses a source-side winner or rewrites a verdict.
- Each public check keeps the existing fields: `id`, `claim_id`, `type`, `basis`, `verdict`, `importance`, `severity`, exact `report_quote`, complete private `addressed_clause_ids` and `assessment_ids`, exact grounding receipts, and `public_receipt`. The exact allowed private field set is in `role-contracts.json`; every unknown field and legacy `report_quote_2`, `addressed_clause_refs`, check-level `population_alignment`, or check-level `numeric_comparison` fails before grounding. There are no shims or aliases. `verdict` is `confirmed`, `contradicted`, `not_checkable`, or `changed_since_report`. Run status is separate and never becomes a claim outcome.
- Every material outcome needs a `public_receipt`. Its report operand has the canonical claim's exact `public_label`, exact value, and public location. Confirmed, contradicted, and changed outcomes have explicit decisive operands; not-checkable has none. The explanation is substantive and host-authored. Evidence-basis receipts link a retained `source_id`; report-basis receipts omit it. Generic operand labels fail the generic public-text contract. Other semantic safety remains the host's responsibility and a customer-page review criterion; Python does not match identifiers or rewrite customer text.
- Optional `public_receipt.calculation` uses restricted numeric arithmetic and a numeric public result. The private decisive assessment carries the host-selected rounded or absolute-tolerance comparison policy. Python recomputes exact values with that declaration. Policy fields remain private; the page may mechanically show the exact and customer-rounded results.
- A repeated-occurrence arithmetic correction uses one host-authored `correction_notice` naming every public location, the repeated report value, replacement value, and a substantive statement that every occurrence must change. The public explanation and a cited action copy that statement exactly. This does not create a second claim or confirmation.
- Exact evidence grounding uses explicit JSON pointers or one exact normalized quote. Numeric equivalence is allowed only after an explicit pointer or operand selected the value. Code never searches quantities to discover meaning or location.
- Population requirements are host-authored on canonical claims. An evidence assessment declaring `same_population` links every requirement id to an exact report quote and exact source receipt. `unreconciled` names the requirement ids, missing dimensions, conflict receipts, substantive reason, and reconciliation action. Python resolves the links and coverage; it does not decide whether populations mean the same thing.
- `presentation` is required. The coordinator authors one concise summary grounded to accepted check ids, selects at least one decision-relevant confirmation when confirmations exist, and authors the one Next block. Each action has an `A` plus digits id, a declared kind, exact text, exact visible report quote, accepted check ids, and complete resolution ids including dependency ancestors. `correct_report` is blocked by any unresolved ancestor or relevant source conflict. `reconcile_before_change` requires an unreconciled or dependency-unresolved resolution. Renderer text remains mechanical from accepted fields and fixed enum-label maps.
- Every accepted role run records role, stage, read-only input bundle path/digest, output bundle path/digest, allowed paths, and observed paths. Stage bundle content must match the exact contract and the exact downstream merge: claim-taker outputs equal coordinator partitions, semantic-plan inputs and outputs equal the approved manifest and merged handoff, verifier assessments and source rows equal the global-resolution input, and global-resolution output equals final `checks.json`. These are opaque-id and exact-value comparisons only. Final acceptance requires the complete zero-reason `preflight.json` and an unchanged bundle digest.
- The renderer puts each accepted material check `id` and verdict on exactly one card as `data-card-id` and `data-disposition`. At least one host-selected confirmation stays prominent when confirmations exist; lower-priority confirmations and full not-checkable receipts remain accessible under Technical detail. The public artifact remains `grade-artifact/public-receipt-v1`; private workflow fields never serialize.

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
