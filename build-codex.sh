#!/usr/bin/env bash
# Assemble plugins/addison-codex from plugins/addison-claude (the source of truth).
# plugins/addison-codex is GENERATED — edit plugins/addison-claude or this builder, never plugins/addison-codex.
#
# Shared: skills, .mcp.json URL, auth model (headerless OAuth), external vs internal.
# Codex-only transforms:
#   - $addison- mention syntax
#   - .mcp.json → Codex shape ({"mcpServers": {...}, oauth_resource})
#   - claude mcp … → codex mcp …
#   - .codex-plugin/plugin.json + .agents/plugins/marketplace.json
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
rm -rf "$DST/hooks"            # version-check hook is Claude-specific
find "$DST" -name "__pycache__" -type d -prune -exec rm -rf {} +

python3 - "$SRC" "$DST" "$MARKETPLACE" <<'PY'
import json
import pathlib
import re
import sys
from urllib.parse import urlsplit

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
    # Host MCP CLI first (before generic Claude → Codex).
    text = re.sub(
        r"claude mcp remove summation -s user(?:\s+2>/dev/null\s*\|\|\s*true)?",
        "codex mcp remove summation 2>/dev/null || true",
        text,
    )
    text = re.sub(
        r"claude mcp add --transport http summation '([^']+)' -s user",
        r"codex mcp add summation --url '\1'",
        text,
    )
    text = text.replace("claude mcp get summation", "codex mcp get summation")
    text = text.replace("claude mcp list", "codex mcp list")
    text = text.replace("claude mcp remove", "codex mcp remove")
    text = text.replace("claude mcp add", "codex mcp add")
    # Prefer codex's OAuth login helper where we mention host authenticate UI.
    text = text.replace(
        "Prefer `/mcp` → Authenticate if the host shows that control.",
        "Prefer `codex mcp login summation` (or the host Authenticate control) if tools are not yet authed.",
    )
    text = text.replace(
        "Also clear auth / disconnect **summation** in `/mcp` if the host keeps a session after remove.",
        "Also run `codex mcp logout summation` if a session remains after remove.",
    )
    for before, after in (
        ("/addison:", "$addison-"),
        ("Claude Desktop", "Codex"),
        ("Claude Code", "Codex"),
        ("Claude", "Codex"),
    ):
        text = text.replace(before, after)
    return text


def to_codex_mcp(payload: dict) -> dict:
    """Claude ships flat {name: {type,url}}; Codex wants {mcpServers: {name: {…, oauth_resource}}}."""
    servers = payload.get("mcpServers", payload)
    out: dict[str, dict] = {}
    for name, cfg in servers.items():
        if not isinstance(cfg, dict):
            continue
        url = cfg.get("url") or ""
        entry: dict = {"type": cfg.get("type") or "http", "url": url}
        parts = urlsplit(url)
        if parts.scheme and parts.netloc:
            # PRM resource id is origin (no /mcp path), matching sum-api-mcp RESOURCE_URL.
            entry["oauth_resource"] = f"{parts.scheme}://{parts.netloc}"
        out[name] = entry
    return {"mcpServers": out}


for path in dst.rglob("*"):
    if not path.is_file():
        continue
    if path.suffix in {".md", ".html"}:
        text = path.read_text(encoding="utf-8")
        if path.name == "SKILL.md":
            text = strip_skill_frontmatter(text)
        path.write_text(codex_text(text), encoding="utf-8")
    elif path.suffix == ".py":
        path.write_text(path.read_text(encoding="utf-8").replace("/addison:", "$addison-"), encoding="utf-8")

# Rewrite .mcp.json into Codex plugin shape (Linear/Notion style).
mcp_path = dst / ".mcp.json"
if mcp_path.exists():
    claude_mcp = json.loads(mcp_path.read_text(encoding="utf-8"))
    write_json(mcp_path, to_codex_mcp(claude_mcp))

plugin_json = {
    "name": "addison",
    "version": version,
    "description": (
        "Addison, Summation's AI data analyst, in Codex: ask data questions, search the catalog, "
        "run bounded SQL, generate and validate reports, and export artifacts."
    ),
    "author": {"name": "Summation", "url": "https://summation.com"},
    "homepage": "https://summation.com",
    "repository": src_manifest["repository"],
    "license": src_manifest.get("license", "MIT"),
    "keywords": sorted(set(src_manifest.get("keywords", []) + ["codex", "mcp"])),
    "skills": "./skills/",
    "mcpServers": "./.mcp.json",
    "interface": {
        "displayName": "Addison",
        "shortDescription": "Ask Addison data questions from Codex.",
        "longDescription": (
            "Addison brings Summation's AI data analyst into Codex for governed data questions, "
            "catalog discovery, SQL, reports, validation, and scheduling. Skills orchestrate the "
            "hosted Summation MCP server; auth is browser OAuth on first use (same product as Claude)."
        ),
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
echo "mcp:" && cat "$DST/.mcp.json"
