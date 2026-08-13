#!/usr/bin/env bash
# Assemble plugins/summation from skills/ + packaging/ (Agent Plugins 1.0.0 only).
set -euo pipefail
cd "$(dirname "$0")"
python3 packaging/build.py
echo "built Summation plugin"
