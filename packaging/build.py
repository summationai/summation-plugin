#!/usr/bin/env python3
"""Assemble the one portable plugin package at plugins/summation/.

Source of truth:
  skills/                         skill markdown
  assets/                         brand images
  packaging/plugin.json           Agent Plugins 1.0.0 manifest + version
  packaging/mcp.json              Agent Plugins MCP config
  packaging/com.anthropic.claude/ Claude hooks

The generated tree is spec-compliant (plugin.json, mcp.json, skills/) and still
carries today's Claude/Codex shims so marketplace installs keep working.
"""
from __future__ import annotations

import json
import pathlib
import re
import shutil
import sys
from urllib.parse import urlsplit

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKILLS = ROOT / "skills"
ASSETS = ROOT / "assets"
PACKAGING = ROOT / "packaging"
DST = ROOT / "plugins" / "summation"
CLAUDE_MARKET = ROOT / ".claude-plugin" / "marketplace.json"
CODEX_MARKET = ROOT / ".agents" / "plugins" / "marketplace.json"

REQUIRED_ASSETS = ("logo.png", "logo-dark.png", "icon.png")
SPEC_PLUGIN_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
SPEC_MCP_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json"
NAME_RE = re.compile(r"^(?!.*(?:--|\.\.))[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$")


def die(message: str) -> None:
    print(f"refusing to build: {message}", file=sys.stderr)
    raise SystemExit(1)


