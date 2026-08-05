---
name: signin
description: Sign in to Summation from Codex. Use when the user needs to connect Addison, fix credentials, or when any Summation call fails with 401/403 and no valid session exists.
---

# Addison Sign-in

One browser sign-in connects everything: the sum-api credential and the hosted Summation MCP server. The helper lives in the sibling `api` skill: `../api/scripts/sum_api.py`.

**The one rule that matters:** the user's only job is to open a link and approve — show it in a message you write, never buried in command output, and always before you poll.

First, detect mode (this decides whether to offer an environment):

```bash
python3 ../api/scripts/sum_api.py mode
```

- `"internal": false` -> production only. Do not ask about environments or tenants.
- `"internal": true` -> internal user. Ask which environment from the returned `environments` list (prod / staging / sandbox) and pass it as `--env` below. Tenant binds to the org they approve in on the web app; to change environment or tenant, sign out and sign in again.

## Flow

1. Start device login (internal: add `--env <prod|staging|sandbox>`):

```bash
python3 ../api/scripts/sum_api.py login --surface codex
```

2. Show the link to the user, then STOP — do not run anything else this turn. Read `verification_uri_complete` and `user_code` from the JSON and post them **copied character-for-character** (never retype or shorten the URL — one wrong character yields a "Link invalid or expired" page):

> Open this link and approve to connect Codex to Summation — it expires in 10 minutes.
> **<verification_uri_complete>**
> Verification code: **<user_code>**
>
> You'll approve in your browser; no password or secret is shared in this chat.

Do **not** run `login-poll` in the same turn as `login` — the user must see this link first. Do not print `device_code` or raw polling JSON.

3. Poll for approval — each `login-poll` checks for up to ~45s and returns on its own (it does not hang):

```bash
python3 ../api/scripts/sum_api.py login-poll
```

Act on `status`, looping until it resolves:

- `{"status":"approved", ...}`: approval succeeded. The helper stored `SUM_API_DEVICE_LOGIN_CREDENTIAL` in `~/.summation/summation-config` (mode `0600`). Continue.
- `{"status":"pending", ...}`: not approved yet — normal, not an error. Briefly tell the user you're still waiting, re-post the same link and code, then run `login-poll` again. Keep looping.
- `{"status":"denied"}`: the user rejected the browser approval. No credential was stored. Offer to start over.
- `{"status":"expired"}`: the approval link expired. No credential was stored. Offer to start over.

4. Register the Summation MCP server with Codex:

```bash
python3 ../api/scripts/sum_api.py mcp-connect --client codex
```

This writes the hosted MCP server (`https://mcp.summation.com/mcp`) into `~/.codex/config.toml` with the stored credential as a bearer header (mode `0600`). The credential moves process-to-process and must never appear in chat. Tell the user to start a new Codex thread (or restart Codex) to load the Summation tools.

5. Verify:

```bash
python3 ../api/scripts/sum_api.py doctor
python3 ../api/scripts/sum_api.py call GET /v1/me
```

6. Report the signed-in identity, whether the MCP server was registered, and `request_id` on any failure.

## Rules

- External (the default): production only — never prompt for an environment or tenant. Internal mode (`ADDISON_PLUGIN_INTERNAL=1`) unlocks `--env` selection among prod/staging/sandbox and tenant switching (sign out, switch org on the web app, sign in).
- Never print, log, or commit the device-login credential or any token.
- The helper stores temporary polling state locally after `login`; do not surface `device_code`, `interval`, or `expires_in` in chat.
- If a Summation MCP call later fails with an auth error, the stored bearer was likely revoked or expired: re-run this sign-in flow to mint a fresh credential and re-register the server.
