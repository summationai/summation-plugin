# Generated package

Do **not** edit files under `plugins/summation` by hand.

This directory is an Agent Plugins 1.0.0 package. There is no
`.claude-plugin`, `.codex-plugin`, or `.mcp.json`.

- Author skills in **`skills/`**.
- Bump version in **`packaging/plugin.json`**.
- MCP URL lives in **`packaging/mcp.json`**.
- Claude hooks live in **`packaging/com.anthropic.claude/hooks/`** (copied to `hooks/` for Claude SessionStart discovery).
- Run `./build-plugins.sh`.
- CI fails if this tree drifts from source.
