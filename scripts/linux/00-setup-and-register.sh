#!/usr/bin/env bash
# 00 - Execute the complete Linux setup and Control Plane registration flow.
# Edit integration-fabric-control-plane.ini, then run this script.
# No systemctl is used. Set START_AGENT=false to register resources only.
set -Eeuo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/_load-linux-config.sh"
ROOT="${FABRIC_ROOT:-/opt/tibco/esb/IntegrationFabricSoftware}"
VERSION="${FABRIC_VERSION:-1.0.0}"

echo "[1/6] Setting up the Linux Administrator and runtime"
FABRIC_ROOT="$ROOT" FABRIC_PYTHON="${FABRIC_PYTHON:-/usr/bin/python3.12}" FABRIC_ADMIN_PORT="${FABRIC_CONTROL_PLANE_PORT:-19080}" FABRIC_ADMIN_HOST="${FABRIC_CONTROL_PLANE_HOST:-0.0.0.0}" FABRIC_ADMIN_API_KEY="$ADMIN_KEY" FABRIC_ADMIN_SECRET_KEY="${ADMIN_SECRET_KEY:-$ADMIN_KEY}" \
  "$SCRIPT_DIR/setup-integration-fabric-linux.sh" "$VERSION"

echo "[2/7] Starting Control Plane"
CP_DIR="$ROOT/control-plane"
[[ -x "$CP_DIR/start-control-plane.sh" ]] || { echo "ERROR: Control Plane launcher not found: $CP_DIR/start-control-plane.sh" >&2; exit 1; }
if ! "$CP_DIR/start-control-plane.sh" status 2>/dev/null | grep -q '^RUNNING'; then
  "$CP_DIR/start-control-plane.sh" start
fi
for attempt in $(seq 1 30); do
  if curl --silent --fail --connect-timeout 2 "${CONTROL_PLANE_URL%/}/api/health" >/dev/null; then
    echo "Control Plane is ready."
    break
  fi
  [[ "$attempt" -eq 30 ]] && { echo "ERROR: Control Plane did not become ready at ${CONTROL_PLANE_URL%/}" >&2; exit 1; }
  sleep 1
done

echo "[3/7] Registering data plane"
"$SCRIPT_DIR/01-register-data-plane.sh"
echo "[4/7] Provisioning Integration Runtime capability"
"$SCRIPT_DIR/02-provision-capability.sh"
echo "[5/7] Creating or updating delivery team"
"$SCRIPT_DIR/03-create-delivery-team.sh"
echo "[6/7] Creating or updating user"
"$SCRIPT_DIR/04-create-user.sh"

if [[ "${START_AGENT:-true}" == "true" ]]; then
  echo "[7/7] Starting data-plane heartbeat agent"
  AGENT_LOG="${FABRIC_AGENT_LOG:-$ROOT/logs/data-plane-agent.log}"
  mkdir -p "$(dirname "$AGENT_LOG")"
  nohup "$SCRIPT_DIR/05-start-data-plane-agent.sh" >"$AGENT_LOG" 2>&1 &
  echo "Data-plane agent started with PID $!; log: $AGENT_LOG"
else
  echo "[7/7] Agent start skipped (START_AGENT=$START_AGENT)"
fi
echo "Complete. Check: curl -H \"X-Admin-Key: $ADMIN_KEY\" \"$CONTROL_PLANE_URL/api/health\""
