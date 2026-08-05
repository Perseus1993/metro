#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "run as root: sudo bash apps/cloud_api/deploy/install.sh" >&2
  exit 2
fi

REPO_DIR="${METRO_REPO_DIR:-$(pwd)}"
if [[ "$(realpath "${REPO_DIR}")" != "/opt/metro" ]]; then
  echo "systemd units require the workspace at /opt/metro" >&2
  exit 2
fi
if [[ ! -f "${REPO_DIR}/apps/cloud_api/pyproject.toml" ]]; then
  echo "METRO_REPO_DIR is not a metro workspace: ${REPO_DIR}" >&2
  exit 2
fi

if ! id metro-cloud >/dev/null 2>&1; then
  useradd --system --home /var/lib/metro-cloud --shell /usr/sbin/nologin metro-cloud
fi
install -d -o metro-cloud -g metro-cloud /var/lib/metro-cloud
install -d -o metro-cloud -g metro-cloud /var/lib/metro-cloud/evidence

cd "${REPO_DIR}"
UV_PROJECT_ENVIRONMENT="${REPO_DIR}/.venv" uv sync --locked \
  --package metro-cloud --extra real

if [[ ! -f /etc/metro-cloud.env ]]; then
  install -m 0640 -o root -g metro-cloud \
    apps/cloud_api/deploy/metro-cloud.env.example /etc/metro-cloud.env
fi
install -m 0644 apps/cloud_api/deploy/metro-cloud-api.service \
  /etc/systemd/system/metro-cloud-api.service
install -m 0644 apps/cloud_api/deploy/metro-cloud-worker.service \
  /etc/systemd/system/metro-cloud-worker.service

systemctl daemon-reload
systemctl enable --now metro-cloud-api.service metro-cloud-worker.service
systemctl --no-pager --full status metro-cloud-api.service metro-cloud-worker.service
