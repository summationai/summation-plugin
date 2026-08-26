# Verify agent roles

Use these roles to keep semantic judgment explicit and reviewable. The coordinator owns the final files, complete membership, canonicalization, and the single repair pass. Raw inventory begins unclassified.

## Coordinator

Partition the report by logical section, worksheet, or slide. Give each claim-taker only its bounded visible text, neutral inventory ids, and report metadata. Assign stable, non-overlapping candidate id ranges. Claim-takers do not receive approved evidence sources.

Receive all partition results together with the complete neutral inventory, report metadata, and opaque internal candidate facts. Declare canonical claims plus exact membership from worker candidate ids and inventory occurrence ids. Repeated labels, values, locations, formulas, or prose are not merge instructions. Decide claim importance and same-population membership yourself. The code validates only that every worker candidate and every inventory occurrence is consumed exactly once, every reference exists, and each material canonical claim has one evidence-verifier assignment.

Each material candidate enumerates its independently verifiable clauses as exact `{id, quote, public_label}` rows. Split a compound visible sentence into separate clause rows when the clauses can be checked independently. The coordinator maps every opaque clause ref exactly once to a canonical claim. It may keep multiple clauses in one canonical claim only when the assigned evidence verifier authors one receipt that explicitly addresses every member clause. Python validates ids and coverage only; it never discovers clauses from punctuation or prose.

Carry each canonical claim's clause `public_label` unchanged into the evidence-verifier input. Do not rename it during merge. A canonical `supporting_provenance` row also carries a substantive reason. One canonical assertion receives one outcome and one HTML card. If a KPI total and a table total are two displayed occurrences of the same assertion, include both clause refs in one canonical claim; do not create confirmed and contradicted aliases. For a contradicted report-basis calculation with repeated occurrence refs, the evidence verifier authors one `correction_notice` with the exact occurrence labels, repeated report value, replacement result, and a substantive statement that all named occurrences must change. Copy that exact statement into the public receipt explanation. The coordinator copies it into a cited `presentation.actions` row. Keep `structural_context` in the private coordinator handoff only. Each action has an `A` plus digits id, exact customer action text, an exact visible report quote, and the accepted check ids that support it. The renderer copies that text into the one Next block and never authors a recommendation.

Run `accept.py --preflight-only` before acceptance. It returns exact repair reasons for opaque membership, required substantive reasons, and numeric public calculation results. The entire run gets one repair pass: return those reasons to the responsible role, merge one repair, and rerun the failed validation once. Stop if a reason remains; do not create another repair loop.

## Claim-taker

Input:

- one bounded visible report section, worksheet, or slide;
- its inventory rows and exact inventory ids; and
- report period metadata when visible.

Output only classified candidates and their handoff metadata. Classify every assigned inventory occurrence exactly once as `material_claim`, `supporting_provenance`, or `structural_context`; missing classification fails closed. For a material candidate, return the exact full visible occurrence quote, stable candidate id, `importance: material`, exact inventory ids, and its explicit `clauses` rows. Each clause has a local id, exact visible clause quote, and public-safe `public_label`. For supporting provenance, return its exact quote, ids, `importance: supporting`, public-safe label, and substantive reason. For structural context, return exactly one inventory id, its exact visible quote, `importance: supporting`, and a substantive reason. Structural context produces no check or card and is stripped before public serialization.

Inventory rows use their raw `displayed` text and internal `location`; the candidate output carries only selected stable ids. For each material occurrence, enumerate all independently verifiable clauses with stable local ids, exact visible clause quotes, and distinct public labels. Do not combine independent clauses merely because they share one text occurrence. A `public_label` is the reader-facing name handed through the coordinator to `public_receipt.report_operand.label`; it is not a verdict and is not a substitute for the evidence verifier's complete `public_receipt`. Decide which statements are load-bearing and which displayed values belong to the same claim or population. Do not issue evidence verdicts. Do not use speaker notes, hidden metadata, or text outside the assigned partition.

## Evidence verifier

Input:

- only canonical claims assigned from the coordinator output;
- the relevant visible report text;
- approved retained source files or approved read-only tools; and
- exact internal candidates for those claim inventory ids.

The claim input is the coordinator's unchanged canonical output, including `public_label` and opaque clause membership. Output checks plus retained `sources` records. Each check lists every `addressed_clause_refs` row from its canonical claim; do not return a verdict for only part of that set. Decide whether the evidence answers each claim, then author the semantic verdict, severity, explicit public locations, decisive operands, substantive explanation, and public-safe source label. Copy the claim's `public_label` exactly into `public_receipt.report_operand.label`. Keep internal pointers and raw coordinates only in grounding fields. For an evidence-basis decisive check, link one retained `source_id`. For a report-basis decisive check, omit it. Every material disposition, including `not_checkable`, needs a complete `public_receipt`; `not_checkable` has no decisive operands.

For an explicit report-basis arithmetic check, `public_receipt.calculation.result` must be a numeric public value such as `12`, `$350,490.34`, `94%`, or `2 percentage points`. The declared verdict must agree with the recomputed values: differing report and calculation results cannot be `confirmed`, and equal values cannot be `contradicted`. Code rejects the row and never rewrites it. Arithmetic-use values do not become confirmations.

Severity is an agent-authored customer-priority field, not a machine finding. Contradicted, changed-since-report, and not-checkable outcomes remain prominent. A confirmed outcome with `high` or `medium` severity remains prominent; a confirmed outcome with `low` or null severity appears under Technical detail. Every material outcome remains a complete, identified, customer-accessible receipt card in either location.

Save every tool result before use. A live result records the exact retrieval time, tool, and safe arguments. A supplied file has no live retrieval metadata. Do not turn an internal candidate or arithmetic-use marker into a confirmation.

The evidence verifier authors retained source records, verdicts, labels, and receipts. It does not author `verification.live_source`: accepted source metadata drives that field mechanically. At least one validated `live_tool` source emits `complete`; when no validated `live_tool` source is retained, it emits `not_run`; public detail remains null.

## Host support

Use native subagents as the primary path when the host supports them. The coordinator remains the only writer of merged run files. Claim-takers run on bounded partitions, then the coordinator consumes every partition output, then evidence verifiers receive canonical claims only. If native subagents are unavailable, perform the same claim-taker, coordinator, and evidence-verifier stages sequentially with the same input schema and the same output schema. Both routes use the identical stage contracts in [role-contracts.json](role-contracts.json); only the execution topology changes.

The reference JSON is a routing and handoff contract, not execution proof. A later host run must establish whether its native or sequential route followed the contract.

Never launch hidden `claude -p`, a second login, or another agent process outside the host's visible orchestration. Do not pass credentials in prompts, source records, tool arguments, or evidence files.
