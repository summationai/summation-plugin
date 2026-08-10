#!/usr/bin/env bash
# Build dist/addison-plugin.zip for claude.ai org "Add plugins → Upload a file".
# Zip root = plugin root (.claude-plugin/plugin.json at top level).
set -euo pipefail
cd "$(dirname "$0")"
./build-claude.sh
mkdir -p dist
rm -f dist/addison-plugin.zip
if find plugins/addison-claude -name ".summation-config*" | grep -q .; then
  echo "refusing to pack: credential file inside plugins/addison-claude" >&2
  exit 1
fi
(cd plugins/addison-claude && zip -r ../../dist/addison-plugin.zip . -x "*.DS_Store" -x "*__pycache__*" -x "GENERATED.md")
echo "built dist/addison-plugin.zip"
