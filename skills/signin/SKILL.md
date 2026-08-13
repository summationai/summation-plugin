---
name: signin
description: Connect the host to Summation via the hosted MCP server. Use when the user needs to connect Summation, when Summation tools are missing or unauthenticated, or when any Summation MCP call fails with 401/403.
---

# Summation Sign-in

Auth is owned by the host MCP client. You never mint, poll, store, or inject a credential. **External** and **internal** flows differ — detect mode first.

## 0. Detect mode (do this first)

```bash
printf '%s' "${SUMMATION_PLUGIN_INTERNAL:-${ADDISON_PLUGIN_INTERNAL:-}}"
```

Treat as **internal** only if the value is `1`, `true`, `yes`, or `on` (case-insensitive). Anything else (including empty) is **external**.

| Mode | Who | Experience |
|---|---|---|
| **External** (default) | Customers | One environment (plugin MCP URL). No env or tenant questions. |
| **Internal** | Summation employees (`SUMMATION_PLUGIN_INTERNAL=1` in the shell that launched Claude; `ADDISON_PLUGIN_INTERNAL` still works) | Ask **environment**, then **tenant** guidance, then auth. |

## Fixed environments (allowlist — never free-form hosts)

| Env | MCP URL |
|---|---|
| `prod` | `https://mcp.summation.com/mcp` |
| `staging` | `https://staging-mcp.summation.com/mcp` |
| `sandbox` | `https://sandbox-mcp.summation.com/mcp` |

The plugin’s bundled `mcp.json` points `summation` at **production** (`https://mcp.summation.com/mcp`). Internal users can switch env at sign-in.

---

## External flow (default)

Do **not** ask about environments or tenants. There is one host and one org session.

### E1. Check auth

Call MCP **`whoami`** on server **`summation`**.

| Outcome | Action |
|---|---|
| Identity returned | Report who they are; done (or hand off to `start`). |
| Needs authentication | Continue to E2. |
| Server missing | Enable/reload the **summation** plugin; do not hand-register alternate URLs. |

### E2. Authenticate

> Summation needs a one-time browser sign-in. When the host prompts you to authenticate **summation**, approve it in the browser (same account/SSO as the web app). No password or token is pasted into this chat.

Invoke **`whoami`** again. Prefer the host Authenticate control (`/mcp`, or `codex mcp login summation`) if tools are not yet authed.

### E3. Confirm

`get_default_project` or `list_projects`. Report identity + org. Ready.

---

## Internal flow (`SUMMATION_PLUGIN_INTERNAL=1`)

### I1. Choose environment

Ask which environment they want: **prod**, **staging**, or **sandbox** (only these three). Default suggestion: **prod** (matches the plugin default).

Do not accept arbitrary URLs or hosts.

### I2. Tenant (org)

Explain clearly:

> MCP auth binds to the **org you approve in the browser** (your active org on the Summation web app for that environment).  
> To use a different tenant: switch org on that env’s web app first, then we re-authenticate.  
> Env and tenant both change only by signing out and signing in again.

If they need a specific tenant now, pause until they’ve switched org on the web app, then continue.

### I3. Point `summation` at the chosen env (headerless)

User-scope override so the chosen env wins over the plugin default. Do **not** set an `Authorization` header or any bearer token — host OAuth owns the credential.

```bash
# replace URL with the allowlisted URL for the chosen env
# Claude Code:
claude mcp remove -s user summation
claude mcp add -s user --transport http summation '<ENV_MCP_URL>'
# Codex:
codex mcp logout summation
codex mcp remove summation
codex mcp add summation --url '<ENV_MCP_URL>'
```

Remove may fail with “not found / not registered” — that is fine; continue to **add**. Surface any other remove failure. **Add** must succeed before auth.

If the host CLI add is unavailable (Desktop-only), tell them to set the Summation MCP URL to the chosen env’s allowlisted host in the host MCP UI (still no `Authorization` header), or re-auth after an admin points the plugin default.

### I4. Authenticate

Same browser prompt as external, for server **`summation`**. Then **`whoami`**.

### I5. Confirm

Report: **environment**, identity, **org/tenant**, scopes. Note that switching either env or tenant requires the `signout` skill, then this flow again.

---

## Rules (both modes)

- Never print, log, or commit tokens.
- Never ask the user to paste client secrets, device codes, or bearers into chat.
- Never use `sum_api.py login` / `login-poll` / `mcp-connect` for host MCP auth.
- On later 401/403: re-run this skill (re-auth), do not improvise REST auth.
- Prefer the plugin/server named **`summation`** when multiple Summation-related MCP entries exist (unless the user explicitly wants another).
