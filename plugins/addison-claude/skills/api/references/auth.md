# Auth Reference (MCP-native)

Claude Code authenticates to the hosted Summation MCP server. The plugin does not mint or store customer credentials for the happy path.

## Happy path

1. Plugin loads `.mcp.json` with a **headerless** HTTP MCP entry:

   ```json
   {
     "summation": {
       "type": "http",
       "url": "https://sandbox-mcp.summation.com/mcp"
     }
   }
   ```

2. First tool call (or explicit authenticate) triggers MCP OAuth discovery:
   - `401` + `WWW-Authenticate` → protected-resource metadata
   - `authorization_servers` → AS metadata (register / authorize / token)
   - Browser opens Summation activate / SSO
   - Claude stores the bearer and retries

3. MCP tools run with that bearer. Identity/tenant come from the token claims server-side.

**Dogfood:** sandbox MCP URL above. **Production:** flip URL to `https://mcp.summation.com/mcp` once prod OAuth is deployed (same shape, no headers).

## What skills must not do

- Device-login poll loops (`login` / `login-poll`) as primary auth
- Writing `SUM_API_DEVICE_LOGIN_CREDENTIAL` into `~/.summation/*` for Claude sessions
- `claude mcp add … --header Authorization: Bearer …` (fights headerless plugin config)
- Asking the user to paste tokens, client secrets, or device codes into chat

## Sign-in / sign-out

| Action | Skill | Mechanism |
|---|---|---|
| Connect | `signin` | `whoami`; if needed, host browser auth; re-check `whoami` |
| Disconnect | `signout` | Host MCP remove / re-auth clear for `summation` |
| Diagnose | `diagnose` | `whoami` + environment MCP tools |

## Legacy bridge (remove if present)

Older installs may still have a **user-scope** `summation` entry with an `Authorization: Bearer sm_dls_…` header from the old `mcp-connect` helper. That bypasses OAuth and can go stale independently of Claude’s token store.

```bash
claude mcp get summation
# if Headers include Authorization → remove the override:
claude mcp remove summation -s user
```

Then reload and use `/addison:signin`.

## Identity rules

- Org/user/tenant come from the authenticated principal on the server.
- Do not accept caller-provided `x-org-id`, `x-user-id`, or similar as trusted identity.
- Switching org: change active org on the Summation web app, then re-authenticate MCP.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Tools missing | Plugin not enabled / MCP not loaded | Enable addison; restart; check `/mcp` |
| 401 on tools | Session expired or never auth’d | `/addison:signin` |
| 403 | Valid user, missing role/scope | Different org or admin grant |
| Auth works on webapp, not MCP | Stale header override | Remove user-scope header entry |
| Sandbox vs prod confusion | Wrong MCP URL in `.mcp.json` | Match URL to intended environment |
