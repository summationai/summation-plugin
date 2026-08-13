#!/usr/bin/env python3
"""Assemble the Agent Plugins 1.0.0 package at plugins/summation/.

Breaking: this tree is spec-only. No .claude-plugin, .codex-plugin, or .mcp.json.
"""
from __future__ import annotations

import json
import pathlib
import re
import shutil
import sys

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
FORBIDDEN_IN_PACKAGE = (".claude-plugin", ".codex-plugin", ".mcp.json")


def die(message: str) -> None:
    print(f"refusing to build: {message}", file=sys.stderr)
    raise SystemExit(1)


def write_json(path: pathlib.Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def copytree(src: pathlib.Path, dst: pathlib.Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(
        src,
        dst,
        ignore=shutil.ignore_patterns("__pycache__", ".DS_Store", ".summation-config*"),
    )


def refuse_secrets(root: pathlib.Path) -> None:
    if any(root.rglob(".summation-config*")):
        die(f"credential file inside {root.relative_to(ROOT)}")


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
        if isinstance(existing, dict) and existing.get("name") == entry["name"]:
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
        if isinstance(existing, dict) and existing.get("name") == entry["name"]:
            plugins[index] = entry
            break
    else:
        plugins.append(entry)
    write_json(CODEX_MARKET, market)


def assert_no_legacy_shims(root: pathlib.Path) -> None:
    for name in FORBIDDEN_IN_PACKAGE:
        if (root / name).exists():
            die(f"legacy shim {name} must not be in the generated package")


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

    if DST.exists():
        shutil.rmtree(DST)
    DST.mkdir(parents=True)

    copytree(SKILLS, DST / "skills")
    copytree(
        PACKAGING / "com.anthropic.claude" / "hooks",
        DST / "com.anthropic.claude" / "hooks",
    )

    assets_dst = DST / "com.openai.codex" / "assets"
    assets_dst.mkdir(parents=True)
    for name in REQUIRED_ASSETS:
        shutil.copy2(ASSETS / name, assets_dst / name)

    write_json(DST / "plugin.json", plugin)
    write_json(DST / "mcp.json", spec_mcp)

    (DST / "GENERATED.md").write_text(
        "# Generated package\n\n"
        "Do **not** edit files under `plugins/summation` by hand.\n\n"
        "This directory is an Agent Plugins 1.0.0 package. There is no\n"
        "`.claude-plugin`, `.codex-plugin`, or `.mcp.json`.\n\n"
        "- Author skills in **`skills/`**.\n"
        "- Bump version in **`packaging/plugin.json`**.\n"
        "- MCP URL lives in **`packaging/mcp.json`**.\n"
        "- Claude hooks live in **`packaging/com.anthropic.claude/hooks/`**.\n"
        "- Run `./build-plugins.sh`.\n"
        "- CI fails if this tree drifts from source.\n",
        encoding="utf-8",
    )

    assert_no_legacy_shims(DST)
    update_claude_marketplace(
        version,
        "Summation's AI data analyst: ask data questions, search the catalog, "
        "run bounded SQL, generate and validate reports. MCP-native.",
    )
    update_codex_marketplace()
    print(f"built {DST.relative_to(ROOT)} (version {version})")
    print("mcp:", url)


if __name__ == "__main__":
    main()
