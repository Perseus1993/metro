#!/usr/bin/env bash
set -euo pipefail

if [[ -f /etc/metro-cloud.env ]]; then
  set -a
  source /etc/metro-cloud.env
  set +a
fi
REPO_DIR="${METRO_REPO_DIR:-$(pwd)}"
VENV_DIR="${METRO_VENV_DIR:-${REPO_DIR}/.venv}"
EVIDENCE_DIR="${METRO_EVIDENCE_DIR:-/var/lib/metro-cloud/evidence}"
API_URL="${METRO_API_URL:-http://127.0.0.1:8000}"

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "Linux target required" >&2
  exit 2
fi
mkdir -p "${EVIDENCE_DIR}"

systemd-analyze verify \
  /etc/systemd/system/metro-cloud-api.service \
  /etc/systemd/system/metro-cloud-worker.service
systemctl is-active --quiet metro-cloud-api.service
systemctl is-active --quiet metro-cloud-worker.service

LISTENERS="$(ss -ltnH 'sport = :8000')"
if [[ -z "${LISTENERS}" ]]; then
  echo "nothing listens on port 8000" >&2
  exit 1
fi
if grep -Eq '(^|[[:space:]])(0\.0\.0\.0|\[::\]):8000' <<<"${LISTENERS}"; then
  echo "port 8000 is publicly bound" >&2
  exit 1
fi
if ! grep -Eq '127\.0\.0\.1:8000|\[::1\]:8000' <<<"${LISTENERS}"; then
  echo "port 8000 is not loopback-bound" >&2
  exit 1
fi

curl -fsS "${API_URL}/health" | tee "${EVIDENCE_DIR}/health.json"
AUTH_ARGS=()
if [[ -n "${METRO_API_TOKEN:-}" ]]; then
  AUTH_ARGS=(-H "Authorization: Bearer ${METRO_API_TOKEN}")
fi
curl -fsS "${AUTH_ARGS[@]}" "${API_URL}/v1/jobs" | python3 -c '
import json, sys
active = [job["id"] for job in json.load(sys.stdin)["jobs"] if job["status"] in {"queued", "running"}]
if active:
    raise SystemExit(f"active jobs must be drained before verification: {active}")
'
"${VENV_DIR}/bin/metro-cloud-remote-e2e" --url "${API_URL}" --runner real --agents 50 \
  --horizon-minutes 15 --demand-minutes 10 \
  --output "${EVIDENCE_DIR}/target-real-http-e2e-50.json"
"${VENV_DIR}/bin/metro-cloud-spike" --agents 25 50 100 200 \
  --timeout-seconds 14400 \
  --output "${EVIDENCE_DIR}/target-capacity-spike.json"
"${VENV_DIR}/bin/metro-cloud-remote-soak" --url "${API_URL}" \
  --jobs 10 --agents 50 \
  --horizon-minutes 15 --demand-minutes 10 --timeout-seconds 14400 \
  --output "${EVIDENCE_DIR}/target-real-soak-10x50.json"

df -h /var/lib/metro-cloud | tee "${EVIDENCE_DIR}/disk-after-soak.txt"
systemctl show metro-cloud-worker.service \
  -p ActiveState -p SubState -p MemoryCurrent -p MemoryPeak -p ControlGroup \
  | tee "${EVIDENCE_DIR}/worker-systemd-state.txt"
echo "target verification passed; run verify-worker-faults.sh and verify-worker-recovery.sh in a maintenance window"
