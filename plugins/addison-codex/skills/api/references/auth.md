# Auth Reference (MCP-native)

Codex authenticates to the hosted Summation MCP server. The plugin does not mint or store customer credentials for the happy path.

## Two experiences

| | External (default) | Internal |
|---|---|---|
| Gate | (none) | Shell: `ADDISON_PLUGIN_INTERNAL=1` (or `true` / `yes` / `on`) when launching Codex |
| Environments | One — plugin `.mcp.json` URL | User picks **prod** / **staging** / **sandbox** at sign-in |
| Tenant | Org approved in browser | Same; skill tells user to switch org on the web app first if needed |
| MCP URL | Bundled headerless entry | User-scope headerless `summation` pointed at the chosen env’s allowlisted URL |
| Skill prompts | Never ask env or tenant | Ask env; explain tenant binding |

Detect mode in skills:

```bash
printf '%s' "${ADDISON_PLUGIN_INTERNAL:-}"
```

## Allowlisted MCP URLs only

| Env | URL |
|---|---|
| prod | `https://mcp.summation.com/mcp` |
| staging | `https://staging-mcp.summation.com/mcp` |
| sandbox | `https://sandbox-mcp.summation.com/mcp` |

Never accept free-form hosts. Internal sign-in re-points with:

```bash
claude mcp add --transport http summation 'https://…' -s user
```

No `--header`, no Bearer injection.

## Happy path (both)

1. Plugin loads headerless `.mcp.json` (default env for external).
2. First tool call / explicit authenticate → MCP OAuth → browser → Codex stores token.
3. Tools run; identity/tenant from server-side claims.

**Dogfood:** bundled default is sandbox until prod OAuth is deployed, then flip `.mcp.json` to prod.

## Sign-in / sign-out

| Action | Skill |
|---|---|
| Connect | `signin` (mode-aware) |
| Disconnect / switch env or tenant | `signout` then `signin` |
| Diagnose | `diagnose` (reports mode + env + org) |

## What skills must not do

- Device-login poll as primary auth
- Writing `sm_dls_…` into `~/.summation/*` for Codex sessions
- `claude mcp add … --header Authorization: …`
- Asking for tokens in chat
- Offering free-form base URLs

## Legacy bridge

Old user-scope entries with `Authorization: Bearer sm_dls_…` fight OAuth:

```bash
claude mcp remove summation -s user
```

Then `$addison-signin`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Tools missing | Enable addison; restart |
| 401 | `$addison-signin` |
| Wrong env (internal) | Sign out; sign in; pick env again |
| Wrong tenant | Switch org on web app; sign out; sign in |
| Stale Bearer header | Remove user-scope header entry |
