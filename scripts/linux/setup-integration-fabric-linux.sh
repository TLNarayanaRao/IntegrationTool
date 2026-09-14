#!/usr/bin/env bash
set -Eeuo pipefail

# Integration Fabric Linux environment setup. No systemctl is used.
FABRIC_ROOT="${FABRIC_ROOT:-/opt/tibco/esb/IntegrationFabricSoftware}"
TEMP_ROOT="${FABRIC_TEMP_ROOT:-$FABRIC_ROOT/administrator/release}"
VERSION="${1:-${FABRIC_ADMIN_VERSION:-}}"
PYTHON_BIN="${FABRIC_PYTHON:-/usr/bin/python3.12}"
PORT="${FABRIC_ADMIN_PORT:-19080}"
HOST="${FABRIC_ADMIN_HOST:-0.0.0.0}"
API_KEY="${FABRIC_ADMIN_API_KEY:-dev-api-key-if}"
API_SECRET="${FABRIC_ADMIN_SECRET_KEY:-dev-api-key-if}"
SOURCE_ROOT="${FABRIC_SOURCE_ROOT:-$FABRIC_ROOT}"
CP="$FABRIC_ROOT/control-plane"; DATA="$FABRIC_ROOT/control-plane-data"
RUNTIME="$FABRIC_ROOT/runtime"; DRIVERS="$FABRIC_ROOT/drivers"
LOGS="$FABRIC_ROOT/logs"; PID="$FABRIC_ROOT/run"
ARCHIVE="${FABRIC_ADMIN_ARCHIVE:-}"
die() { echo "ERROR: $*" >&2; exit 1; }
command -v "$PYTHON_BIN" >/dev/null 2>&1 || die "Python interpreter not found: $PYTHON_BIN"
command -v tar >/dev/null 2>&1 || die "tar is required"

# Step 1: locate the Linux Administrator archive or extracted folder copied from Windows.
if [[ -z "$ARCHIVE" ]]; then
  if [[ -n "$VERSION" ]]; then
    ARCHIVE="$TEMP_ROOT/IntegrationFabricAdministrator-${VERSION}-Linux-x64.tar.gz"
  else
    if [[ -d "$TEMP_ROOT" ]]; then
      mapfile -t found < <(find "$TEMP_ROOT" -maxdepth 1 -type f -name 'IntegrationFabricAdministrator-*-Linux-x64.tar.gz' -print | sort)
      [[ "${#found[@]}" -eq 0 ]] || ARCHIVE="${found[0]}"
    fi
  fi
fi
if [[ -n "$ARCHIVE" && ! -f "$ARCHIVE" ]]; then ARCHIVE=""; fi

# Step 1b: if no archive was copied, build the Linux Administrator archive from
# the administrator/ source folder. Set FABRIC_BUILD_ADMIN=false to skip this.
BUILD_SCRIPT=""
for candidate in \
  "$FABRIC_ROOT/scripts/linux/build-administrator-linux.sh" \
  "$FABRIC_ROOT/scripts/build-administrator-linux.sh" \
  "$FABRIC_ROOT/build-administrator-linux.sh"; do
  if [[ -f "$candidate" ]]; then BUILD_SCRIPT="$candidate"; break; fi
done
if [[ -z "$ARCHIVE" && "${FABRIC_BUILD_ADMIN:-true}" == "true" && -n "$BUILD_SCRIPT" ]]; then
  BUILD_VERSION="${VERSION:-${FABRIC_VERSION:-2.4.0}}"
  echo "Administrator archive not found; building Linux Administrator $BUILD_VERSION"
  chmod +x "$BUILD_SCRIPT"
  FABRIC_PYTHON="$PYTHON_BIN" "$BUILD_SCRIPT" "$BUILD_VERSION"
  ARCHIVE="$FABRIC_ROOT/administrator/release/IntegrationFabricAdministrator-${BUILD_VERSION}-Linux-x64.tar.gz"
fi
if [[ -n "$ARCHIVE" && ! -f "$ARCHIVE" ]]; then ARCHIVE=""; fi

# Step 2: create all directories used by the Control Plane and runtime.
mkdir -p "$CP" "$DATA" "$RUNTIME/data" "$RUNTIME/logs" "$FABRIC_ROOT/apps" "$DRIVERS" "$LOGS/control-plane" "$LOGS/runtime" "$PID"

