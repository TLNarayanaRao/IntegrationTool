#!/usr/bin/env bash
# PUT failures only fall back to POST when the resource is absent.
mina_api_upsert() {
  local collection="$1" identifier="$2" payload="$3" response status
  response="$(mktemp)"
  status="$(curl -sS -o "$response" -w '%{http_code}' -X PUT "${BASE%/}$collection/$identifier" -H "X-Admin-Key: $KEY" -H 'Content-Type: application/json' -d "$payload")" || status=000
  if [[ "$status" == 2* ]]; then
    cat "$response"; rm -f "$response"
  elif [[ "$status" == 404 ]]; then
    rm -f "$response"
    curl -fsS -X POST "${BASE%/}$collection" -H "X-Admin-Key: $KEY" -H 'Content-Type: application/json' -d "$payload"
  else
    echo "ERROR: Control Plane update failed (HTTP $status)" >&2
    cat "$response" >&2; rm -f "$response"; return 1
  fi
}
