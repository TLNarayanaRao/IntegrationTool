#!/usr/bin/env bash
# 05 - Start the lightweight MINA data-plane heartbeat agent.
#
# This process keeps a registered data plane ONLINE by sending heartbeats to
# the Control Plane. Run one agent per data plane. It does not use systemd.
#
# Usage:
#   CONTROL_PLANE_URL=http://pho-tibwapp-d03:19080 \
#   ADMIN_KEY='technology-team-key' \
#   ./05-start-data-plane-agent.sh customer-data-delivery-plane BDDcustomer
#
# Optional variables:
#   AGENT_VERSION=1.0.0 HEARTBEAT_SECONDS=30 AVAILABLE_CAPACITY=50
#   MINA_JAVA_BRIDGE_HOME=/path/to/java-bridge/build
#   MINA_DRIVER_HOME=/path/to/drivers
#   MINA_JAVA=/path/to/java
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/_load-linux-config.sh"

# Native connector archives are unpacked below the agent directory, while the
# licensed drivers and Java bridge are shared by every data plane beneath the
# MINA installation root.  Establish those defaults here so operators do not
# have to include them in each nohup command. Explicit environment overrides
# remain supported for non-standard installations.
MINA_INSTALL_ROOT="${MINA_INSTALL_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
export MINA_JAVA_BRIDGE_HOME="${MINA_JAVA_BRIDGE_HOME:-$MINA_INSTALL_ROOT/java-bridge/build}"
export MINA_DRIVER_HOME="${MINA_DRIVER_HOME:-$MINA_INSTALL_ROOT/drivers}"
if [[ -z "${MINA_JAVA:-}" && -x "$MINA_INSTALL_ROOT/java/openjdk17/bin/java" ]]; then
  export MINA_JAVA="$MINA_INSTALL_ROOT/java/openjdk17/bin/java"
fi

exec "${MINA_PYTHON:-python3}" "$SCRIPT_DIR/remote-data-plane-agent.py" "$@"
