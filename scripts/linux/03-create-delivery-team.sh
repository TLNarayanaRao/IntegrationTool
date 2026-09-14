#!/usr/bin/env bash
# 03 - Create or update a delivery team and isolated namespaces.
# Usage: SCOPES_JSON='[{"dataPlaneId":"customer-plane","namespace":"BDDcustomer"}]' ./03-create-delivery-team.sh team-id "Team Name" [description]
set -euo pipefail
source "$(dirname "$0")/_load-linux-config.sh"
BASE="${CONTROL_PLANE_URL:-http://127.0.0.1:19080}"; KEY="${ADMIN_KEY:?Set admin_key in integration-fabric-control-plane.ini}"
ID="${1:-${DELIVERY_TEAM_ID:-}}"; NAME="${2:-${DELIVERY_TEAM_NAME:-Delivery Team}}"; DESCRIPTION="${3:-${DELIVERY_TEAM_DESCRIPTION:-Delivery team}}"; SCOPES="${SCOPES_JSON:-${DELIVERY_TEAM_SCOPES_JSON:-}}"; [[ -n "$ID" && -n "$SCOPES" ]] || { echo 'Set [delivery-team] id and scopes_json in the INI' >&2; exit 2; }
PAYLOAD=$(python3 -c 'import json,sys; print(json.dumps({"id":sys.argv[1],"name":sys.argv[2],"kind":"delivery","description":sys.argv[3],"namespaceScopes":json.loads(sys.argv[4])}))' "$ID" "$NAME" "$DESCRIPTION" "$SCOPES")
RESPONSE_FILE=$(mktemp)
trap 'rm -f "$RESPONSE_FILE"' EXIT
STATUS=$(curl -sS -o "$RESPONSE_FILE" -w '%{http_code}' -X PUT "$BASE/api/teams/$ID" -H "X-Admin-Key: $KEY" -H 'Content-Type: application/json' -d "$PAYLOAD") || STATUS=000
if [[ "$STATUS" == 2* ]]; then
  cat "$RESPONSE_FILE"; echo
elif [[ "$STATUS" == 404 ]]; then
  curl -fsS -X POST "$BASE/api/teams" -H "X-Admin-Key: $KEY" -H 'Content-Type: application/json' -d "$PAYLOAD"
  echo
else
  echo "ERROR: Control Plane rejected delivery team update (HTTP $STATUS):" >&2
  cat "$RESPONSE_FILE" >&2; echo >&2
  exit 1
fi
