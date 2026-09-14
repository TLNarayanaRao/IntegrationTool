#!/usr/bin/env bash
# 04 - Create or update a user/principal.
# Usage: ./04-create-user.sh user-id team-id [role] [scope] [resource-id] [display-name]
set -euo pipefail
source "$(dirname "$0")/_load-linux-config.sh"
BASE="${CONTROL_PLANE_URL:-http://127.0.0.1:19080}"; KEY="${ADMIN_KEY:?Set ADMIN_KEY}"
ID="${1:-${USER_ID:-}}"; TEAM="${2:-${USER_TEAM_ID:-}}"; ROLE="${3:-${USER_ROLE:-Application Manager}}"; SCOPE="${4:-${USER_SCOPE:-namespace}}"; RESOURCE="${5:-${USER_RESOURCE_ID:-*}}"; NAME="${6:-${USER_NAME:-$ID}}"; [[ -n "$ID" && -n "$TEAM" ]] || { echo 'Set [user] id and team_id in the INI' >&2; exit 2; }
PAYLOAD=$(python3 -c 'import json,sys; print(json.dumps({"id":sys.argv[1],"name":sys.argv[7],"type":"user","teamId":sys.argv[2],"permissions":[{"role":sys.argv[3],"scope":sys.argv[4],"resourceId":sys.argv[5]}]}))' "$ID" "$TEAM" "$ROLE" "$SCOPE" "$RESOURCE" unused "$NAME")
curl -fsS -X PUT "$BASE/api/access/principals/$ID" -H "X-Admin-Key: $KEY" -H 'Content-Type: application/json' -d "$PAYLOAD" || curl -fsS -X POST "$BASE/api/access/principals" -H "X-Admin-Key: $KEY" -H 'Content-Type: application/json' -d "$PAYLOAD"
echo
