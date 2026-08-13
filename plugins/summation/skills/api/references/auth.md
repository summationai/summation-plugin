# Auth Reference (MCP-native)

The host MCP client authenticates to the hosted Summation MCP server. The plugin does not mint or store customer credentials for the happy path.

## Two experiences

| | External (default) | Internal |
|---|---|---|
| Gate | (none) | Shell: `SUMMATION_PLUGIN_INTERNAL=1` (or `ADDISON_PLUGIN_INTERNAL`) when launching the host CLI |
| Environments | One — plugin `mcp.json` URL | User picks **prod** / **staging** / **sandbox** at sign-in |
| Tenant | Org approved in browser | Same; skill tells user to switch org on the web app first if needed |
| MCP URL | Bundled headerless entry | User-scope headerless `summation` pointed at the chosen env’s allowlisted URL |
| Skill prompts | Never ask env or tenant | Ask env; explain tenant binding |

Detect mode in skills:

```bash
printf '%s' "${SUMMATION_PLUGIN_INTERNAL:-${ADDISON_PLUGIN_INTERNAL:-}}"
```

## Allowlisted MCP URLs only

| Env | URL |
|---|---|
| prod | `https://mcp.summation.com/mcp` |
| staging | `https://staging-mcp.summation.com/mcp` |
| sandbox | `https://sandbox-mcp.summation.com/mcp` |

Never accept free-form hosts. Internal sign-in re-points with:

```bash
# Claude Code:
claude mcp add -s user --transport http summation 'https://…'
# Codex:
codex mcp add summation --url 'https://…'
```

Do **not** pass `--header`, an `Authorization` header, or any bearer token — the host’s OAuth flow owns the credential.

## Happy path (both)

1. Plugin loads headerless `mcp.json` (default env for external).
2. First tool call / explicit authenticate → MCP OAuth → browser → host stores token.
3. Tools run; identity/tenant from server-side claims.

**Default:** bundled `mcp.json` points at production (`https://mcp.summation.com/mcp`).

## Sign-in / sign-out

| Action | Skill |
|---|---|
| Connect | `signin` (mode-aware) |
| Disconnect / switch env or tenant | `signout` then `signin` |
| Diagnose | `diagnose` (reports mode + env + org) |

## What skills must not do

- Device-login poll as primary auth
- Writing `sm_dls_…` into `~/.summation/*` for host sessions
- Registering MCP with an `Authorization` header (for example `--header Authorization: …`)
- Asking for tokens in chat
- Offering free-form base URLs

## Legacy bridge

Old user-scope entries that inject an `Authorization` header (device-login `sm_dls_…` style) fight OAuth:

```bash
# Claude Code:
claude mcp remove -s user summation
# Codex:
codex mcp logout summation
codex mcp remove summation
```

Then the `signin` skill.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Tools missing | Enable summation; restart |
| 401 | the `signin` skill |
| Wrong env (internal) | Sign out; sign in; pick env again |
| Wrong tenant | Switch org on web app; sign out; sign in |
| Stale `Authorization` header on the MCP entry | Remove user-scope override; re-auth headerless |
