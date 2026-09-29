#!/usr/bin/env bash
set -Eeuo pipefail

# MINA Linux environment setup. No systemctl is used.
MINA_ROOT="${MINA_ROOT:-/opt/mina}"
TEMP_ROOT="${MINA_TEMP_ROOT:-$MINA_ROOT/administrator/release}"
VERSION="${1:-${MINA_ADMIN_VERSION:-}}"
PYTHON_BIN="${MINA_PYTHON:-/usr/bin/python3.12}"
PORT="${MINA_ADMIN_PORT:-19080}"
HOST="${MINA_ADMIN_HOST:-0.0.0.0}"
API_KEY="${MINA_ADMIN_API_KEY:-dev-api-key-if}"
API_SECRET="${MINA_ADMIN_SECRET_KEY:-dev-api-key-if}"
SOURCE_ROOT="${MINA_SOURCE_ROOT:-$MINA_ROOT}"
CP="$MINA_ROOT/control-plane"; DATA="$MINA_ROOT/control-plane-data"
RUNTIME="$MINA_ROOT/runtime"; DRIVERS="$MINA_ROOT/drivers"
LOGS="$MINA_ROOT/logs"; PID="$MINA_ROOT/run"
ARCHIVE="${MINA_ADMIN_ARCHIVE:-}"
die() { echo "ERROR: $*" >&2; exit 1; }
command -v "$PYTHON_BIN" >/dev/null 2>&1 || die "Python interpreter not found: $PYTHON_BIN"
command -v tar >/dev/null 2>&1 || die "tar is required"

# Step 1: locate the Linux Administrator archive or extracted folder copied from Windows.
if [[ -z "$ARCHIVE" ]]; then
  if [[ -n "$VERSION" ]]; then
    ARCHIVE="$TEMP_ROOT/MinaAdministrator-${VERSION}-Linux-x64.tar.gz"
  else
    if [[ -d "$TEMP_ROOT" ]]; then
      mapfile -t found < <(find "$TEMP_ROOT" -maxdepth 1 -type f -name 'MinaAdministrator-*-Linux-x64.tar.gz' -print | sort)
      [[ "${#found[@]}" -eq 0 ]] || ARCHIVE="${found[0]}"
    fi
  fi
fi
if [[ -n "$ARCHIVE" && ! -f "$ARCHIVE" ]]; then ARCHIVE=""; fi

# Step 1b: if no archive was copied, build the Linux Administrator archive from
# the administrator/ source folder. Set MINA_BUILD_ADMIN=false to skip this.
BUILD_SCRIPT=""
for candidate in \
  "$MINA_ROOT/scripts/linux/build-administrator-linux.sh" \
  "$MINA_ROOT/scripts/build-administrator-linux.sh" \
  "$MINA_ROOT/build-administrator-linux.sh"; do
  if [[ -f "$candidate" ]]; then BUILD_SCRIPT="$candidate"; break; fi
done
if [[ -z "$ARCHIVE" && "${MINA_BUILD_ADMIN:-true}" == "true" && -n "$BUILD_SCRIPT" ]]; then
  BUILD_VERSION="${VERSION:-${MINA_VERSION:-2.4.0}}"
  echo "Administrator archive not found; building Linux Administrator $BUILD_VERSION"
  chmod +x "$BUILD_SCRIPT"
  MINA_PYTHON="$PYTHON_BIN" "$BUILD_SCRIPT" "$BUILD_VERSION"
  ARCHIVE="$MINA_ROOT/administrator/release/MinaAdministrator-${BUILD_VERSION}-Linux-x64.tar.gz"
fi
if [[ -n "$ARCHIVE" && ! -f "$ARCHIVE" ]]; then ARCHIVE=""; fi

# Step 2: create all directories used by the Control Plane and runtime.
mkdir -p "$CP" "$DATA" "$RUNTIME/data" "$RUNTIME/logs" "$MINA_ROOT/apps" "$DRIVERS" "$LOGS/control-plane" "$LOGS/runtime" "$PID"

