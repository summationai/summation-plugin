---
name: diagnose
description: Diagnose Summation (sum-api) connectivity and auth. Use when Summation calls fail, credentials seem stale, or the user asks whether Summation is set up correctly.
---

# Summation Doctor

Run the bundled diagnostic from the sibling `api` skill (resolve relative to this skill's base directory):

```bash
python3 ../api/scripts/sum_api.py doctor
```

`doctor` reports: mode (`internal` true/false) and environment, base URL, config file path and mode, OpenAPI reachability (title/version/path count), and whether a credential is present. External is always production; internal reports the selected environment.

If the user reports Summation MCP tools failing with auth errors while `doctor` passes: the MCP registration carries its own bearer header — re-run `$addison-signin` (steps 1-4) to mint a fresh credential and re-register the server via `mcp-connect`.

For the full **preflight** (authenticated environment summary — identity, org, projects, tables, views, connections, all counted and named):

```bash
python3 ../api/scripts/sum_api.py preflight
```

Render preflight as a short environment card: who you are (tenant, scopes), what's connected, what's reachable, plus 2–3 sample questions that would work against the real table names found.

To trace recent API activity (every call logs one line with `request_id` to `~/.summation/audit.jsonl`):

```bash
python3 ../api/scripts/sum_api.py audit --tail 20
```

## Interpreting results

- OpenAPI unreachable → network problem, not auth (the base URL is always an allowlisted Summation environment).
- No credential found → hand off to the `signin` skill.
- 401 on the list call → credential invalid or expired; re-run `login`.
- 403 → scope problem; report the `request_id` and the granted scopes.
- Always include `request_id` from any failing response — it joins client failures to server-side traces.
