#!/usr/bin/env bash
# Load all sections from the central INI as FABRIC_* shell variables.
CONFIG_FILE="${FABRIC_CONFIG_FILE:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/integration-fabric-control-plane.ini}"
[[ -f "$CONFIG_FILE" ]] || { echo "ERROR: INI file not found: $CONFIG_FILE" >&2; return 1 2>/dev/null || exit 1; }
shopt -s extglob
fabric_ini_load() {
  local section="$1" line key value in_section=0 variable
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%%#*}"; line="${line##+([[:space:]])}"; line="${line%%+([[:space:]])}"
    [[ -z "$line" ]] && continue
    if [[ "$line" == "["*] ]]; then in_section=0; [[ "$line" == "[$section]" ]] && in_section=1; continue; fi
    [[ "$in_section" == 1 && "$line" == *=* ]] || continue
    key="${line%%=*}"; value="${line#*=}"; key="${key//[[:space:]]/}"
    case "$section:$key" in
      control-plane:control_plane_url) variable=CONTROL_PLANE_URL ;;
      control-plane:admin_key) variable=ADMIN_KEY ;;
      control-plane:secret_key) variable=ADMIN_SECRET_KEY ;;
      data-plane:id) variable=DATA_PLANE_ID ;;
      data-plane:name) variable=DATA_PLANE_NAME ;;
      data-plane:namespace) variable=DATA_PLANE_NAMESPACE ;;
      data-plane:agent_version) variable=AGENT_VERSION ;;
      data-plane:heartbeat_seconds) variable=HEARTBEAT_SECONDS ;;
      data-plane:available_capacity) variable=AVAILABLE_CAPACITY ;;
      delivery-team:id) variable=DELIVERY_TEAM_ID ;;
      delivery-team:name) variable=DELIVERY_TEAM_NAME ;;
      delivery-team:description) variable=DELIVERY_TEAM_DESCRIPTION ;;
      delivery-team:scopes_json) variable=DELIVERY_TEAM_SCOPES_JSON ;;
      user:id) variable=USER_ID ;;
      user:name) variable=USER_NAME ;;
      user:team_id) variable=USER_TEAM_ID ;;
      user:role) variable=USER_ROLE ;;
      user:scope) variable=USER_SCOPE ;;
      user:resource_id) variable=USER_RESOURCE_ID ;;
      setup:version) variable=FABRIC_VERSION ;;
      *) variable="FABRIC_${section^^}_${key^^}"; variable="${variable//-/_}" ;;
    esac
    printf -v "$variable" '%s' "$value"; export "$variable"
  done < "$CONFIG_FILE"
}
fabric_ini_load control-plane; fabric_ini_load runtime; fabric_ini_load data-plane
fabric_ini_load delivery-team; fabric_ini_load user; fabric_ini_load setup
CONTROL_PLANE_URL="${CONTROL_PLANE_URL:-http://127.0.0.1:19080}"
ADMIN_KEY="${ADMIN_KEY:-}"
DATA_PLANE_ID="${DATA_PLANE_ID:-}"
DATA_PLANE_NAMESPACE="${DATA_PLANE_NAMESPACE:-default}"
HEARTBEAT_SECONDS="${HEARTBEAT_SECONDS:-30}"
AVAILABLE_CAPACITY="${AVAILABLE_CAPACITY:-20}"
export CONTROL_PLANE_URL ADMIN_KEY HEARTBEAT_SECONDS AVAILABLE_CAPACITY
