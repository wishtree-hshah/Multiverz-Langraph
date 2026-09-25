#!/usr/bin/env bash
# Dev helper: poll a run and auto-resume every waiting_human gate until it
# reaches a terminal state. Stands in for the "Approve & Continue" UI action
# that challenges-backend/challenges-frontend don't implement yet for
# form_filling_10step's 9 human-approval gates.
#
# Usage: ./scripts/auto_resume.sh <run_id> [base_url] [resume_value_json]
set -euo pipefail

run_id="${1:?usage: auto_resume.sh <run_id> [base_url] [resume_value_json]}"
base_url="${2:-http://localhost:8000}"
resume_value="${3:-{\"approved\": true}}"

echo "watching ${run_id} @ ${base_url}"

while true; do
  run=$(curl -sf "${base_url}/runs/${run_id}")
  status=$(echo "$run" | jq -r '.status')

  case "$status" in
    waiting_human)
      step=$(echo "$run" | jq -c '.interrupt')
      echo "[$(date +%H:%M:%S)] waiting_human, interrupt=${step} -> resuming"
      curl -sf -X POST "${base_url}/runs/${run_id}/resume" \
        -H "Content-Type: application/json" \
        -d "{\"value\": ${resume_value}}" > /dev/null
      sleep 2
      ;;
    succeeded|failed|dead)
      echo "[$(date +%H:%M:%S)] terminal status: ${status}"
      echo "$run" | jq .
      exit 0
      ;;
    queued|running)
      sleep 2
      ;;
    *)
      echo "unexpected status: ${status}"
      echo "$run" | jq .
      exit 1
      ;;
  esac
done
