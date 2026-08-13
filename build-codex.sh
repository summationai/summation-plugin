#!/usr/bin/env bash
# Assemble plugins/summation-codex from shared skills/ + Claude packaging (version, MCP URL).
# plugins/summation-codex is GENERATED — edit skills/ or this builder, never plugins/summation-codex.
#
# Shared source of truth: skills/
# Codex-only transforms:
#   - $summation- mention syntax
#   - .mcp.json → Codex shape ({"mcpServers": {...}, oauth_resource})
#   - claude mcp … → codex mcp …
#   - .codex-plugin/plugin.json + .agents/plugins/marketplace.json
set -euo pipefail
cd "$(dirname "$0")"

# Keep Claude skills in sync first (same canonical skills/).
./build-claude.sh

SKILLS=skills
CLAUDE=plugins/summation-claude
DST=plugins/summation-codex
MARKETPLACE=.agents/plugins/marketplace.json

if find "$SKILLS" -name ".summation-config*" | grep -q .; then
  echo "refusing to build: credential file inside $SKILLS" >&2
  exit 1
fi

rm -rf "$DST"
mkdir -p "$DST" "$(dirname "$MARKETPLACE")"
cp -R "$SKILLS" "$DST/skills"
cp "$CLAUDE/.mcp.json" "$DST/.mcp.json"
# Brand assets for Codex marketplace / composer (canonical: repo-root assets/)
if [[ -d assets ]]; then
  mkdir -p "$DST/assets"
  # logo.png, logo-dark.png, icon.png (composer)
  cp -f assets/logo.png assets/logo-dark.png assets/icon.png "$DST/assets/" 2>/dev/null || {
    echo "refusing to build: assets/ must include logo.png, logo-dark.png, icon.png" >&2
    exit 1
  }
fi
find "$DST" -name "__pycache__" -type d -prune -exec rm -rf {} + 2>/dev/null || true

python3 - "$CLAUDE" "$DST" "$MARKETPLACE" <<'PY'
import json
import pathlib
import re
import sys
from urllib.parse import urlsplit

claude = pathlib.Path(sys.argv[1])
dst = pathlib.Path(sys.argv[2])
marketplace_path = pathlib.Path(sys.argv[3])

