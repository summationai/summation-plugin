# Verify agent roles

This is the private `verify-role-handoff/coordinator-v6` workflow. The public artifact remains `grade-artifact/public-receipt-v1`. Host roles author meaning. Python validates exact mechanics and never infers semantics from prose, tags, labels, keys, locations, formulas, identifiers, or value overlap. Raw inventory begins unclassified.

## Stage sequence

1. Mechanical intake builds the neutral occurrence inventory and hashes the report and approved sources.
2. Bounded claim-takers classify every assigned occurrence and author exact material clauses.
3. The coordinator reviews every classification and declares canonical claims, population requirements, the source-by-claim plan, dependency DAG, and verifier assignments.
4. The shared validator preflights that semantic plan mechanically.
5. Evidence verifiers run in dependency order and author private assessments, explicit operand origins, source decisions, proposed resolutions, and public checks.
6. The coordinator reconciles all assessments and source pairs into one resolution and one check per material claim, then authors presentation and actions.
7. `validate_acceptance_bundle()` runs one full preflight and records the exact bundle digest and complete repair-reason set.
8. At most one bounded repair is allowed. `role_provenance.repair_passes_used` is exactly `0` or `1`; every repaired input uses `repair_context.repair_pass_id: 1`. Every affected descendant, resolution, and presentation row is regenerated once.
9. Final acceptance reruns the same validator against the unchanged digest before render and audit.

## Coordinator semantic plan

Partition the report by logical section, worksheet, or slide. Materialize one read-only input bundle for each claim-taker containing only its bounded visible text, neutral inventory rows, visible report metadata, and this role contract. Claim-takers do not receive approved evidence values, prior claims, a prior page, or an answer key. An initial assignment must not prescribe classifications, verdicts, severities, check ids, public labels, operands, calculations, dependencies, numeric precision or tolerance, expected counts, score, a source-side winner, summary, or action.

A prior grade artifact is never semantic input.

Receive every partition output together with the complete neutral inventory, report metadata, canonical approved-source manifest, and opaque internal candidates. Review every occurrence exactly once. An `accept` review preserves the claim-taker classification and material clauses. A `demote` review may change a material proposal to supporting provenance or structural context and accepts no material clause. An unresolved `challenge` blocks the run. The coordinator cannot promote a nonmaterial proposal by inventing a material clause; the claim-taker must author that clause during the one bounded repair or the run fails closed.

Declare the canonical material claims from exact clause ids and occurrence ids. Repeated labels, values, locations, formulas, or prose are not merge instructions. Independently verifiable clauses remain separate claims unless one assigned verifier will address every clause in one receipt. Repeated visible occurrences of one assertion may belong to one canonical claim. One canonical claim later receives one resolution, one public outcome, and one HTML card. Carry the selected clause `public_label` unchanged into the verifier input. Keep structural context private and retain a substantive reason for every supporting or structural classification.

For each canonical claim, declare any required population dimensions as exact ids, enums, and visible report quotes. Declare every source/material-claim pair in `source_consideration_plan` before verifier assignment. Each row has one host decision, `consider` or `exclude`, and a substantive reason. Declare a complete claim-dependency DAG and each verifier assignment. Python validates only exact ids, complete and unique coverage, exact spans, known enums, and acyclicity; it does not decide a classification, canonical grouping, source relevance, population requirement, dependency, or verifier judgment.

Run the shared semantic-plan preflight before evidence verification. A missing review, clause membership, source pair, dependency endpoint, or verifier assignment returns an exact mechanical reason. No public artifact can be produced from a partial plan.

The materialized semantic-plan input must exactly match the collected claim-taker outputs, neutral inventory, visible report metadata, and canonical approved-source manifest. Its output must exactly match the coordinator handoff merged into `claims.json`. Python compares these bundles by opaque ids and exact values; it does not judge their meaning.

## Claim-taker

Input:

- one bounded visible report section, worksheet, or slide;
- its inventory rows and exact inventory ids; and
- report period metadata when visible.

Output only `partition_id`, `occurrence_decisions`, and `clauses`. Classify every assigned inventory occurrence exactly once as `material_claim`, `supporting_provenance`, or `structural_context`; missing classification fails closed. Every occurrence decision names its exact occurrence id, classification, substantive reason, and clause ids. A nonmaterial decision has no clause ids. Structural context produces no check or card and is stripped before public serialization. Supporting provenance stays outside the material ledger.

For each material occurrence, enumerate every independently verifiable clause. Each clause has one stable id, its occurrence id, a zero-based `[start,end)` span into normalized `displayed` text, the exact substring quote, a public-safe `public_label`, and exact context occurrence ids. Do not combine independent clauses merely because they share one text occurrence. A `public_label` is the reader-facing name handed unchanged through the coordinator to `public_receipt.report_operand.label`; it is not a verdict or a substitute for a complete receipt. Decide which statements are load-bearing and which displayed values belong to the same claim or population. Do not issue evidence verdicts. Do not use speaker notes, hidden metadata, or text outside the assigned partition.

## Evidence verifier

The coordinator schedules verifiers in dependency order. A verifier receives only its assigned canonical claims, relevant visible report text, assigned canonical sources, the exact coordinator source-plan rows, and accepted upstream assessment results named by the dependency DAG. The canonical `public_label` and clause membership are unchanged.

