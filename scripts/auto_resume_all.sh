#!/usr/bin/env bash
# Dev helper: continuously auto-resume EVERY form_filling_10step run sitting
# at waiting_human, driving each through all 9 human-approval gates to
# completion. Unlike auto_resume.sh (single run_id), this services every run
# — current and future — so it only needs to be started once per dev session.
# Stands in for the "Approve & Continue" UI action that challenges-backend/
# challenges-frontend don't implement yet (see auto_resume.sh's header).
#
# Usage: ./scripts/auto_resume_all.sh [base_url] [poll_interval_seconds]
set -uo pipefail

base_url="${1:-http://localhost:8000}"
poll_interval="${2:-3}"
resume_value='{"approved": true}'
compose_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "watching ALL form_filling_10step waiting_human runs @ ${base_url} (poll every ${poll_interval}s)"

while true; do
  run_ids=$(cd "$compose_dir" && docker compose exec -T postgres psql -U sn -d strategy_navigator -tA -c "
    SELECT run_id FROM sn_run
    WHERE workflow='form_filling_10step' AND status='waiting_human';
  " 2>/dev/null | sed '/^$/d')

  for run_id in $run_ids; do
    step=$(curl -sf "${base_url}/runs/${run_id}" 2>/dev/null | jq -r '.interrupt.stepNumber // "?"' 2>/dev/null)
    echo "[$(date +%H:%M:%S)] ${run_id} waiting_human at step ${step} -> resuming"
    curl -sf -X POST "${base_url}/runs/${run_id}/resume" \
      -H "Content-Type: application/json" \
      -d "{\"value\": ${resume_value}}" > /dev/null 2>&1
  done

  sleep "$poll_interval"
done
