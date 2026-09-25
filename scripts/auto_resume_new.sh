#!/usr/bin/env bash
# Dev helper: auto-resume every form_filling_10step run through all 9
# human-approval gates to completion, WITHOUT needing to be told per-run —
# but only for runs created AFTER this script starts. Existing runs (already
# being watched some other way, or intentionally left alone) are snapshotted
# at startup and never touched.
#
# Stands in for the "Approve & Continue" UI action that challenges-backend/
# challenges-frontend don't implement yet (see auto_resume.sh's header).
#
# Usage: ./scripts/auto_resume_new.sh [base_url] [poll_interval_seconds]
set -uo pipefail

base_url="${1:-http://localhost:8000}"
poll_interval="${2:-3}"
resume_value='{"approved": true}'
compose_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

_all_run_ids() {
  (cd "$compose_dir" && docker compose exec -T postgres psql -U sn -d strategy_navigator -tA -c "
    SELECT run_id FROM sn_run WHERE workflow='form_filling_10step';
  " 2>/dev/null | sed '/^$/d')
}

known_ids=$(_all_run_ids)
echo "watching for NEW form_filling_10step runs @ ${base_url} (poll every ${poll_interval}s)"
echo "ignoring $(echo "$known_ids" | grep -c .) pre-existing run(s)"

while true; do
  waiting_ids=$(cd "$compose_dir" && docker compose exec -T postgres psql -U sn -d strategy_navigator -tA -c "
    SELECT run_id FROM sn_run
    WHERE workflow='form_filling_10step' AND status='waiting_human';
  " 2>/dev/null | sed '/^$/d')

  for run_id in $waiting_ids; do
    if grep -qxF "$run_id" <<< "$known_ids"; then
      continue  # pre-existing run — leave it alone
    fi
    step=$(curl -sf "${base_url}/runs/${run_id}" 2>/dev/null | jq -r '.interrupt.stepNumber // "?"' 2>/dev/null)
    echo "[$(date +%H:%M:%S)] NEW run ${run_id} waiting_human at step ${step} -> resuming"
    curl -sf -X POST "${base_url}/runs/${run_id}/resume" \
      -H "Content-Type: application/json" \
      -d "{\"value\": ${resume_value}}" > /dev/null 2>&1
  done

  # known_ids stays FROZEN at the startup snapshot — a new run must keep
  # getting resumed on every one of its 9 gates (step 2, 3, ... 9), not just
  # its first, so it must never be added to the ignore set.
  sleep "$poll_interval"
done
