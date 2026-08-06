---
name: schedule
description: Schedule recurring Summation playbook runs with email delivery — list, create, pause, resume, or run now.
---

# Summation Schedule

MCP only. Schedules email real people — confirm carefully.

## Flows

**List:** `list_schedules` → plain table: what, when (with timezone), who gets email, status. History via run tools if needed.

**Create:**
1. Needs a **playbook** (`list_playbooks`). If none: say playbooks are authored in the Summation app today; one-off reports use `$addison-report`.  
2. Cadence with **explicit timezone** (ask; never assume).  
3. Recipients exactly as the user named.  
4. **Read back** what / when / who → get an explicit yes → `create_schedule`.  
5. Confirm it appears in `list_schedules`.

**Operate:** pause / resume / run-now with confirmation when email will fire. Don’t invent update tools if missing — say changes may need the web app until update is available.

## Rules

- No recipients the user didn’t name.  
- Always show timezone.  
- Plain language to the user.  
- No REST helper.
