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
set -euo pipefail
source "$(dirname "$0")/_load-linux-config.sh"
exec "${FABRIC_PYTHON:-python3}" "$(dirname "$0")/remote-data-plane-agent.py" "$@"
