#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
set -euo pipefail

report="$(mktemp)"
trap 'rm -f "$report"' EXIT
chmod 600 "$report"

gitleaks git --no-banner --redact=100 --report-format=json --report-path="$report" >/dev/null
: >"$report"
gitleaks dir . --no-banner --redact=100 --report-format=json --report-path="$report" >/dev/null

scan_trufflehog() {
  set +e
  trufflehog "$@" --json --no-update --no-verification --results=unverified --fail --fail-on-scan-errors >"$report" 2>/dev/null
  scan_code=$?
  set -e
  if [[ "$scan_code" -ne 0 && "$scan_code" -ne 183 ]]; then
    echo "TruffleHog scan failed before completing." >&2
    exit "$scan_code"
  fi
  if [[ "$scan_code" -eq 183 ]]; then
    echo "TruffleHog reported suspicious material; finding values are withheld." >&2
    exit 1
  fi
  : >"$report"
}

scan_trufflehog filesystem .
scan_trufflehog git "file://${PWD}"
echo "Secret scans passed for the worktree and full Git history."
