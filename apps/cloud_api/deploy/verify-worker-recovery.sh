#!/usr/bin/env bash
set -euo pipefail

if [[ -f /etc/metro-cloud.env ]]; then
  set -a
  source /etc/metro-cloud.env
  set +a
fi
API_URL="${METRO_API_URL:-http://127.0.0.1:8000}"
EVIDENCE_DIR="${METRO_EVIDENCE_DIR:-/var/lib/metro-cloud/evidence}"
CURL=(curl -fsS)
if [[ -n "${METRO_API_TOKEN:-}" ]]; then
  CURL+=(-H "Authorization: Bearer ${METRO_API_TOKEN}")
fi

if [[ "${EUID}" -ne 0 ]]; then
  echo "run as root; this intentionally SIGKILLs metro-cloud-worker" >&2
  exit 2
fi
mkdir -p "${EVIDENCE_DIR}"

"${CURL[@]}" "${API_URL}/v1/jobs" | python3 -c '
import json, sys
active = [job["id"] for job in json.load(sys.stdin)["jobs"] if job["status"] in {"queued", "running"}]
if active:
    raise SystemExit(f"active jobs must be drained before recovery test: {active}")
'

PAYLOAD='{"spec_version":"0.1","horizon_minutes":15,"demand_minutes":10,"entry_count_hour":300,"exit_count_hour":0,"transfer_count_hour":0,"trajectory_sample_seconds":10,"label":"systemd-recovery"}'
RESPONSE="$("${CURL[@]}" -X POST -H 'Content-Type: application/json' -d "${PAYLOAD}" "${API_URL}/v1/jobs")"
JOB_ID="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])' <<<"${RESPONSE}")"

for _ in $(seq 1 100); do
  STATUS="$("${CURL[@]}" "${API_URL}/v1/jobs/${JOB_ID}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["status"])')"
  [[ "${STATUS}" == "running" ]] && break
  [[ "${STATUS}" =~ ^(failed|succeeded|cancelled)$ ]] && {
    echo "job became terminal before recovery test: ${STATUS}" >&2
    exit 1
  }
  sleep 0.1
done
[[ "${STATUS}" == "running" ]] || { echo "job never reached running" >&2; exit 1; }

systemctl kill --kill-whom=all --signal=SIGKILL metro-cloud-worker.service

for _ in $(seq 1 200); do
  STATUS="$("${CURL[@]}" "${API_URL}/v1/jobs/${JOB_ID}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["status"])')"
  [[ "${STATUS}" == "failed" ]] && break
  sleep 0.1
done
[[ "${STATUS}" == "failed" ]] || { echo "recovered job did not become failed" >&2; exit 1; }

"${CURL[@]}" "${API_URL}/v1/jobs/${JOB_ID}/artifacts/summary.json" \
  > "${EVIDENCE_DIR}/worker-recovery-summary.json"
python3 - "${EVIDENCE_DIR}/worker-recovery-summary.json" <<'PY'
import json
import sys

summary = json.load(open(sys.argv[1], encoding="utf-8"))
assert summary["status"] == "failed", summary
assert summary["error"]["kind"] == "worker_lost", summary
PY

systemctl is-active --quiet metro-cloud-worker.service
if ps -eo pid=,args= | awk '/python.*-m metro_cloud_api[.]child( |$)/ { print }' \
  > "${EVIDENCE_DIR}/worker-recovery-orphans.txt" && \
  [[ -s "${EVIDENCE_DIR}/worker-recovery-orphans.txt" ]]; then
  echo "orphan metro_cloud_api.child process found" >&2
  exit 1
fi
echo "worker SIGKILL recovery passed for ${JOB_ID}"
