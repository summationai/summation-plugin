---
name: schedule
description: Schedule recurring Summation playbook runs with email delivery — list, create, update, pause, resume, or run now.
---

# Summation Schedule

Execute via **sumcli** when a shell is available (see `../api/references/sumcli.md`); the MCP tools below are the shell-less fallback. Schedules email real people — confirm carefully.

## Flows

**List:** `list_schedules` → plain table: what, when (with timezone), who gets email, status. History via run tools as needed.

**Create / update:**
1. Needs a **playbook** (`list_playbooks` / create or update via available playbook tools if the user is authoring one). One-off docs without a playbook → the `report` skill.  
2. Cadence with **explicit timezone** (ask; never assume).  
3. Recipients exactly as named.  
4. **Read back** what / when / who → explicit yes → `create_schedule` or the update/patch tool if changing an existing schedule.  
5. Confirm via `list_schedules` / `get_schedule`.

**Operate:** pause / resume / run-now with confirmation when email will fire.

## Rules

- No recipients the user didn’t name.  
- Always show timezone.  
- Prefer partial updates when a patch/update tool exists — don’t wipe fields the user didn’t mention.  
- Plain language. No REST helper.
