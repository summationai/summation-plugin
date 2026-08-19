---
name: doctor
description: Alias for diagnose — check whether Summation is connected and what data is visible. Use when tools fail, sign-in seems broken, or the user asks if setup is OK. Prefer diagnose.
---

# Doctor → diagnose

This skill was **renamed to `diagnose`**. Do **not** run `python3 ../api/scripts/sum_api.py doctor` (or any relative `../api/...` path). That path breaks when the host mounts skills as `summation:api` / `summation:doctor` rather than plain `api` / `doctor`.

## What to do

1. Follow the **`diagnose`** skill end-to-end.  
2. Auth and health checks: **`whoami`** on server **`summation`**, then list projects/connections/tables; when a shell is present, also `sumcli auth whoami` (401 → `sumcli auth login`).  
3. If not signed in → **`signin`** skill (browser OAuth). Never mint tokens with the legacy helper for day-to-day use.

Invoke the `diagnose` skill (`doctor` is an alias if the host still registers it).
