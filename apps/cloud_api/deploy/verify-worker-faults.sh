#!/usr/bin/env bash
set -euo pipefail

if [[ -f /etc/metro-cloud.env ]]; then
  set -a
  source /etc/metro-cloud.env
  set +a
fi
API_URL="${METRO_API_URL:-http://127.0.0.1:8000}"
EVIDENCE_DIR="${METRO_EVIDENCE_DIR:-/var/lib/metro-cloud/evidence}"
DROPIN_DIR="/run/systemd/system/metro-cloud-worker.service.d"
DROPIN_FILE="${DROPIN_DIR}/timeout-test.conf"
CURL=(curl -fsS)
if [[ -n "${METRO_API_TOKEN:-}" ]]; then
  CURL+=(-H "Authorization: Bearer ${METRO_API_TOKEN}")
fi

if [[ "${EUID}" -ne 0 ]]; then
  echo "run as root; this temporarily restarts metro-cloud-worker" >&2
  exit 2
fi
mkdir -p "${EVIDENCE_DIR}"

assert_drained() {
  "${CURL[@]}" "${API_URL}/v1/jobs" | python3 -c '
import json, sys
active = [job["id"] for job in json.load(sys.stdin)["jobs"] if job["status"] in {"queued", "running"}]
if active:
    raise SystemExit(f"active jobs must be drained before fault test: {active}")
'
}

wait_for_status() {
  local job_id="$1"
  local wanted="$2"
  local status=""
  for _ in $(seq 1 600); do
    status="$("${CURL[@]}" "${API_URL}/v1/jobs/${job_id}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["status"])')"
    [[ "${status}" == "${wanted}" ]] && return 0
    [[ "${status}" =~ ^(failed|succeeded|cancelled)$ ]] && break
    sleep 0.1
  done
  echo "job ${job_id} reached ${status:-unknown}, expected ${wanted}" >&2
  return 1
}

assert_no_child() {
  local output="$1"
  ps -eo pid=,args= | awk '/python.*-m metro_cloud_api[.]child( |$)/ { print }' > "${output}"
  if [[ -s "${output}" ]]; then
    echo "orphan metro_cloud_api.child process found" >&2
    return 1
  fi
}

download_summary() {
  local job_id="$1"
  local output="$2"
  for _ in $(seq 1 100); do
    if "${CURL[@]}" "${API_URL}/v1/jobs/${job_id}/artifacts/summary.json" > "${output}"; then
      return 0
    fi
    sleep 0.1
  done
  echo "summary did not become downloadable for ${job_id}" >&2
  return 1
}

restore_worker() {
  rm -f -- "${DROPIN_FILE}"
  rmdir --ignore-fail-on-non-empty "${DROPIN_DIR}" 2>/dev/null || true
  systemctl daemon-reload
  systemctl restart metro-cloud-worker.service
}
trap restore_worker EXIT

assert_drained
PAYLOAD='{"spec_version":"0.1","horizon_minutes":60,"demand_minutes":60,"entry_count_hour":50,"exit_count_hour":0,"transfer_count_hour":0,"trajectory_sample_seconds":10,"label":"running-cancel"}'
CANCEL_RESPONSE="$("${CURL[@]}" -X POST -H 'Content-Type: application/json' -d "${PAYLOAD}" "${API_URL}/v1/jobs")"
CANCEL_ID="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])' <<<"${CANCEL_RESPONSE}")"
wait_for_status "${CANCEL_ID}" running
"${CURL[@]}" -X POST "${API_URL}/v1/jobs/${CANCEL_ID}/cancel" >/dev/null
wait_for_status "${CANCEL_ID}" cancelled
download_summary "${CANCEL_ID}" "${EVIDENCE_DIR}/worker-running-cancel-summary.json"
python3 - "${EVIDENCE_DIR}/worker-running-cancel-summary.json" <<'PY'
import json, sys
summary = json.load(open(sys.argv[1], encoding="utf-8"))
assert summary["status"] == "cancelled", summary
assert summary["error"]["kind"] == "cancelled", summary
assert summary["result"]["trajectory_rows"] is None, summary
PY
assert_no_child "${EVIDENCE_DIR}/worker-cancel-orphans.txt"

mkdir -p "${DROPIN_DIR}"
printf '[Service]\nEnvironment=METRO_JOB_TIMEOUT_SECONDS=0.1\n' > "${DROPIN_FILE}"
systemctl daemon-reload
systemctl restart metro-cloud-worker.service
systemctl is-active --quiet metro-cloud-worker.service
assert_drained
TIMEOUT_PAYLOAD='{"spec_version":"0.1","horizon_minutes":15,"demand_minutes":10,"entry_count_hour":300,"exit_count_hour":0,"transfer_count_hour":0,"trajectory_sample_seconds":10,"label":"forced-timeout"}'
TIMEOUT_RESPONSE="$("${CURL[@]}" -X POST -H 'Content-Type: application/json' -d "${TIMEOUT_PAYLOAD}" "${API_URL}/v1/jobs")"
TIMEOUT_ID="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])' <<<"${TIMEOUT_RESPONSE}")"
wait_for_status "${TIMEOUT_ID}" failed
download_summary "${TIMEOUT_ID}" "${EVIDENCE_DIR}/worker-timeout-summary.json"
python3 - "${EVIDENCE_DIR}/worker-timeout-summary.json" <<'PY'
import json, sys
summary = json.load(open(sys.argv[1], encoding="utf-8"))
assert summary["status"] == "failed", summary
assert summary["error"]["kind"] == "timeout", summary
assert summary["result"]["trajectory_rows"] is None, summary
PY
assert_no_child "${EVIDENCE_DIR}/worker-timeout-orphans.txt"

restore_worker
trap - EXIT
systemctl is-active --quiet metro-cloud-worker.service
echo "running cancel and forced timeout cleanup passed"
