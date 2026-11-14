#!/usr/bin/env bash
# Daily job: run the tests, then check every vendor and the news feeds, then rebuild
# CHANGELOG.md and site/. Used by the GitHub Action and for local test runs.
# Exit code: 0 = all good, 1 = tests failed (nothing written) or a vendor page could not be read.
set -uo pipefail
cd "$(dirname "$0")"
PY="${PYTHON:-python}"

if ! "$PY" -m pytest -q; then
  echo "Tests failed: not touching any data." >&2
  exit 1
fi
"$PY" -m subprocessor_watch
status=$?
echo "watcher exit code: $status"
exit "$status"
