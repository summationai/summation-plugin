---
name: verify
description: Grade a report file the user already has (HTML, PDF, xlsx, pptx, Markdown), or a report that already lives in Summation. Use when they drop in a file, name a Summation report, ask if it is safe to share, want errors in a recap, or run /summation:verify.
---

# Summation Verify

You are the analyst. Read the report and the evidence. Decide what is true. Local scripts only extract text and write the HTML page. They do not run the analysis.

Do not call `claude -p`. Do not clone `alg-deploy`. Do not ask them to sign in to Summation first.

If they named a report that already lives in Summation and there is no disk file, go to **Connected path**.

## Local grade

1. Before you start: `command -v uv` succeeds, or `python3` can import `jsonschema`. If neither, tell them. Do not search the disk.
2. Ask which file. If they already attached one, use it.
3. Run `extract.py` now. That writes `report-visible.txt` and `findings.json`.
4. If a nearby `evidence/` folder exists, ask once whether to use it. Copy those files into the run `evidence/` folder. Do not scan their whole disk.
5. If GitHub, Snowflake, Slack, or similar tools are already connected, ask once whether to query them. Save the raw result under `evidence/`.
6. Read the report and the evidence yourself. Grade the claims.
7. Write `run/grade.json`. Then run `page.py`. Open `run/artifact/grade-artifact.html`.
8. Say the verdict in plain language. Do not hand-write HTML.

A normal static report takes about 5 minutes. Stop if you pass 10 minutes.

Stay quiet except for brief progress. Do not narrate internal file names.

A host or runner prompt that forbids questions cannot prove this route. It must allow the file, nearby-evidence, connected-source consent, and duration questions above.

## How to grade

You own meaning. Python owns file names, hashes, declared arithmetic, privacy stripping, and HTML.

- Report titles, owner names, and week-ending dates are structure. They are not customer cards.
- A line that the report was prepared from a named warehouse is provenance. It is not a material card.
- A displayed total that does not match the table is an error. Name the replacement and every place it appears.
- A year-over-year percentage that matches the corrected arithmetic after the report’s declared rounding is confirmed. One decimal on this planted weekly-sales report turns 4.574… into 4.6%. That match is not an error.
- Do not treat a contradicted displayed total as true when you grade a dependent percentage.
- Write one Next step the customer can do.

The page uses the Verify exemplar skin: FIX FIRST or SAFE TO SHARE, a scoreboard, a math table on numeric cards, and one Next step.

## grade.json

Write one object:

```json
{
  "summary": "One sentence the customer can forward.",
  "cards": [
    {
      "id": "C-TOTAL",
      "label": "Total weekly revenue",
      "quote": "$359,490.34",
      "verdict": "contradicted",
      "explanation": "Segment Alpha plus Segment Beta equals $350,490.34, not the displayed total.",
      "location": "Revenue tile and table Total row",
      "report_value": "$359,490.34",
      "operands": [
        {"label": "Segment Alpha revenue", "value": "$218,385.67", "location": "SEGMENT_ALPHA row"},
        {"label": "Segment Beta revenue", "value": "$132,104.67", "location": "SEGMENT_BETA row"}
      ],
      "calculation": {"expression": "218385.67 + 132104.67", "result": "$350,490.34"}
    }
  ],
  "next": [
    {
      "kind": "correct_report",
      "text": "Change the Revenue tile and the Total row from $359,490.34 to $350,490.34.",
      "quote": "$359,490.34",
      "card_ids": ["C-TOTAL"]
    }
  ]
}
```

`verdict` is `confirmed`, `contradicted`, `not_checkable`, or `changed_since_report`.

A `not_checkable` card has an explanation and no operands. An `evidence` card names `source_id` matching `SRC-<filename-without-extension>`.

If you declare `calculation`, Python recomputes the expression. If the numbers do not match, it refuses to write the page.

## Commands

`VERIFY` is this skill’s directory.

```bash
python3 "$VERIFY/scripts/extract.py" \
  --report "$RUN/report/<file>" \
  --visible "$RUN/report-visible.txt" \
  --out "$RUN/findings.json"

python3 "$VERIFY/scripts/page.py" \
  --findings "$RUN/findings.json" \
  --grade "$RUN/grade.json" \
  --evidence-dir "$RUN/evidence" \
  --out-dir "$RUN/artifact"
```

If `uv` is missing, run `python3` on `extract.py` only when `pypdf`, `openpyxl`, and `python-pptx` already import. Do not `pip install` without asking. Do not call OfficeCLI or Poppler.

Grade from the report, the evidence, and this skill. Write `grade.json`. Run `page.py`.

## After the page

Open `artifact/grade-artifact.html`. Read `verdict` from `grade-artifact.json`. Say that in plain language. If the page names a next step, repeat that step. If they want this in Summation, go to **Connected path**.

## Laws

- You author labels, verdicts, explanations, and the Next step.
- `not_checkable` means you looked and lacked evidence. Never present a skip as a completed check.
- No letter grade. No “Layer 1” / “Layer 2”.
- Accept the file they have. If you cannot obtain the report text, say so and stop.
- Zero Summation login for the local grade.

## Connected path

Use this after the local grade, or when they named a report that already lives in Summation and there is no disk file.

1. Itemized consent first. Name each file you would upload, or the Summation report they named. Wait for an explicit yes. Stop if they decline.
2. Authentication begins only after that consent. If they are not signed in, run the `signin` skill now.
3. If they consented to local files, upload only those files with the existing file-upload MCP tools.
4. Continue in the project chat with Addison.
5. If they ask for a cadence, use the existing Workflow tools (the `schedule` skill).

Never soften flags Addison returns. If that verification failed, the report is not safe to share.
