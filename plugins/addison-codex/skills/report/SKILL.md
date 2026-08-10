---
name: report
description: "Generate a Summation report from a question and export it (Markdown, PDF, or DOCX). Use for analyses, board updates, or exportable documents over Summation data."
---

# Summation Report

MCP tools only. Generation can take a few minutes — keep the user informed.

## Flow

1. **Project:** `list_projects` / `get_default_project`. Match name/id; if none and exactly one, use it; else list and ask.  
2. **Snapshot** `list_reports` so you can tell new from old.  
3. **Generate:** `start_report` with the question and project context.  
   - “Building your report — this can take a few minutes.”  
   - Brief progress every ~30–45s while waiting.  
   - Follow status until complete (or a clear failure).  
4. **Verify:** `export_report` (or get content) and confirm it’s **non-empty** and looks like the real report.  
5. **Export format:** default **markdown** unless they asked pdf/docx. No internal cite markup.  
6. **Hand back:** title, short summary, offer `$addison-validate` before external share.

## Rules

- Never claim “report done” without a real content check.  
- On failure, plain language first; include `request_id` if present for support.  
- No REST helper.