Author one or more private assessments for each assigned claim. Each assessment declares its basis and effect, exact operand bindings, and any upstream assessment ids. Allowed origins are only an exact report occurrence, an exact retained-source pointer or normalized quote, or the declared numeric result of an accepted upstream assessment. The dependency list must exactly match upstream assessment-result origins. If an upstream contradicted occurrence has one accepted replacement, a downstream calculation consumes that result rather than the stale occurrence. If the upstream claim is not checkable or changed since the report, a private report-consistency assessment may run, but the downstream resolution remains `not_checkable` and no `correct_report` action may use it until the dependency is grounded.

For every coordinator source-plan row assigned to the verifier, return one source-consideration result. A considered pair produces an assessment. An excluded pair retains a substantive verifier reason. A disagreement with the coordinator remains unresolved and blocks final acceptance. Population alignment lives on an evidence assessment. `same_population` links every declared requirement id to an exact visible report quote and exact source receipt. `unreconciled` names the missing dimensions, exact conflict receipts, substantive reason, and reconciliation action. Python resolves the declarations but never decides that populations match.

For report arithmetic, author an exact public numeric calculation result and a private numeric policy: rounded with `half_up` or `half_even` plus decimal places, or absolute tolerance. Python recomputes the declared operands and applies only that policy. It never chooses precision from prose or formatting. Numeric policy, dependency data, assessment ids, and population declarations stay private.

Propose one resolution and one public check for each canonical claim. The check lists the complete `addressed_clause_ids` and exact `assessment_ids`. Decide the verdict, severity, public-safe labels and locations, decisive operands, explanation, and source label. Copy the canonical `public_label` exactly to `public_receipt.report_operand.label`. Customer-safe wording remains the host's responsibility and a page-review criterion; Python does not detect identifiers or rewrite semantic text. Every material verdict, including `not_checkable`, needs the current public-v1 receipt. An unreconciled multi-basis claim uses a prose-only not-checkable receipt with no decisive operands or calculation.

Save every tool result before use. A live source records retrieval time, tool, and safe arguments; a supplied file has no live retrieval metadata. Verifiers cite canonical retained source ids and never create duplicate physical source rows. Accepted source metadata alone drives `verification.live_source`: `complete` when a validated `live_tool` exists, otherwise `not_run`; detail remains null.

## Coordinator global resolution

After all dependency waves, merge the exact verifier outputs. Preserve every coordinator source-plan decision in the final source-by-claim matrix and require one verifier result per pair. Reconcile all assessments into exactly one resolution and one public check per material canonical claim. Any relevant unreconciled assessment, aligned conflict, missing decisive assessment, or unresolved dependency produces `not_checkable`. A changed-since-report assessment stays distinct. Python validates the host-authored states and exact ids; it never writes or rewrites the verdict.

The assessment and source-pair rows materialized by evidence verifiers must exactly account for the rows passed into global resolution. The global-resolution output must exactly match the final retained sources, source matrix, whole-source exclusions, assessments, resolutions, checks, and presentation accepted from `checks.json`. A missing, substituted, or extra row fails closed before render.

Author presentation only after the full dependency, source, and resolution ledgers are complete. The summary and each action cite accepted check ids and resolution ids. Every action includes the complete dependency closure. `correct_report` requires a stable contradicted resolution with a grounded replacement and no unresolved ancestor or relevant source conflict. `reconcile_before_change` requires an unreconciled resolution. At least one host-selected decision-relevant confirmation stays visible when confirmations exist. Per-claim source exclusions remain private; only separately authored whole-source exclusions appear in Technical scope.

Run one full `validate_acceptance_bundle()` preflight and record its bundle digest and complete reasons. The entire run has at most one repair. Give the responsible role only its original read-only input bundle, prior output, exact mechanical reasons, and the shared `repair_pass_id: 1`. Set top-level `role_provenance.repair_passes_used` to `0` when no repair ran and `1` when it did. All repaired role inputs share that id, and a role target has at most one repaired generation. The repair ledger is part of the full bundle digest. A second id, a repaired input with a zero-pass declaration, or another generation after pass 1 fails closed. Regenerate every affected descendant, resolution, and presentation row. Final acceptance reruns the same validator and requires the unchanged preflight digest and zero reasons.

Before grounding, each coordinator-v6 check contains only the exact allowed private check fields in [role-contracts.json](role-contracts.json). Legacy `report_quote_2`, `addressed_clause_refs`, check-level `population_alignment`, check-level `numeric_comparison`, and any other unknown semantic field fail closed. There are no compatibility aliases or inferred migrations. Numeric comparison and population alignment remain private assessment fields.

## Host support

Use native subagents as the primary path when the host supports them. The coordinator remains the only writer of merged run files. Materialize a read-only input JSON and an output JSON for every role run. Record both digests, the allowed read paths, and the observed read paths. A read of a prior artifact, unrelated partition, evaluator control, or product checkout fails the route proof.

If native subagents are unavailable, perform the same stage sequence sequentially with the same input schema and the same output schema. Both routes use the identical nine stage names and four role-bundle contracts in [role-contracts.json](role-contracts.json); only execution topology changes. The reference JSON is a routing and handoff contract, not execution proof. A later host run must prove the route, bundle digests, and read-path provenance.

Never launch hidden `claude -p`, a second login, or another agent process outside the host's visible orchestration. Do not pass credentials in prompts, source records, tool arguments, or evidence files.
