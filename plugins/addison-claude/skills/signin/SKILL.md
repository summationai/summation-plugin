---
name: signin
description: Sign in to Summation. Use when the user needs to connect Addison, fix credentials, or when any Summation call fails with 401/403 and no valid config exists.
---

# Addison Login

One browser sign-in connects everything: the sum-api credential AND the hosted Summation MCP server. The helper is the sibling `api` skill: `<plugin>/skills/api/scripts/sum_api.py` (resolve relative to this skill's base directory: `../api/scripts/sum_api.py`).

**The one rule that matters:** the user's only job is to open a link in their browser and approve. That link must appear in a message *you write to the user* — never left buried in command output — and you must show it **before** you poll.

## 0. Detect mode (do this first)

```bash
python3 ../api/scripts/sum_api.py mode
```

- `"internal": false` → **production only.** There is exactly one environment and one tenant — do **not** ask the user about environments or tenants. Skip to step 1 with no `--env`.
- `"internal": true` → internal Summation user. Ask which environment they want from the returned `environments` list (prod / staging / sandbox) and pass it as `--env` in step 1. See "Internal notes" for tenant behavior.

## 1. Mint the approval link

```bash
python3 ../api/scripts/sum_api.py login --surface <claude-code|claude-desktop>
# internal only: add --env <prod|staging|sandbox>
```

Always pass `--surface`: `claude-code` in Claude Code, `claude-desktop` in Claude Desktop. Do not rely on a helper default.

## 2. Show the link — then STOP, do not run anything else this turn

Read `verification_uri_complete` and `user_code` from the JSON and post them **copied character-for-character** (never retype, shorten, or reformat the URL — one wrong character yields a "Link invalid or expired" page):

> **Open this link in your browser and approve to connect Claude to Summation** — it expires in 10 minutes.
>
> 👉 <verification_uri_complete>
>
> Verification code: **<user_code>**
>
> You approve in the browser; no password or secret is shared in this chat.

Do **not** run `login-poll` in the same turn as `login` — the user must first see this link. Show only `verification_uri_complete` and `user_code`; never print `device_code` or raw polling JSON, and never ask the user for a password, token, or secret in chat.

## 3. Poll for approval (loop until it resolves)

Each `login-poll` checks for up to ~45s and returns on its own — it does not hang the turn:

```bash
python3 ../api/scripts/sum_api.py login-poll
```

Act on `status`:

- `approved` — done. The credential was stored locally (mode `0600`). Go to step 4.
- `pending` — not approved yet; this is normal, not an error. Briefly tell the user you're still waiting, **re-post the same link and code from step 2**, then run `login-poll` again. Keep looping.
- `denied` — the user rejected it in the browser. No credential stored. Offer to start over from step 1.
- `expired` — the 10-minute link lapsed. No credential stored. Offer to start over from step 1.

## 4. Connect the Summation MCP server (Claude Code only; skip on Claude Desktop)

```bash
python3 ../api/scripts/sum_api.py mcp-connect
```

Registers the hosted MCP server for the signed-in environment with the stored credential as a bearer header — passed process-to-process, never in chat. Tell the user to restart Claude Code (or run `/mcp`) to load the Summation tools.

## 5. Verify

```bash
python3 ../api/scripts/sum_api.py doctor
python3 ../api/scripts/sum_api.py call GET /v1/me
```

## 6. Report

Report the signed-in identity, the environment (internal only), whether the MCP server was registered, and `request_id` on any failure.

## Internal notes (only when `mode` reports `"internal": true`)

- **Environment** is chosen with `--env prod|staging|sandbox` at login and pinned; the MCP server and every call follow it. There is no free-form URL — only these three Summation environments.
- **Tenant** binds to the org the user approves in on the web app; it is not selected in the plugin. To connect to a different tenant, the user switches org on the Summation web app first, then re-signs in.
- **Env and tenant are pinned at login. To change either, sign out and sign in again.**
- If device login is unavailable and the user already has machine credentials, `configure` (M2M) is available in internal mode: `configure --env <env> --client-id <ID> --client-secret <SECRET> [--profile <NAME> --activate]`.

## Logout

Revoke the device-login session, remove the local credential, and deregister the MCP server:

```bash
python3 ../api/scripts/sum_api.py logout
python3 ../api/scripts/sum_api.py mcp-disconnect
```

Always run both — `mcp-disconnect` removes the bearer header that `mcp-connect` stored in the Claude Code MCP registration.

## Rules

- External (the default): production only — never prompt for an environment or tenant.
- Never print, log, or commit the device-login credential or any token.
- The helper stores temporary polling state locally after `login`; do not surface `device_code`, `interval`, or `expires_in` in chat.
- If a Summation MCP call later fails with an auth error, the stored bearer was likely revoked or expired: re-run this flow to mint a fresh credential and re-register the server.