# Step 3: extract the Administrator package, or use an already extracted folder.
STAGE="$(mktemp -d)"; trap 'rm -rf "$STAGE"' EXIT
if [[ -n "$ARCHIVE" ]]; then
  echo "Using Administrator archive: $ARCHIVE"
  tar -xzf "$ARCHIVE" -C "$STAGE"
  ADMIN="$(find "$STAGE" -type f -name MinaAdministrator -print -quit)"
else
  ADMIN="$(find "$MINA_ROOT/administrator" -type f -name MinaAdministrator -print -quit 2>/dev/null || true)"
  [[ -n "$ADMIN" ]] || die "No Linux Administrator input found. Copy the Linux build script to $MINA_ROOT/scripts/linux/build-administrator-linux.sh and the administrator source folder to $MINA_ROOT/administrator, or copy MinaAdministrator and _internal/ below $MINA_ROOT/administrator, or set MINA_ADMIN_ARCHIVE."
  echo "Using extracted Administrator folder: $(dirname "$ADMIN")"
fi
[[ -n "$ADMIN" ]] || die "MinaAdministrator was not found in the Administrator package"
cp -a "$(dirname "$ADMIN")"/. "$CP/"
[[ -f "$CP/MinaAdministrator" ]] && cp -f "$CP/MinaAdministrator" "$CP/mina-control-plane"
chmod 755 "$CP/MinaAdministrator" "$CP/mina-control-plane" 2>/dev/null || true
[[ -x "$CP/mina-control-plane" ]] || die "Administrator executable was not installed"

# Step 4: verify the source needed to execute deployed applications.
[[ -f "$SOURCE_ROOT/backend/run_deployment.py" ]] || die "Missing $SOURCE_ROOT/backend/run_deployment.py"
[[ -f "$SOURCE_ROOT/backend/requirements.txt" ]] || die "Missing $SOURCE_ROOT/backend/requirements.txt"

# Step 5: create the Linux runtime virtual environment and install dependencies.
[[ -x "$RUNTIME/.venv/bin/python" ]] || "$PYTHON_BIN" -m venv "$RUNTIME/.venv"
RUNTIME_REQUIREMENTS="$RUNTIME/requirements-linux.txt"
if [[ "${MINA_INSTALL_DB2:-false}" == "true" ]]; then
  cp "$SOURCE_ROOT/backend/requirements.txt" "$RUNTIME_REQUIREMENTS"
else
  # ibm-db downloads and compiles the IBM DB2 CLI driver and requires gcc.
  # It is optional unless an application actually uses a DB2 connection.
  sed '/^[[:space:]]*ibm-db[<=>!~]/d' "$SOURCE_ROOT/backend/requirements.txt" > "$RUNTIME_REQUIREMENTS"
  echo "Skipping optional ibm-db; set MINA_INSTALL_DB2=true when gcc and DB2 build prerequisites are available."
fi
"$RUNTIME/.venv/bin/python" -m pip install -r "$RUNTIME_REQUIREMENTS"

# Step 6: create the runtime adapter used when the Control Plane starts apps.
cat > "$RUNTIME/mina-runtime" <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail
export PYTHONPATH="$SOURCE_ROOT/backend"
export MINA_DRIVER_HOME="$DRIVERS"
exec "$RUNTIME/.venv/bin/python" "$SOURCE_ROOT/backend/run_deployment.py" "\$@"
EOF
chmod 755 "$RUNTIME/mina-runtime"

# Step 7: write one authoritative direct-run INI configuration.
cat > "$CP/mina-control-plane.ini" <<EOF
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
runtime_command=$RUNTIME/mina-runtime --application {application} --environment {environment}

[runtime]
data_dir=$RUNTIME/data
log_dir=$LOGS/runtime
driver_home=$DRIVERS
EOF
chmod 600 "$CP/mina-control-plane.ini"

# Step 8: verify setup before startup.
[[ -x "$RUNTIME/mina-runtime" ]] || die "Runtime adapter is not executable"
echo "Setup complete. Start: $CP/start-control-plane.sh start &"
echo "Health: curl http://localhost:$PORT/api/health"
