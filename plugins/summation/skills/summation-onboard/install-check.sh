#!/bin/sh
# Read-only setup check for the grade path. Reports what will run; changes nothing.
# Usage: sh ~/.summation-onboard/install-check.sh --input <report-file>
set -eu

INPUT=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --input) INPUT="$2"; shift 2 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done
[ -n "$INPUT" ] && [ -e "$INPUT" ] || { echo "usage: install-check.sh --input <report-file>"; exit 2; }

SUFFIX="$(printf '%s' "${INPUT##*.}" | tr '[:upper:]' '[:lower:]')"
echo "Grade setup check (read-only)"
echo "Report: $INPUT (.$SUFFIX)"
case "$SUFFIX" in
  html|htm) echo "  document checks: deterministic claim-ledger checks (full coverage for HTML)" ;;
  md|markdown|txt|csv) echo "  document checks: text adapter + agentic scan (stated in the artifact)" ;;
  xlsx|pptx|docx) command -v officecli >/dev/null 2>&1 || echo "  MISSING: officecli (brew install) is needed for .$SUFFIX" ;;
  pdf) command -v pdftotext >/dev/null 2>&1 || echo "  MISSING: poppler (brew install) is needed for .pdf" ;;
  *) echo "  unsupported report format: .$SUFFIX"; exit 1 ;;
esac
command -v summation-flow >/dev/null 2>&1 \
  && echo "  summation-flow: $(summation-flow --version 2>/dev/null || echo present)" \
  || echo "  MISSING: summation-flow (rerun the toolkit install)"
command -v claude >/dev/null 2>&1 \
  && echo "  claude: $(claude --version 2>/dev/null | head -1)" \
  || echo "  MISSING: Claude Code 2.x is needed for the semantic review stage"
echo "Will write: ./grade-out/grade-summary.json and ./grade-out/grade-artifact.html"
echo "Will read: the report and any evidence files beside it. Nothing else. No uploads."
