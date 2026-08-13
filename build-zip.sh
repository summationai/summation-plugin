#!/usr/bin/env bash
# Build dist/summation-plugin.zip for claude.ai org "Add plugins → Upload a file".
# Zip root = plugin root (.claude-plugin/plugin.json and plugin.json at top level).
set -euo pipefail
cd "$(dirname "$0")"
./build-plugins.sh
mkdir -p dist
rm -f dist/summation-plugin.zip dist/addison-plugin.zip
if find plugins/summation -name ".summation-config*" | grep -q .; then
  echo "refusing to pack: credential file inside plugins/summation" >&2
  exit 1
fi
(cd plugins/summation && zip -r ../../dist/summation-plugin.zip . -x "*.DS_Store" -x "*__pycache__*" -x "GENERATED.md")
echo "built dist/summation-plugin.zip"
