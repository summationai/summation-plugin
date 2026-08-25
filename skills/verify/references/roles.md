# Verify agent roles

Use these roles to keep semantic judgment explicit and reviewable. The coordinator owns the final files and the single repair pass.

## Coordinator

Partition the report by logical section, worksheet, or slide. Give each worker only its bounded visible text, inventory ids, and approved source records. Assign stable, non-overlapping claim and check id ranges.

Merge and deduplicate by exact claim id, check id, inventory id, and source id. Resolve cross-section claims yourself. Do not merge two populations because their labels sound similar. Carry each accepted claim's `public_label` unchanged into the evidence-verifier input; do not rename it during merge. Retain one source record per exact raw result and digest. Run `accept.py`, return every exact discard reason to the responsible role once, merge the repair, then render.

## Claim-taker

Input:

- one bounded visible report section, worksheet, or slide;
- its inventory rows and exact inventory ids; and
- report period metadata when visible.

Output only claims and their claim-handoff metadata. For each claim, return the exact visible quote, stable claim id, material or supporting classification, importance, exact inventory ids, and `public_label`, an explicit public-safe claim label. Inventory rows use their raw `displayed` text and internal `location`; the claim output carries only the selected stable ids. The label is the reader-facing name handed to the evidence verifier for `public_receipt.report_operand.label`; it is not a verdict and is not a substitute for the evidence verifier's complete `public_receipt`. Decide which statements are load-bearing and which displayed values belong to the same claim or population. Do not issue evidence verdicts. Do not use speaker notes, hidden metadata, or text outside the assigned section.

## Evidence verifier

Input:

- bounded accepted claims;
- the relevant visible report text;
- approved retained source files or approved read-only tools; and
- exact internal candidates for those claim inventory ids.

The claim input is the coordinator's unchanged claim-taker output, including `public_label`. Output checks plus retained `sources` records. Decide whether the evidence answers each claim, then author the semantic verdict, explicit public locations, decisive operands, substantive explanation, and public-safe source label. Copy the claim's `public_label` exactly into `public_receipt.report_operand.label`. Keep internal pointers and raw coordinates only in grounding fields. For an evidence-basis decisive check, link one retained `source_id`. For a report-basis decisive check, omit it. Every material disposition, including `not_checkable`, needs a complete `public_receipt`; `not_checkable` has no decisive operands.

Save every tool result before use. A live result records the exact retrieval time, tool, and safe arguments. A supplied file has no live retrieval metadata. Do not turn an internal candidate or arithmetic-use marker into a confirmation.

The evidence verifier authors retained source records, verdicts, labels, and receipts. It does not author `verification.live_source`: accepted source metadata drives that field mechanically. At least one validated `live_tool` source emits `complete`; when no validated `live_tool` source is retained, it emits `not_run`; public detail remains null.

## Host support

Use native subagents as the primary path when the host supports them. The coordinator remains the only writer of merged run files. If native subagents are unavailable, perform claim-taking and evidence verification sequentially with the same input schema and the same output schema. Both routes use the identical stage contracts in [role-contracts.json](role-contracts.json); only the execution topology changes.

The reference JSON is a routing and handoff contract, not execution proof. A later host run must establish whether its native or sequential route followed the contract.

Never launch hidden `claude -p`, a second login, or another agent process outside the host's visible orchestration. Do not pass credentials in prompts, source records, tool arguments, or evidence files.
