#!/usr/bin/env bash
# 01 - Register or update a data plane.
# Usage: CONTROL_PLANE_URL=http://host:19080 ADMIN_KEY=... ./01-register-data-plane.sh id name [type] [host] [region] [namespaces] [capacity]
set -euo pipefail
source "$(dirname "$0")/_load-linux-config.sh"
BASE="${CONTROL_PLANE_URL:-http://pho-tibwapp-d03:19080/}"; KEY="${ADMIN_KEY:?Set ADMIN_KEY}"
ID="${1:-$DATA_PLANE_ID}"; NAME="${2:-${DATA_PLANE_NAME:-Customer Data Plane}}"; TYPE="${3:-on-premises}"; HOST="${4:-127.0.0.1}"; REGION="${5:-local}"; NS="${6:-$DATA_PLANE_NAMESPACE}"; CAPACITY="${7:-$AVAILABLE_CAPACITY}"; [[ -n "$ID" ]] || { echo 'Set [data-plane] id in the INI' >&2; exit 2; }
PAYLOAD=$(python3 -c 'import json,sys; print(json.dumps({"id":sys.argv[1],"name":sys.argv[2],"type":sys.argv[3],"host":sys.argv[4],"region":sys.argv[5],"namespaces":[x.strip() for x in sys.argv[6].split(",") if x.strip()],"capacity":int(sys.argv[7]),"driver":"agent","tags":[]}))' "$ID" "$NAME" "$TYPE" "$HOST" "$REGION" "$NS" "$CAPACITY")
curl -fs -X PUT "$BASE/api/data-planes/$ID" -H "X-Admin-Key: $KEY" -H 'Content-Type: application/json' -d "$PAYLOAD" 2>/dev/null || curl -fsS -X POST "$BASE/api/data-planes" -H "X-Admin-Key: $KEY" -H 'Content-Type: application/json' -d "$PAYLOAD"
echo
