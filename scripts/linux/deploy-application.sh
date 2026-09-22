#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
[[ -f "$SCRIPT_DIR/_load-linux-config.sh" ]] && source "$SCRIPT_DIR/_load-linux-config.sh"

# Upload, create, and start an MINA application deployment.
# No systemctl is used.
# Usage: ./deploy-application.sh <package.mpkg|package.ear> <environment> (legacy .ifpkg is accepted)
# Required: FABRIC_CONTROL_PLANE_KEY (or FABRIC_ADMIN_API_KEY)
# Optional: FABRIC_CONTROL_PLANE_URL, FABRIC_DATA_PLANE, FABRIC_NAMESPACE,
#           FABRIC_CAPABILITY_ID, FABRIC_TEAM_ID, FABRIC_INSTANCES,
#           FABRIC_SECRETS_FILE, FABRIC_START_AFTER_DEPLOY=false

BASE_URL="${FABRIC_CONTROL_PLANE_URL:-${CONTROL_PLANE_URL:-http://localhost:19080}}"; BASE_URL="${BASE_URL%/}"
KEY="${FABRIC_CONTROL_PLANE_KEY:-${FABRIC_ADMIN_API_KEY:-${ADMIN_KEY:-}}}"
PACKAGE_FILE="${1:-}"; ENVIRONMENT="${2:-dev}"
DATA_PLANE="${FABRIC_DATA_PLANE:-${DATA_PLANE_ID:-localhost}}"; NAMESPACE="${FABRIC_NAMESPACE:-${DATA_PLANE_NAMESPACE:-default}}"
CAPABILITY_ID="${FABRIC_CAPABILITY_ID:-${FABRIC_CAPABILITY_ID_OVERRIDE:-integration-runtime-${DATA_PLANE}-${NAMESPACE}}}"; TEAM_ID="${FABRIC_TEAM_ID:-${DELIVERY_TEAM_ID:-}}"
INSTANCES="${FABRIC_INSTANCES:-1}"; SECRETS_FILE="${FABRIC_SECRETS_FILE:-}"
START="${FABRIC_START_AFTER_DEPLOY:-true}"
die() { echo "ERROR: $*" >&2; exit 1; }
command -v curl >/dev/null 2>&1 || die "curl is required"
command -v python3 >/dev/null 2>&1 || die "python3 is required"
[[ -f "$PACKAGE_FILE" ]] || die "Package not found. Usage: $0 <package> <environment>"
[[ -n "$KEY" ]] || die "Set FABRIC_CONTROL_PLANE_KEY"
[[ "$INSTANCES" =~ ^[1-9][0-9]*$ ]] || die "FABRIC_INSTANCES must be a positive integer"
AUTH=(-H "X-Admin-Key: $KEY")

# Step 1: verify the target Control Plane is reachable.
curl --fail-with-body --silent --show-error "${AUTH[@]}" "$BASE_URL/api/health" >/dev/null || die "Control Plane is unreachable: $BASE_URL"

# Step 2: upload and validate the package.
echo "Uploading $PACKAGE_FILE"
UPLOAD_URL="$BASE_URL/api/packages"; [[ -n "$TEAM_ID" ]] && UPLOAD_URL="$UPLOAD_URL?teamId=$TEAM_ID"
UPLOAD="$(curl --fail-with-body --silent --show-error -X POST "${AUTH[@]}" -F "file=@$PACKAGE_FILE" "$UPLOAD_URL")" || die "Package upload failed"
PACKAGE_ID="$(printf '%s' "$UPLOAD" | python3 -c 'import json,sys; print(json.load(sys.stdin)["packageId"])')" || die "Upload response has no packageId: $UPLOAD"
echo "Package: $PACKAGE_ID"

# Step 3: prepare deployment secrets, if supplied. The file must be one JSON object.
SECRETS='{}'
if [[ -n "$SECRETS_FILE" ]]; then
  [[ -f "$SECRETS_FILE" ]] || die "Secrets file not found: $SECRETS_FILE"
  SECRETS="$(python3 -c 'import json,sys; value=json.load(open(sys.argv[1])); assert isinstance(value,dict); print(json.dumps(value,separators=(",",":")))' "$SECRETS_FILE")" || die "Secrets file must contain a JSON object"
fi
DEPLOYMENT="$(PACKAGE_ID="$PACKAGE_ID" ENVIRONMENT="$ENVIRONMENT" DATA_PLANE="$DATA_PLANE" NAMESPACE="$NAMESPACE" CAPABILITY_ID="$CAPABILITY_ID" TEAM_ID="$TEAM_ID" INSTANCES="$INSTANCES" SECRETS="$SECRETS" python3 -c '
import json,os
d={"packageId":os.environ["PACKAGE_ID"],"environment":os.environ["ENVIRONMENT"],"dataPlaneId":os.environ["DATA_PLANE"],"namespace":os.environ["NAMESPACE"],"instances":int(os.environ["INSTANCES"]),"secrets":json.loads(os.environ["SECRETS"])}
if os.environ.get("CAPABILITY_ID"): d["capabilityId"]=os.environ["CAPABILITY_ID"]
if os.environ.get("TEAM_ID"): d["teamId"]=os.environ["TEAM_ID"]
print(json.dumps(d,separators=(",",":")))
')"

# Step 4: create the deployment and capture its deployment ID.
echo "Creating deployment"
CREATED="$(curl --fail-with-body --silent --show-error -X POST "${AUTH[@]}" -H 'Content-Type: application/json' -d "$DEPLOYMENT" "$BASE_URL/api/deployments")" || die "Deployment creation failed"
DEPLOYMENT_ID="$(printf '%s' "$CREATED" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')" || die "Deployment response has no id: $CREATED"
echo "Deployment ID: $DEPLOYMENT_ID"

# Step 5: start the application unless explicitly disabled.
if [[ "$START" == "true" ]]; then
  echo "Starting deployment"
  curl --fail-with-body --silent --show-error -X POST "${AUTH[@]}" "$BASE_URL/api/deployments/$DEPLOYMENT_ID/start" >/dev/null || die "Deployment created but start failed"
  echo "Deployment started"
else
  echo "Deployment created but not started (FABRIC_START_AFTER_DEPLOY=$START)"
fi
echo "Details: $BASE_URL/api/deployments/$DEPLOYMENT_ID"
