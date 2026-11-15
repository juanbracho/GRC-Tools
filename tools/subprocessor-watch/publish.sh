#!/usr/bin/env bash
# Commit the day's data and push it (used by the GitHub Action after daily.sh).
# If main moved while we were running (someone pushed), generated files can
# conflict. They are never merged by hand: we move to the latest main, run the
# watcher again there, and push that. Up to 3 attempts.
set -euo pipefail
cd "$(dirname "$0")"
BRANCH="${1:-main}"
PY="${PYTHON:-python}"

commit() {
  git add data CHANGELOG.md site
  if git diff --cached --quiet; then
    echo "No changes."
    return 1
  fi
  git commit -q -m "Subprocessor Watch: daily update $(date -u +%F)"
}

commit || exit 0
for attempt in 1 2 3; do
  git fetch -q origin "$BRANCH"
  if git rebase -q "origin/$BRANCH" 2>/dev/null; then
    if git push -q origin "HEAD:$BRANCH"; then
      echo "Pushed (attempt $attempt)."
      exit 0
    fi
    echo "Push rejected (main moved again); retrying."
  else
    echo "Main moved and generated files conflict: re-running on top of the latest main."
    git rebase --abort
    git reset -q --hard "origin/$BRANCH"
    "$PY" -m subprocessor_watch || true   # its exit code was already reported by daily.sh
    commit || exit 0
  fi
done
echo "Could not push after 3 attempts." >&2
exit 1