# Step 3: extract the Administrator package, or use an already extracted folder.
STAGE="$(mktemp -d)"; trap 'rm -rf "$STAGE"' EXIT
if [[ -n "$ARCHIVE" ]]; then
  echo "Using Administrator archive: $ARCHIVE"
  tar -xzf "$ARCHIVE" -C "$STAGE"
  ADMIN="$(find "$STAGE" -type f -name IntegrationFabricAdministrator -print -quit)"
else
  ADMIN="$(find "$FABRIC_ROOT/administrator" -type f -name IntegrationFabricAdministrator -print -quit 2>/dev/null || true)"
  [[ -n "$ADMIN" ]] || die "No Linux Administrator input found. Copy the Linux build script to $FABRIC_ROOT/scripts/linux/build-administrator-linux.sh and the administrator source folder to $FABRIC_ROOT/administrator, or copy IntegrationFabricAdministrator and _internal/ below $FABRIC_ROOT/administrator, or set FABRIC_ADMIN_ARCHIVE."
  echo "Using extracted Administrator folder: $(dirname "$ADMIN")"
fi
[[ -n "$ADMIN" ]] || die "IntegrationFabricAdministrator was not found in the Administrator package"
cp -a "$(dirname "$ADMIN")"/. "$CP/"
[[ -f "$CP/IntegrationFabricAdministrator" ]] && cp -f "$CP/IntegrationFabricAdministrator" "$CP/integration-fabric-control-plane"
chmod 755 "$CP/IntegrationFabricAdministrator" "$CP/integration-fabric-control-plane" 2>/dev/null || true
[[ -x "$CP/integration-fabric-control-plane" ]] || die "Administrator executable was not installed"

# Step 4: verify the source needed to execute deployed applications.
[[ -f "$SOURCE_ROOT/backend/run_deployment.py" ]] || die "Missing $SOURCE_ROOT/backend/run_deployment.py"
[[ -f "$SOURCE_ROOT/backend/requirements.txt" ]] || die "Missing $SOURCE_ROOT/backend/requirements.txt"

# Step 5: create the Linux runtime virtual environment and install dependencies.
[[ -x "$RUNTIME/.venv/bin/python" ]] || "$PYTHON_BIN" -m venv "$RUNTIME/.venv"
RUNTIME_REQUIREMENTS="$RUNTIME/requirements-linux.txt"
if [[ "${FABRIC_INSTALL_DB2:-false}" == "true" ]]; then
  cp "$SOURCE_ROOT/backend/requirements.txt" "$RUNTIME_REQUIREMENTS"
else
  # ibm-db downloads and compiles the IBM DB2 CLI driver and requires gcc.
  # It is optional unless an application actually uses a DB2 connection.
  sed '/^[[:space:]]*ibm-db[<=>!~]/d' "$SOURCE_ROOT/backend/requirements.txt" > "$RUNTIME_REQUIREMENTS"
  echo "Skipping optional ibm-db; set FABRIC_INSTALL_DB2=true when gcc and DB2 build prerequisites are available."
fi
"$RUNTIME/.venv/bin/python" -m pip install -r "$RUNTIME_REQUIREMENTS"

# Step 6: create the runtime adapter used when the Control Plane starts apps.
cat > "$RUNTIME/integration-fabric-runtime" <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail
export PYTHONPATH="$SOURCE_ROOT/backend"
export FABRIC_DRIVER_HOME="$DRIVERS"
exec "$RUNTIME/.venv/bin/python" "$SOURCE_ROOT/backend/run_deployment.py" "\$@"
EOF
chmod 755 "$RUNTIME/integration-fabric-runtime"

# Step 7: write one authoritative direct-run INI configuration.
cat > "$CP/integration-fabric-control-plane.ini" <<EOF
# Direct-run configuration. Start with start-control-plane.sh; do not use systemctl.
[control-plane]
host=$HOST
port=$PORT
home=$CP
data_dir=$DATA
log_dir=$LOGS/control-plane
pid_dir=$PID
api_key=$API_KEY
secret_key=$API_SECRET
runtime_command=$RUNTIME/integration-fabric-runtime --application {application} --environment {environment}

[runtime]
data_dir=$RUNTIME/data
log_dir=$LOGS/runtime
driver_home=$DRIVERS
EOF
chmod 600 "$CP/integration-fabric-control-plane.ini"

# Step 8: verify setup before startup.
[[ -x "$RUNTIME/integration-fabric-runtime" ]] || die "Runtime adapter is not executable"
echo "Setup complete. Start: $CP/start-control-plane.sh start &"
echo "Health: curl http://localhost:$PORT/api/health"
