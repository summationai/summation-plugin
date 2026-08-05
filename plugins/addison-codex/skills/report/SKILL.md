---
name: report
description: Generate a Summation report from a question and export it (Markdown, PDF, or DOCX). Use when the user asks for an analysis, report, board update, or exportable document over their Summation data.
---

# Summation Report

Full pipeline via **MCP tools only**. Generation is one buffered result (~15–60s+, sometimes longer) — tell the user Addison is working; do not treat silence as failure before ~120s.

## Flow

1. **Project:** `list_projects` / `get_default_project`. Match `--project` by name or id; if none and exactly one project, use it; else list and ask.
2. **Snapshot:** `list_reports` for that project (note existing ids).
3. **Generate:** `start_report` with the user’s question (and project context as the tool requires). Take the new report id from the result; if ambiguous vs the snapshot, ask which report is theirs.
4. **Status:** `get_report_status` if still running.
5. **Export:** `export_report` — default **markdown** unless the user asked pdf/docx. Prefer exported content over raw markers; never paste internal cite markup.
6. **Report back:** title/id, content or file path, and offer `$addison-validate` before external share.

## Rules

- Long generation is normal — keep the user informed.
- On failure, include any `request_id` from the tool error.
- No REST / `sum_api.py` for this skill.