src_manifest = json.loads((claude / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
version = src_manifest["version"]


def write_json(path: pathlib.Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def strip_skill_frontmatter(text: str) -> str:
    """Keep only name + description for Codex.

    Codex rejects skills whose frontmatter lacks a non-empty ``description``.
    Folded YAML (``description: >`` plus indented lines) used to be stripped to
    a bare ``description: >`` with no body — Codex then skipped the skill.
    Flatten multi-line descriptions to one line so the field always has a value.
    """
    if not text.startswith("---\n"):
        return text
    end = text.find("\n---", 4)
    if end == -1:
        return text
    lines = text[4:end].splitlines()
    name: str | None = None
    description = ""
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("name:"):
            name = line.split(":", 1)[1].strip().strip("\"'")
            i += 1
            continue
        if line.startswith("description:"):
            rest = line.split(":", 1)[1].strip()
            i += 1
            if rest in {">", "|", ">-", "|-", ">+", "|+"}:
                parts: list[str] = []
                while i < len(lines) and (lines[i].startswith(" ") or lines[i].startswith("\t")):
                    parts.append(lines[i].strip())
                    i += 1
                description = " ".join(parts)
            else:
                description = rest.strip("\"'")
                while i < len(lines) and (lines[i].startswith(" ") or lines[i].startswith("\t")):
                    description = f"{description} {lines[i].strip()}".strip()
                    i += 1
            continue
        i += 1
    if not name:
        return text
    description = " ".join(description.split())
    if not description:
        raise SystemExit(f"skill {name!r}: empty description after frontmatter strip")
    # Double-quote so colons / dashes in the blurb stay valid YAML.
    desc_yaml = json.dumps(description, ensure_ascii=False)
    return f"---\nname: {name}\ndescription: {desc_yaml}\n---" + text[end + len("\n---") :]


def codex_text(text: str) -> str:
    # Logout first so OAuth session clears while the server name still resolves.
    # Do not re-inject `|| true` — signout skill requires real failures to surface.
    text = re.sub(
        r"claude mcp remove -s user summation(?:\s+2>/dev/null\s*\|\|\s*true)?",
        "codex mcp logout summation\n"
        "codex mcp remove summation",
        text,
    )
    text = re.sub(
        r"claude mcp remove summation -s user(?:\s+2>/dev/null\s*\|\|\s*true)?",
        "codex mcp logout summation\n"
        "codex mcp remove summation",
        text,
    )
    text = re.sub(
        r"claude mcp add -s user --transport http summation '([^']+)'",
        r"codex mcp add summation --url '\1'",
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
    text = text.replace(
        "Prefer `/mcp` → Authenticate if the host shows that control.",
        "Prefer `codex mcp login summation` (or the host Authenticate control) if tools are not yet authed.",
    )
    text = text.replace(
        "Also clear auth / disconnect **summation** in `/mcp` if the host keeps a session after remove. Prefer the host’s “disconnect / re-authenticate” when available.",
        "Run `codex mcp logout summation` **before** remove so the OAuth session is cleared while the server name still resolves.",
    )
    for before, after in (
        ("/summation:", "$summation-"),
        ("Claude Desktop", "Codex"),
        ("Claude Code", "Codex"),
        ("Claude", "Codex"),
    ):
        text = text.replace(before, after)
    return text


def to_codex_mcp(payload: dict) -> dict:
    servers = payload.get("mcpServers", payload)
    out: dict[str, dict] = {}
    for name, cfg in servers.items():
        if not isinstance(cfg, dict):
            continue
        url = cfg.get("url") or ""
        entry: dict = {"type": cfg.get("type") or "http", "url": url}
        parts = urlsplit(url)
        if parts.scheme and parts.netloc:
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
        path.write_text(path.read_text(encoding="utf-8").replace("/summation:", "$summation-"), encoding="utf-8")

mcp_path = dst / ".mcp.json"
if mcp_path.exists():
    claude_mcp = json.loads(mcp_path.read_text(encoding="utf-8"))
    write_json(mcp_path, to_codex_mcp(claude_mcp))

# Marker so humans do not edit the generated tree.
(dst / "GENERATED.md").write_text(
    "# Generated package\n\n"
    "Do **not** edit files under `plugins/summation-codex` by hand.\n\n"
    "- Author skills in **`skills/`** (shared).\n"
    "- Run `./build-codex.sh` (also refreshes Claude’s `skills/` copy via `./build-claude.sh`).\n"
    "- CI fails if this tree drifts from source.\n",
    encoding="utf-8",
)

plugin_json = {
    "name": "summation",
    "version": version,
    "description": (
        "Summation's AI data analyst, in Codex: ask data questions, search the catalog, "
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
        "displayName": "Summation",
        "shortDescription": "Ask Summation data questions from Codex.",
        "longDescription": (
            "The Summation plugin brings the analyst into Codex for governed data questions, "
            "catalog discovery, SQL, reports, validation, and scheduling. Skills orchestrate the "
            "hosted Summation MCP server; auth is browser OAuth on first use (same product as Claude)."
        ),
        "developerName": "Summation",
        "category": "Data",
        "capabilities": ["Interactive", "Data analysis", "Reports", "MCP"],
        "websiteURL": "https://summation.com",
        "brandColor": "#2F6FEB",
        "composerIcon": "./assets/icon.png",
        "logo": "./assets/logo.png",
        "logoDark": "./assets/logo-dark.png",
        "defaultPrompt": [
            "Set up Summation.",
            "What data can Summation see?",
            "Generate a report from my data.",
        ],
    },
}
assets_dir = dst / "assets"
for rel in ("assets/icon.png", "assets/logo.png", "assets/logo-dark.png"):
    if not (dst / rel).is_file():
        raise SystemExit(f"missing brand asset {rel} — add files under repo assets/ and rebuild")
write_json(dst / ".codex-plugin" / "plugin.json", plugin_json)

entry = {
    "name": "summation",
    "source": {"source": "local", "path": "./plugins/summation-codex"},
    "policy": {"installation": "AVAILABLE", "authentication": "ON_USE"},
    "category": "Data",
}
if marketplace_path.exists():
    marketplace = json.loads(marketplace_path.read_text(encoding="utf-8"))
else:
    marketplace = {"name": "summationai", "interface": {"displayName": "Summation"}, "plugins": []}
marketplace["name"] = "summationai"
marketplace.setdefault("interface", {"displayName": "Summation"})
plugins = marketplace.setdefault("plugins", [])
for index, existing in enumerate(plugins):
    if isinstance(existing, dict) and existing.get("name") in {entry["name"], "addison"}:
        plugins[index] = entry
        break
else:
    plugins.append(entry)
write_json(marketplace_path, marketplace)
PY

VERSION=$(python3 -c "import json; print(json.load(open('$DST/.codex-plugin/plugin.json'))['version'])")
echo "built $DST (version $VERSION)"
echo "mcp:" && cat "$DST/.mcp.json"
