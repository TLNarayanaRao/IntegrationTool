#!/usr/bin/env bash
set -Eeuo pipefail

artifact_dir="${1:?Provide the downloaded artifact directory}"
profile="${2:?Provide the MINA environment profile}"
: "${MINA_CONTROL_PLANE_URL:?Set the Control Plane URL}"
: "${MINA_CONTROL_PLANE_KEY:?Set the deployment credential}"
: "${MINA_DATA_PLANE:?Set the data-plane ID}"
: "${MINA_CAPABILITY_ID:?Set the capability ID}"
: "${MINA_NAMESPACE:?Set the namespace}"

shopt -s nullglob
archives=("$artifact_dir"/*.ear)
if [[ ${#archives[@]} -ne 1 ]]; then
  echo "Expected one EAR in $artifact_dir" >&2
  exit 1
fi
# Check the exact archive we will upload, including its checksum entry.
if ! (cd "$artifact_dir" && sha256sum --check --strict SHA256SUMS \
  && expected=$(sha256sum -- "${archives[0]##*/}") \
  && [[ "$expected" == "$(cat SHA256SUMS)" ]]); then
  echo "SHA256SUMS must contain one valid entry for ${archives[0]##*/}" >&2
  exit 1
fi

umask 077
secrets_file=$(mktemp)
trap 'rm -f -- "$secrets_file"' EXIT
deployment_secrets="${MINA_DEPLOYMENT_SECRETS_JSON:-}"
if [[ -z "$deployment_secrets" ]]; then deployment_secrets='{}'; fi
printf '%s' "$deployment_secrets" > "$secrets_file"
unset deployment_secrets MINA_DEPLOYMENT_SECRETS_JSON
export MINA_SECRETS_FILE="$secrets_file" MINA_START_AFTER_DEPLOY=true MINA_INSTANCES=1
deploy_script="$(cd "$(dirname "$0")/../linux" && pwd)/deploy-application.sh"
if ! deployment=$(bash "$deploy_script" "${archives[0]}" "$profile"); then
  printf '%s\n' "$deployment" >&2
  exit 1
fi
printf '%s\n' "$deployment"
deployment_id=$(sed -n 's/^Deployment ID: //p' <<< "$deployment")
[[ "$deployment_id" =~ ^[A-Za-z0-9_-]+$ ]]
if [[ -n "${MINA_DEPLOYMENT_ID_FILE:-}" ]]; then
  printf '%s\n' "$deployment_id" > "$MINA_DEPLOYMENT_ID_FILE"
fi

for ((attempt=1; attempt<=24; attempt++)); do
  response=$(curl --fail --silent --show-error --max-time 10 \
    -H "X-Admin-Key: $MINA_CONTROL_PLANE_KEY" \
    "${MINA_CONTROL_PLANE_URL%/}/api/deployments/$deployment_id/health") || response='{}'
  status=$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("status","UNKNOWN"))' <<< "$response")
  if [[ "$status" == HEALTHY ]]; then
    echo "MINA deployment $deployment_id reports HEALTHY"
    exit 0
  fi
  sleep 5
done
echo "MINA deployment $deployment_id did not become healthy. Last status: $status" >&2
exit 1
