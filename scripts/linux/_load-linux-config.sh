#!/usr/bin/env bash
# Values are data, never evaluated as shell commands.
CONFIG_FILE="${MINA_CONFIG_FILE:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/mina-control-plane.ini}"
[[ -f "$CONFIG_FILE" ]] || { echo "ERROR: INI file not found: $CONFIG_FILE" >&2; return 1; }
_mina_config_tmp="$(mktemp)"
if ! "${MINA_PYTHON:-python3}" "$(dirname "${BASH_SOURCE[0]}")/linux_config.py" "$CONFIG_FILE" > "$_mina_config_tmp"; then
  rm -f "$_mina_config_tmp"; return 1
fi
while IFS= read -r -d '' _mina_name && IFS= read -r -d '' _mina_value; do
  printf -v "$_mina_name" '%s' "$_mina_value"; export "$_mina_name"
done < "$_mina_config_tmp"
rm -f "$_mina_config_tmp"
unset _mina_config_tmp _mina_name _mina_value
CONTROL_PLANE_URL="${CONTROL_PLANE_URL:-http://127.0.0.1:19080}"
CONTROL_PLANE_URL="${CONTROL_PLANE_URL%/}"
ADMIN_KEY="${ADMIN_KEY:-${MINA_CONTROL_PLANE_API_KEY:-}}"
DATA_PLANE_ID="${DATA_PLANE_ID:-}"
DATA_PLANE_NAMESPACE="${DATA_PLANE_NAMESPACE:-default}"
HEARTBEAT_SECONDS="${HEARTBEAT_SECONDS:-30}"
AVAILABLE_CAPACITY="${AVAILABLE_CAPACITY:-20}"
export CONTROL_PLANE_URL ADMIN_KEY HEARTBEAT_SECONDS AVAILABLE_CAPACITY
