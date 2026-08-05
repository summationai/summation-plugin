# Auth Reference

The skill must use public `sum-api` authentication only. **External** (the default) is production-only: every request is pinned to `https://api.summation.com`, device-login only, no M2M. **Internal** (`ADDISON_PLUGIN_INTERNAL=1`) additionally allows environment selection (`--env prod|staging|sandbox`, a fixed Summation allowlist — never a free-form host), M2M credentials (`SUM_API_CLIENT_ID` / `SUM_API_CLIENT_SECRET` / `SUM_API_M2M_SCOPE`), and named tenant profiles; its config lives in `~/.summation/summation-config-internal`. Either way the credential can only ever reach an allowlisted Summation host.

## Supported Runtime Inputs

Device-login credential (stored by the `signin` flow):

```bash
SUM_API_DEVICE_LOGIN_CREDENTIAL=sm_dls_...
```

Bearer token (honored if already present):

```bash
SUM_API_ACCESS_TOKEN=...
```

Local config file:

```text
~/.summation/summation-config
```

The file uses environment-style lines:

```bash
SUM_API_DEVICE_LOGIN_CREDENTIAL=sm_dls_...
```

Set `SUM_API_CONFIG_FILE` or `SUMMATION_CONFIG` to point the helper at a specific config file.

The helper reads settings in this order:

1. Environment variables.
2. `SUM_API_CONFIG_FILE`.
3. Current directory `.summation-config`.
4. `~/.summation/summation-config` (canonical).
5. Installed skill directory `.summation-config` (legacy).
6. Home directory `.summation-config` (legacy).

A config found only in a legacy location is copied to `~/.summation/summation-config` on first use; the legacy file is left in place and the canonical path wins afterward.

Use file mode `0600` for files that contain secrets.

Base URL overrides (`SUM_API_BASE_URL`, `--base-url`) are refused unless they equal the production URL — the helper exits with a pin error rather than silently ignoring them. Sandbox/staging/per-tenant environments are an internal-edition capability.

## Auth Precedence

The helper resolves auth in this order:

1. `SUM_API_DEVICE_LOGIN_CREDENTIAL`
2. `SUM_API_ACCESS_TOKEN`

With neither present, authenticated commands exit with "Not signed in to Summation. Run /addison:signin to connect."

## Device Login Flow

Device login is the only interactive auth path.

Use the sibling `signin` skill for the step-by-step interactive flow. The helper starts login with `login`, stores temporary local polling state (`0600`), completes approval with `login-poll`, registers the hosted MCP server with `mcp-connect`, and revokes the device-login session plus removes the local credential with `logout` (pair with `mcp-disconnect`).

On approval, the helper stores `SUM_API_DEVICE_LOGIN_CREDENTIAL` in `~/.summation/summation-config`. Do not print or quote `device_code` in chat; the helper keeps it only in temporary local polling state until `login-poll` finishes.

## MCP Registration

`mcp-connect` registers `https://mcp.summation.com/mcp` with Claude Code (user scope), passing the stored credential as a bearer header via subprocess argv — never through chat, stdout, or a shell string. `mcp-disconnect` removes the registration. A revoked/expired credential surfaces as MCP auth errors; re-run the login flow to fix.

## Identity Rules

- The service principal identity is resolved by `sum-api` and auth-service.
- Organization identity must come from trusted token claims and auth-service resolution.
- Do not accept caller-provided `x-org-id`, `x-user-id`, `x-tenant-id`, or similar headers as trusted identity.
- If an operation targets an org or project, verify it is consistent with the authenticated principal by relying on the API response or error.

## Troubleshooting

- `401` usually means missing, expired, or invalid credentials.
- `403` usually means the token is valid but the principal lacks permission.
- `404` can mean the resource does not exist or is not visible to the principal.
- `429` means retry with jitter and respect any retry headers.
- On macOS, `certificate verify failed` usually means Python cannot find a CA bundle. Set `SSL_CERT_FILE` to a CA bundle path or install `certifi` in the Python environment running the skill helper.
