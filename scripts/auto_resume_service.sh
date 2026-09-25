#!/usr/bin/env sh
# Runs INSIDE the dev-auto-approver container (see docker-compose.yml).
# Continuously auto-resumes EVERY form_filling_10step run sitting at
# waiting_human, driving each through all 9 human-approval gates to
# completion — permanently, independent of any host-side session. Stands in
# for the "Approve & Continue" UI action that challenges-backend/
# challenges-frontend don't implement yet (see scripts/auto_resume.sh).
set -u

base_url="${AUTO_RESUME_BASE_URL:-http://api:8000}"
poll_interval="${AUTO_RESUME_POLL_SECONDS:-3}"
resume_value='{"approved": true}'

echo "dev-auto-approver: watching ALL form_filling_10step waiting_human runs @ ${base_url} (poll every ${poll_interval}s)"

max_age_hours="${AUTO_RESUME_MAX_AGE_HOURS:-6}"

while true; do
  # Only recent runs — old stale test runs from previous sessions/days stay
  # frozen rather than getting silently revived every time this restarts.
  run_ids=$(psql "$SN_DATABASE_URL" -tA -c "
    SELECT run_id FROM sn_run
    WHERE workflow='form_filling_10step' AND status='waiting_human'
      AND created_at > now() - interval '${max_age_hours} hours';
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
