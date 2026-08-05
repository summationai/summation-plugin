#!/usr/bin/env bash
# Assemble plugins/addison-codex from plugins/addison-claude (the source of truth).
# plugins/addison-codex is GENERATED — edit plugins/addison-claude or this builder, never plugins/addison-codex.
# Codex differs from the Claude edition only by: $addison- mention syntax, a signin/signout
# auth overlay (device-login + `mcp-connect --client codex`), and the Codex manifest.
set -euo pipefail
cd "$(dirname "$0")"

SRC=plugins/addison-claude
DST=plugins/addison-codex
MARKETPLACE=.agents/plugins/marketplace.json

if find "$SRC" -name ".summation-config*" | grep -q .; then
  echo "refusing to build: credential file inside $SRC" >&2
  exit 1
fi

rm -rf "$DST"
mkdir -p "$(dirname "$DST")" "$(dirname "$MARKETPLACE")"
cp -R "$SRC" "$DST"
rm -rf "$DST/.claude-plugin"   # Codex uses .codex-plugin/plugin.json (written below)
rm -rf "$DST/hooks"            # the version-check hook is Claude-specific (`claude plugin update`)
find "$DST" -name "__pycache__" -type d -prune -exec rm -rf {} +

python3 - "$SRC" "$DST" "$MARKETPLACE" <<'PY'
import json
import pathlib
import sys

src = pathlib.Path(sys.argv[1])
dst = pathlib.Path(sys.argv[2])
marketplace_path = pathlib.Path(sys.argv[3])

src_manifest = json.loads((src / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
version = src_manifest["version"]


def write_json(path: pathlib.Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def strip_skill_frontmatter(text: str) -> str:
    if not text.startswith("---\n"):
        return text
    end = text.find("\n---", 4)
    if end == -1:
        return text
    kept = [
        line for line in text[4:end].splitlines()
        if line.startswith("name:") or line.startswith("description:")
    ]
    return "---\n" + "\n".join(kept) + "\n---" + text[end + len("\n---"):]


def codex_text(text: str) -> str:
    for before, after in (
        ("/addison:", "$addison-"),
        ("Claude Desktop", "Codex"),
        ("Claude Code", "Codex"),
        ("Claude", "Codex"),
    ):
        text = text.replace(before, after)
    return text


for path in dst.rglob("*"):
    if not path.is_file():
        continue
    if path.suffix in {".md", ".html"}:
        text = path.read_text(encoding="utf-8")
        if path.name == "SKILL.md":
            text = strip_skill_frontmatter(text)
        path.write_text(codex_text(text), encoding="utf-8")
    elif path.suffix == ".py":
        # Only the mention syntax changes in the helper; Claude/Codex logic is shared.
        path.write_text(path.read_text(encoding="utf-8").replace("/addison:", "$addison-"), encoding="utf-8")


signin_skill = """---
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
"""

signout_skill = """---
name: signout
description: Disconnect Codex from Summation — revoke the stored device-login session, remove the local credential, and deregister the Summation MCP server. Use to disconnect, sign in as a different Summation user, or clear a stale session.
---

# Addison Sign-out

Revoke the stored device-login session, remove `SUM_API_DEVICE_LOGIN_CREDENTIAL`, and deregister the Summation MCP server from Codex. The helper lives in the sibling `api` skill: `../api/scripts/sum_api.py`.

## Flow

1. Revoke the session, then deregister the server:

```bash
python3 ../api/scripts/sum_api.py logout
python3 ../api/scripts/sum_api.py mcp-disconnect --client codex
```

2. Interpret the results:

- `logout` -> `{"status":"logged_out", ...}` — the session was revoked and the credential removed. `{"status":"already_logged_out", ...}` — nothing was present.
- `mcp-disconnect --client codex` -> `{"status":"disconnected"}` — the server block (and its bearer header) was removed from `~/.codex/config.toml`. `{"status":"not_registered"}` — nothing was present.

## Rules

- Always run both: a revoked session must not leave a stale bearer header in Codex config.
- Report both outcomes to the user.
"""

(dst / "skills" / "signin" / "SKILL.md").write_text(signin_skill, encoding="utf-8")
(dst / "skills" / "signout" / "SKILL.md").write_text(signout_skill, encoding="utf-8")

plugin_json = {
    "name": "addison",
    "version": version,
    "description": "Addison, Summation's AI data analyst, in Codex: ask data questions, search the catalog, run bounded SQL, generate and validate reports, and export artifacts.",
    "author": {"name": "Summation", "url": "https://summation.com"},
    "homepage": "https://summation.com",
    "repository": src_manifest["repository"],
    "license": src_manifest.get("license", "MIT"),
    "keywords": sorted(set(src_manifest.get("keywords", []) + ["codex", "mcp"])),
    "skills": "./skills/",
    "interface": {
        "displayName": "Addison",
        "shortDescription": "Ask Addison data questions from Codex.",
        "longDescription": "Addison brings Summation's AI data analyst into Codex for governed data questions, catalog discovery, SQL, reports, validation, and scheduling. One browser approval stores a local credential and connects the hosted Summation MCP server.",
        "developerName": "Summation",
        "category": "Data",
        "capabilities": ["Interactive", "Data analysis", "Reports", "MCP"],
        "websiteURL": "https://summation.com",
        "brandColor": "#2F6FEB",
        "defaultPrompt": [
            "Set up Addison for Summation.",
            "What data can Addison see?",
            "Generate a report from my data.",
        ],
    },
}
write_json(dst / ".codex-plugin" / "plugin.json", plugin_json)

entry = {
    "name": "addison",
    "source": {"source": "local", "path": "./plugins/addison-codex"},
    "policy": {"installation": "AVAILABLE", "authentication": "ON_USE"},
    "category": "Data",
}
if marketplace_path.exists():
    marketplace = json.loads(marketplace_path.read_text(encoding="utf-8"))
else:
    marketplace = {"name": "summation", "interface": {"displayName": "Summation"}, "plugins": []}
marketplace.setdefault("name", "summation")
marketplace.setdefault("interface", {"displayName": "Summation"})
plugins = marketplace.setdefault("plugins", [])
for index, existing in enumerate(plugins):
    if isinstance(existing, dict) and existing.get("name") == entry["name"]:
        plugins[index] = entry
        break
else:
    plugins.append(entry)
write_json(marketplace_path, marketplace)
PY

VERSION=$(python3 -c "import json; print(json.load(open('$DST/.codex-plugin/plugin.json'))['version'])")
echo "built $DST (version $VERSION)"
