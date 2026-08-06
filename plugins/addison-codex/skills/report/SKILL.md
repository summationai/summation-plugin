---
name: report
description: Generate a Summation report from a question and export it (Markdown, PDF, or DOCX). Use for analyses, board updates, or exportable documents over Summation data.
---

# Summation Report

MCP tools only. Generation can take **several minutes** — keep the user informed; do not treat silence as failure after only ~2 minutes if the run is still active.

## Flow

1. **Project:** `list_projects` / `get_default_project`. Match name/id; if none and exactly one, use it; else list and ask.  
2. **Snapshot** existing reports if tools allow (`list_reports` or project files) so you can tell new from old.  
3. **Generate:** `start_report` with the question and project context.  
   - Tell the user: “Building your report — this can take a few minutes.”  
   - While waiting, brief progress every ~30–45s (“Still working…”).  
   - Poll `get_report_status` / conversation status until terminal (or up to ~7–10 minutes before declaring a hang).  
4. **Verify before celebrating:** export or open content; confirm it’s **non-empty** and looks like the real report (not a stub). If `list_reports` is empty but files exist, use file tools.  
5. **Export:** `export_report` — default **markdown** unless they asked pdf/docx. No internal cite markup.  
6. **Hand back:** title, short summary, offer `$addison-validate` before external share.

## Rules

- Never claim “report done” without a real artifact check.  
- On failure, plain language first; include `request_id` if present for support.  
- No REST helper for this skill.
