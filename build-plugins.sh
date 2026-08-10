#!/usr/bin/env bash
# Build both plugin packages from the shared skills/ tree.
set -euo pipefail
cd "$(dirname "$0")"
./build-claude.sh
./build-codex.sh
echo "built Claude + Codex plugins"
