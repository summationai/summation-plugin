---
name: signin
description: Connect Codex to Summation via the hosted MCP server. Use when the user needs to connect Addison, when Summation tools are missing or unauthenticated, or when any Summation MCP call fails with 401/403.
---

# Addison Sign-in

Auth is owned by Codex’s MCP client. You never mint, poll, store, or inject a credential. **External** and **internal** flows differ — detect mode first.

## 0. Detect mode (do this first)

```bash
printf '%s' "${ADDISON_PLUGIN_INTERNAL:-}"
```

Treat as **internal** only if the value is `1`, `true`, `yes`, or `on` (case-insensitive). Anything else (including empty) is **external**.

| Mode | Who | Experience |
|---|---|---|
| **External** (default) | Customers | One environment (plugin MCP URL). No env or tenant questions. |
| **Internal** | Summation employees (`ADDISON_PLUGIN_INTERNAL=1` in the shell that launched Codex) | Ask **environment**, then **tenant** guidance, then auth. |

## Fixed environments (allowlist — never free-form hosts)

| Env | MCP URL |
|---|---|
| `prod` | `https://mcp.summation.com/mcp` |
| `staging` | `https://staging-mcp.summation.com/mcp` |
| `sandbox` | `https://sandbox-mcp.summation.com/mcp` |

**Dogfood note:** the plugin’s bundled `.mcp.json` currently points `summation` at **sandbox**. External users use that as-is. After prod OAuth is live, the bundled default becomes prod; internals still pick via this skill.

---

## External flow (default)

Do **not** ask about environments or tenants. There is one host and one org session.

### E1. Check auth

Call MCP **`whoami`** on server **`summation`**.

| Outcome | Action |
|---|---|
| Identity returned | Report who they are; done (or hand off to `start`). |
| Needs authentication | Continue to E2. |
| Server missing | Enable/reload the **addison** plugin; do not hand-register alternate URLs. |

### E2. Authenticate

> Summation needs a one-time browser sign-in. When Codex prompts you to authenticate **summation**, approve it in the browser (same account/SSO as the web app). No password or token is pasted into this chat.

Invoke **`whoami`** again. Prefer `codex mcp login summation` (or the host Authenticate control) if tools are not yet authed.

### E3. Confirm

`get_default_project` or `list_projects`. Report identity + org. Ready.

---

## Internal flow (`ADDISON_PLUGIN_INTERNAL=1`)

### I1. Choose environment

Ask which environment they want: **prod**, **staging**, or **sandbox** (only these three). Default suggestion: **sandbox** for dogfood, **prod** for customer-shaped testing once prod OAuth is up.

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
codex mcp logout summation 2>/dev/null || true
codex mcp remove summation 2>/dev/null || true
codex mcp add summation --url '<ENV_MCP_URL>'
```

If `codex mcp add` is unavailable (e.g. Desktop-only), tell them to set the Summation MCP URL to the chosen env’s allowlisted host in `/mcp` (still no `Authorization` header), or re-auth after an admin points the plugin default.

### I4. Authenticate

Same browser prompt as external, for server **`summation`**. Then **`whoami`**.

### I5. Confirm

Report: **environment**, identity, **org/tenant**, scopes. Note that switching either env or tenant requires `$addison-signout` then this flow again.

---

## Rules (both modes)

- Never print, log, or commit tokens.
- Never ask the user to paste client secrets, device codes, or bearers into chat.
- Never use `sum_api.py login` / `login-poll` / `mcp-connect` for Codex auth.
- On later 401/403: re-run this skill (re-auth), do not improvise REST auth.
- Prefer the plugin/server named **`summation`** when multiple Summation-related MCP entries exist (unless the user explicitly wants another).
