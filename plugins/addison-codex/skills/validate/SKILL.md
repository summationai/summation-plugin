---
name: validate
description: Verify a Summation report against its sources before sharing — runs the report verification pipeline and summarizes verdicts and citations. Use before any report goes to an executive or external recipient, or when the user asks "is this right?".
---

# Summation Validate

Nothing executive-facing ships without validation. **MCP tools only.** `validate_report` is buffered (~15–60s) — say validation is running; wait ~120s before failing.

## Flow

1. Resolve project (`list_projects` / `get_default_project`) and report (`list_reports`; match id or name, newest first when ambiguous).
2. Call **`validate_report`** for that report.
3. Summarize as a verdict panel:
   - **Checked claims:** verified / flagged / unverifiable counts
   - **Flagged items:** claim, why, cited source
   - **Overall:** safe to share / share with caveats / fix first

## Rules

- Never soften flagged findings — list them before the overall judgment.
- If verification fails, report the error/`request_id` and stop; do not declare the report valid.
- After `$addison-report`, offer validation proactively.
- No REST helper for this skill.