def write_json(path: pathlib.Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def copytree(src: pathlib.Path, dst: pathlib.Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", ".DS_Store", ".summation-config*"))


def refuse_secrets(root: pathlib.Path) -> None:
    if any(root.rglob(".summation-config*")):
        die(f"credential file inside {root.relative_to(ROOT)}")


def strip_skill_frontmatter(text: str, skill_name: str) -> str:
    """Keep only name + a single-line description (Codex requires a value)."""
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
        name = skill_name
    description = " ".join(description.split())
    if not description:
        die(f"skill {name!r}: empty description after frontmatter strip")
    desc_yaml = json.dumps(description, ensure_ascii=False)
    return f"---\nname: {name}\ndescription: {desc_yaml}\n---" + text[end + len("\n---") :]


def codex_text(text: str) -> str:
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


def write_codex_skills(src_skills: pathlib.Path, dst_skills: pathlib.Path) -> None:
    copytree(src_skills, dst_skills)
    for path in dst_skills.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix in {".md", ".html"}:
            text = path.read_text(encoding="utf-8")
            if path.name == "SKILL.md":
                text = strip_skill_frontmatter(text, path.parent.name)
            path.write_text(codex_text(text), encoding="utf-8")
        elif path.suffix == ".py":
            path.write_text(
                path.read_text(encoding="utf-8").replace("/summation:", "$summation-"),
                encoding="utf-8",
            )


def mcp_url(spec_mcp: dict) -> str:
    servers = spec_mcp.get("mcpServers") or {}
    summation = servers.get("summation") or {}
    url = summation.get("url") or ""
    if not url:
        die("packaging/mcp.json missing mcpServers.summation.url")
    return url


def validate_spec(plugin: dict, mcp: dict) -> None:
    if plugin.get("$schema") != SPEC_PLUGIN_SCHEMA:
        die("packaging/plugin.json $schema must be the Agent Plugins 1.0.0 plugin schema")
    name = plugin.get("name")
    if not isinstance(name, str) or not NAME_RE.match(name):
        die(f"invalid plugin name {name!r}")
    extra = set(plugin) - {
        "$schema",
        "name",
        "version",
        "description",
        "author",
        "homepage",
        "repository",
        "license",
        "keywords",
        "extensions",
    }
    if extra:
        die(f"plugin.json has non-portable fields: {sorted(extra)}")
    if mcp.get("$schema") != SPEC_MCP_SCHEMA:
        die("packaging/mcp.json $schema must be the Agent Plugins 1.0.0 MCP schema")
    if set(mcp) != {"$schema", "mcpServers"}:
        die("mcp.json may only contain $schema and mcpServers")
    servers = mcp.get("mcpServers")
    if not isinstance(servers, dict):
        die("mcp.json mcpServers must be an object")
    for key, cfg in servers.items():
        if not isinstance(cfg, dict) or cfg.get("type") != "streamable-http" or not cfg.get("url"):
            die(f"mcp server {key!r} must be streamable-http with a url")


def update_claude_marketplace(version: str, description: str) -> None:
    if CLAUDE_MARKET.exists():
        market = json.loads(CLAUDE_MARKET.read_text(encoding="utf-8"))
    else:
        market = {"name": "summationai", "owner": {"name": "Summation"}, "plugins": []}
    market["name"] = "summationai"
    plugins = market.setdefault("plugins", [])
    entry = {
        "name": "summation",
        "source": "./plugins/summation",
        "description": description,
        "version": version,
        "author": {"name": "Summation"},
        "category": "data",
    }
    for index, existing in enumerate(plugins):
        if isinstance(existing, dict) and existing.get("name") in {entry["name"], "addison"}:
            plugins[index] = entry
            break
    else:
        plugins.append(entry)
    write_json(CLAUDE_MARKET, market)


def update_codex_marketplace() -> None:
    if CODEX_MARKET.exists():
        market = json.loads(CODEX_MARKET.read_text(encoding="utf-8"))
    else:
        market = {"name": "summationai", "interface": {"displayName": "Summation"}, "plugins": []}
    market["name"] = "summationai"
    market.setdefault("interface", {"displayName": "Summation"})
    plugins = market.setdefault("plugins", [])
    entry = {
        "name": "summation",
        "source": {"source": "local", "path": "./plugins/summation"},
        "policy": {"installation": "AVAILABLE", "authentication": "ON_USE"},
        "category": "Data",
    }
    for index, existing in enumerate(plugins):
        if isinstance(existing, dict) and existing.get("name") in {entry["name"], "addison"}:
            plugins[index] = entry
            break
    else:
        plugins.append(entry)
    write_json(CODEX_MARKET, market)


def main() -> None:
    if not SKILLS.is_dir():
        die("missing skills/ (canonical skill source)")
    if not ASSETS.is_dir():
        die("missing assets/")
    for name in REQUIRED_ASSETS:
        if not (ASSETS / name).is_file():
            die(f"assets/ must include {name}")
    refuse_secrets(SKILLS)
    refuse_secrets(PACKAGING)

    plugin = json.loads((PACKAGING / "plugin.json").read_text(encoding="utf-8"))
    spec_mcp = json.loads((PACKAGING / "mcp.json").read_text(encoding="utf-8"))
    validate_spec(plugin, spec_mcp)
    version = plugin["version"]
    url = mcp_url(spec_mcp)
    origin = urlsplit(url)
    oauth_resource = f"{origin.scheme}://{origin.netloc}" if origin.scheme and origin.netloc else url

    if DST.exists():
        shutil.rmtree(DST)
    DST.mkdir(parents=True)

    copytree(SKILLS, DST / "skills")
    hooks_src = PACKAGING / "com.anthropic.claude" / "hooks"
    copytree(hooks_src, DST / "hooks")
    copytree(hooks_src, DST / "com.anthropic.claude" / "hooks")

    assets_dst = DST / "assets"
    assets_dst.mkdir()
    for name in REQUIRED_ASSETS:
        shutil.copy2(ASSETS / name, assets_dst / name)
    copytree(assets_dst, DST / "com.openai.codex" / "assets")

    write_json(DST / "plugin.json", plugin)
    write_json(DST / "mcp.json", spec_mcp)
    write_json(
        DST / ".mcp.json",
        {"summation": {"type": "http", "url": url}},
    )
    write_json(
        DST / ".claude-plugin" / "plugin.json",
        {
            "name": plugin["name"],
            "displayName": "Summation",
            "version": version,
            "description": (
                "Summation's AI data analyst in Claude Code: ask data questions, search the catalog, "
                "run bounded SQL, generate + validate reports, export PDF/DOCX/Markdown. MCP-native auth and tools."
            ),
            "author": {"name": "Summation"},
            "homepage": plugin["homepage"],
            "license": plugin["license"],
            "repository": plugin["repository"],
            "keywords": plugin.get("keywords", []),
        },
    )

    write_codex_skills(SKILLS, DST / "com.openai.codex" / "skills")
    write_json(
        DST / "com.openai.codex" / "mcp.json",
        {
            "mcpServers": {
                "summation": {
                    "type": "http",
                    "url": url,
                    "oauth_resource": oauth_resource,
                }
            }
        },
    )
    write_json(
        DST / ".codex-plugin" / "plugin.json",
        {
            "name": plugin["name"],
            "version": version,
            "description": (
                "Summation's AI data analyst, in Codex: ask data questions, search the catalog, "
                "run bounded SQL, generate and validate reports, and export artifacts."
            ),
            "author": {"name": "Summation", "url": "https://summation.com"},
            "homepage": plugin["homepage"],
            "repository": plugin["repository"],
            "license": plugin["license"],
            "keywords": sorted(set(plugin.get("keywords", []) + ["codex"])),
            "skills": "./com.openai.codex/skills/",
            "mcpServers": "./com.openai.codex/mcp.json",
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
        },
    )

    (DST / "GENERATED.md").write_text(
        "# Generated package\n\n"
        "Do **not** edit files under `plugins/summation` by hand.\n\n"
        "- Author skills in **`skills/`**.\n"
        "- Bump version in **`packaging/plugin.json`**.\n"
        "- MCP URL lives in **`packaging/mcp.json`**.\n"
        "- Claude hooks live in **`packaging/com.anthropic.claude/hooks/`**.\n"
        "- Run `./build-plugins.sh`.\n"
        "- CI fails if this tree drifts from source.\n",
        encoding="utf-8",
    )

    update_claude_marketplace(
        version,
        "Summation's AI data analyst in Claude Code: ask data questions, search the catalog, "
        "run bounded SQL, generate + validate reports. MCP-native.",
    )
    update_codex_marketplace()
    print(f"built {DST.relative_to(ROOT)} (version {version})")
    print("mcp:", url)


if __name__ == "__main__":
    main()
