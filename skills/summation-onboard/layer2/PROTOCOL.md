# Layer 2 — the agentic verifier, with receipts

Layer 1 (`summation-flow verify --cold`) is deterministic: it checks arithmetic, units, rounding, and periods. It cannot read meaning. Layer 2 is an agent that reads the report **and every evidence file** and hunts for what Layer 1 cannot see: claims that contradict the evidence, stale statements, internal logic breaks, and tone problems.

## The honesty rule

The agent proposes; the machine checks the receipts. Every finding must carry two verbatim quotes:

- `report_quote` — copied exactly from the report.
- `evidence_quote` — copied exactly from the named evidence file (empty only for `type: "internal"` findings, which instead carry a second report quote in `report_quote_2`).

`receipts.py` verifies each quote appears in its source (whitespace-normalized, HTML tags stripped). A finding whose quotes do not verify is **discarded**. Nothing invented survives.

## The findings file

The agent writes `layer2-findings.json` beside the report:

```json
{
  "layer2_version": "layer2-findings/v1",
  "report": "weekly-meeting-review.html",
  "findings": [
    {
      "id": "L2-001",
      "type": "semantic",
      "severity": "high",
      "report_quote": "…",
      "evidence_file": "evidence/meetings.json",
      "evidence_quote": "…",
      "explanation": "one sentence: what contradicts what"
    }
  ]
}
```

`type` is one of: `semantic` (says something the evidence contradicts), `staleness` (was true, no longer is), `internal` (the report contradicts itself), `logic` (a conclusion its own numbers do not support), `tone` (advisory only — never a defect).

## Scoring

`receipts.py --answers <answers.json>` scores validated findings against the fixture's planted defects: a planted defect counts as caught when a validated finding's report quote contains the defect's `shown` text. Output: caught / missed per defect, plus any extra validated findings for human review.
