---
name: schedule
description: Schedule recurring Summation playbook runs with email delivery — list, create, pause, resume, or trigger schedules. Use when the user wants a report/playbook on a cadence ("every Monday", "daily at 9am") or asks what's scheduled.
---

# Summation Schedule

Recurring playbook runs, email delivery. **MCP tools only.**

## Flows

**Inspect:** `list_schedules` → table of description, kind, cadence (+ timezone), target, status. History: `list_schedule_runs` / `get_schedule`.

**Create:**
1. Schedules target **playbooks** (`list_playbooks` / `get_playbook`). If none exists for the ask, say so — `$addison-report` is one-off; a playbook must exist first.
2. Build the schedule body per the tool schema: target ids, cadence (`time_of_day`, **explicit timezone** — ask, never assume), `email_recipients` (to/cc/bcc).
3. **Confirm before `create_schedule`:** read back what runs, when (with zone), and exactly who is emailed. Create only after an explicit yes.
4. Report schedule id and first expected run.

**Operate:** pause / resume / run-now via the matching schedule tools. Run-now emails recipients — confirm first. Delete only when the user names the exact schedule and confirms.

## Rules

- Recipient lists are blast radius: verbatim read-back; never add recipients the user didn’t name.
- Always show cadence with timezone.
- Surface `request_id` on errors.
- No REST helper for this skill.
