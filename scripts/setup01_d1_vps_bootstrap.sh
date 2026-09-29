#!/usr/bin/env bash
# One-time initialization of the SETUP_01 D1 durable storage VPS.
#
# Run once on the Ubuntu VPS as root:
#
#   sudo D1_VPS_PUBLIC_KEY="ssh-ed25519 AAAA... d1-github-actions" \
#        bash scripts/setup01_d1_vps_bootstrap.sh
#
# It creates the dedicated non-root account, the frozen storage root layout and
# the repository-owned remote helper.  It never touches nginx, databases,
# containers, proxy settings or any unrelated service, and it is idempotent.
set -euo pipefail

STORAGE_ROOT="${D1_VPS_STORAGE_ROOT:-/srv/d1-research}"
SERVICE_USER="${D1_VPS_USER:-d1store}"
HELPER_SOURCE="${D1_VPS_HELPER_SOURCE:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/research/d1_vps_store_helper.py}"
PUBLIC_KEY="${D1_VPS_PUBLIC_KEY:-}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "run as root (sudo)" >&2
  exit 1
fi
if [[ "${STORAGE_ROOT}" != /* ]]; then
  echo "D1_VPS_STORAGE_ROOT must be an absolute path" >&2
  exit 1
fi
if [[ ! -f "${HELPER_SOURCE}" ]]; then
  echo "remote helper not found: ${HELPER_SOURCE}" >&2
  exit 1
fi

if ! id -u "${SERVICE_USER}" >/dev/null 2>&1; then
  adduser --system --group --home "${STORAGE_ROOT}" --no-create-home --shell /bin/bash "${SERVICE_USER}"
fi

install -d -m 0750 -o "${SERVICE_USER}" -g "${SERVICE_USER}" "${STORAGE_ROOT}"
for directory in objects sessions sessions/CN sessions/US system system/activation system/activation_epochs system/activation_epochs/CN system/activation_epochs/US system/validation manifests; do
  install -d -m 0750 -o "${SERVICE_USER}" -g "${SERVICE_USER}" "${STORAGE_ROOT}/${directory}"
done
install -d -m 0700 -o "${SERVICE_USER}" -g "${SERVICE_USER}" "${STORAGE_ROOT}/system/tmp"

# The helper is repository-owned and must not be writable by the runtime
# account or any other non-root user.
install -m 0644 -o root -g root "${HELPER_SOURCE}" "${STORAGE_ROOT}/system/d1_vps_store_helper.py"

if [[ -n "${PUBLIC_KEY}" ]]; then
  install -d -m 0700 -o "${SERVICE_USER}" -g "${SERVICE_USER}" "${STORAGE_ROOT}/.ssh"
  touch "${STORAGE_ROOT}/.ssh/authorized_keys"
  grep -qxF "${PUBLIC_KEY}" "${STORAGE_ROOT}/.ssh/authorized_keys" || echo "${PUBLIC_KEY}" >> "${STORAGE_ROOT}/.ssh/authorized_keys"
  chmod 0600 "${STORAGE_ROOT}/.ssh/authorized_keys"
  chown "${SERVICE_USER}:${SERVICE_USER}" "${STORAGE_ROOT}/.ssh/authorized_keys"
fi

echo
echo "Storage root:      ${STORAGE_ROOT}"
echo "Runtime account:   ${SERVICE_USER} (non-root, no sudo)"
echo "Remote helper:     ${STORAGE_ROOT}/system/d1_vps_store_helper.py"
echo
echo "Freeze this SSH host key fingerprint in the D1_VPS_HOST_KEY_FINGERPRINT secret:"
for key in /etc/ssh/ssh_host_ed25519_key.pub /etc/ssh/ssh_host_rsa_key.pub; do
  [[ -f "${key}" ]] && ssh-keygen -lf "${key}"
done
echo "Known_hosts entry for the GitHub side:"
for key in /etc/ssh/ssh_host_ed25519_key.pub /etc/ssh/ssh_host_rsa_key.pub; do
  [[ -f "${key}" ]] && echo "$(hostname -I 2>/dev/null | awk '{print $1}') $(cut -d' ' -f1,2 "${key}")"
done
echo
echo "Storage identity (freeze this in D1_VPS_STORAGE_ROOT / turnstile validation input):"
python3 "${STORAGE_ROOT}/system/d1_vps_store_helper.py" --root "${STORAGE_ROOT}" identity
