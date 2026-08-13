#!/usr/bin/env bash
# Compatibility wrapper — there is one package now.
set -euo pipefail
cd "$(dirname "$0")"
./build-plugins.sh
