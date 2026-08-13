#!/usr/bin/env bash
# Assemble plugins/summation-claude skills from the shared skills/ tree (source of truth).
# Edit skills/ — never hand-edit plugins/summation-claude/skills (generated copy).
set -euo pipefail
cd "$(dirname "$0")"

SKILLS=skills
DST=plugins/summation-claude

if [[ ! -d "$SKILLS" ]]; then
  echo "refusing to build: missing $SKILLS/ (canonical skill source)" >&2
  exit 1
fi
if find "$SKILLS" -name ".summation-config*" | grep -q .; then
  echo "refusing to build: credential file inside $SKILLS" >&2
  exit 1
fi

rm -rf "$DST/skills"
cp -R "$SKILLS" "$DST/skills"
find "$DST/skills" -name "__pycache__" -type d -prune -exec rm -rf {} + 2>/dev/null || true

echo "built $DST/skills from $SKILLS/"
