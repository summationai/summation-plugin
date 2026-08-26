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
3. Run `extract.py` now. That writes `report-visible.txt` and `findings.json`. If extract exits non-zero and `findings.json` exists, keep going.
4. If a nearby `evidence/` folder exists, ask once whether to use it. Copy those files into the run `evidence/` folder. Do not scan their whole disk.
5. If GitHub, Snowflake, Slack, or similar tools are already connected, ask once whether to query them. Save the raw result under `evidence/`. Name that file in `grade.json` `sources` with `"kind": "live_tool"`.
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
- When two rates sit in one table (40.0% then 43.0%), the move is percentage points (`pp`). Write `43.0 - 40.0` with result `3 pp`. Say `3 pp` in the Next step. A relative 7.5% is the wrong customer correction unless the report itself claims that relative form.
- If the report writes “improved 3%” for that table, contradict it. The Next step is: write “improved 3 pp week over week.”
- Write one Next step the customer can do.
- The summary count of material outcomes must match the `cards` array. If you wrote two cards, do not write four metrics. The scoreboard prints one box per card.

The page uses the Verify exemplar skin: FIX FIRST or SAFE TO SHARE, a scoreboard, a math table on numeric cards, and one Next step.

## grade.json

Write one object:

```json
{
  "summary": "One sentence the customer can forward.",
  "report_period": "Week ending 2026-04-04",
  "report_date": "2026-04-04",
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

Card `verdict` is `confirmed`, `contradicted`, `not_checkable`, or `changed_since_report`. If extract cannot read the file, also set top-level `"verdict": "unable_to_grade"`. A `changed_since_report` card needs `reconstruction_attempt`: one sentence that names the replacement.

If the report states a period, put that visible string in `report_period`. If it states a calendar date, put ISO `YYYY-MM-DD` in `report_date`. Those fields are not customer cards. `page.py` copies them onto the file line. Leave them out only when the report does not state them.

`page.py` prints receipt numbers with thousands separators. A calculation result rounds to the same decimal places as the report value. Customer dates on the page use American month-day order (`August 24, 2026`). Write `August 24` in explanations. Do not write `24 August`.

A `not_checkable` card has an explanation and no operands. An `evidence` card names `source_id` matching `SRC-<filename-without-extension>`.

When you queried a live tool in this run, add a top-level `sources` array. Each live row needs `"kind": "live_tool"`, `evidence_file` equal to the saved file name, and `retrieval` with `retrieved_at`, `tool`, and `arguments`. `page.py` hashes the file. The page prints `Live source Ran` only then. A nearby file you did not query stays a supplied file.

```json
"sources": [
  {
    "id": "SRC-get_currency_rates",
    "kind": "live_tool",
    "label": "currency_rates_input",
    "evidence_file": "get_currency_rates.json",
    "retrieval": {
      "retrieved_at": "2026-08-26T20:57:25Z",
      "tool": "get_currency_rates",
      "arguments": {"period": "Jul-26"}
    }
  }
]
```

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

Open `artifact/grade-artifact.html`. Read `verdict` from `grade-artifact.json`. Say that in plain language. If the page names a next step, repeat that step. If they want this in Summation, go to **Connected path**. Do not start that path during the local grade.

## Laws

- You author labels, verdicts, explanations, and the Next step.
- The lead sentence count must match the number of cards. Two cards means two outcomes, not four metrics.
- `not_checkable` means you looked and lacked evidence. Never present a skip as a completed check.
- No letter grade. No “Layer 1” / “Layer 2”.
- Accept the file they have. If extract reports no readable text, write `grade.json` with `"verdict": "unable_to_grade"`, one card that says why, and one Next that names a supported file type. Then run `page.py`. Do not stop at chat.
- Zero Summation login for the local grade.

### Optional local source wrapper

When an authenticated local SDK, CLI, or API profile can already read a source but no MCP tool exposes it, offer a local read-only FastMCP wrapper for the current host workflow. Explain the bounded scope and generate it only after explicit consent. Prefer that wrapper over a direct API or CLI call. Do not copy secrets into the host home.

A direct read-only API or CLI call remains valid if they decline the wrapper.

If they consent, the wrapper must:

- expose source-specific typed functions rather than arbitrary SQL or shell input;
- reuse the existing credential provider or profile without copying secrets into code, chat, logs, or evidence;
- mark every tool read-only, non-destructive, and idempotent;
- save the raw result under the run `evidence/` folder; and
- make one test call and retain its raw result before using the wrapper for a grade.

The wrapper lasts only for the current host workflow. A recurring Summation workflow still needs the equivalent source connection inside Summation. Keep this fallback optional: add no backend, relay, default-grade dependency, or mandatory wrapper step.

## Run directory

```text
run/
  report/               original file
  report-visible.txt    extract.py writes this
  evidence/             unchanged tool results and user files
  findings.json         extract.py writes this
  grade.json            you write this
  artifact/             page.py writes grade-artifact.html + .json
```

## Connected path

Use this after the local grade, or when they named a report that already lives in Summation and there is no disk file.

1. Itemized consent first. Name each file you would upload, or the Summation report they named. Wait for an explicit yes. Stop if they decline.
2. Authentication begins only after that consent. If they are not signed in, run the `signin` skill now.
3. If they consented to local files, upload only those files with the existing file-upload MCP tools.
4. Continue in the project chat with Addison.
5. If they ask for a cadence, use the existing Workflow tools (the `schedule` skill).

Never soften flags Addison returns. If that verification failed, the report is not safe to share.
