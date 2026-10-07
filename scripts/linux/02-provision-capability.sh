#!/usr/bin/env bash
# 02 - Provision or update an Integration Runtime capability.
# Usage: ./02-provision-capability.sh name data-plane-id namespace [version]
set -euo pipefail
source "$(dirname "$0")/_load-linux-config.sh"
BASE="${CONTROL_PLANE_URL:-http://127.0.0.1:19080}"; KEY="${ADMIN_KEY:?Set ADMIN_KEY}"
NAME="${1:-Integration Runtime}"; PLANE="${2:-$DATA_PLANE_ID}"; NS="${3:-$DATA_PLANE_NAMESPACE}"; VERSION="${4:-${MINA_VERSION:-1.0.0}}"; [[ -n "$PLANE" ]] || { echo 'Set [data-plane] id in the INI' >&2; exit 2; }
PAYLOAD=$("${MINA_PYTHON:-python3}" -c 'import json,sys; print(json.dumps({"name":sys.argv[1],"type":"integration-runtime","version":sys.argv[4],"dataPlaneId":sys.argv[2],"namespace":sys.argv[3],"tags":[]}))' "$NAME" "$PLANE" "$NS" "$VERSION")
ID="integration-runtime-${PLANE}-${NS}"
source "$(dirname "$0")/_api-upsert.sh"
mina_api_upsert /api/capabilities "$ID" "$PAYLOAD"
echo
