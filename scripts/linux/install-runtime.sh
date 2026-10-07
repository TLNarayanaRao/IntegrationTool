#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="${MINA_INSTALL_ROOT:?Set install_root in the INI}"
SOURCE_ROOT="${MINA_SOURCE_ROOT:?Set source_root in the INI}"
PYTHON="${MINA_PYTHON:-python3}"
RUNTIME="$ROOT/runtime"
DRIVERS="${MINA_DRIVER_HOME:-$ROOT/drivers}"
[[ -f "$SOURCE_ROOT/backend/run_deployment.py" && -f "$SOURCE_ROOT/backend/requirements.txt" ]] || { echo 'Missing backend source or requirements' >&2; exit 1; }
mkdir -p "$RUNTIME/data" "$ROOT/logs/runtime" "$DRIVERS"
[[ -x "$RUNTIME/.venv/bin/python" ]] || "$PYTHON" -m venv "$RUNTIME/.venv"
if [[ "${MINA_INSTALL_DB2:-false}" == true ]]; then
  cp "$SOURCE_ROOT/backend/requirements.txt" "$RUNTIME/requirements-linux.txt"
else
  sed '/^[[:space:]]*ibm-db[<=>!~]/d' "$SOURCE_ROOT/backend/requirements.txt" > "$RUNTIME/requirements-linux.txt"
fi
PIP_ARGS=()
[[ -z "${MINA_PYPI_INDEX_URL:-}" ]] || PIP_ARGS+=(--index-url "$MINA_PYPI_INDEX_URL")
[[ -z "${MINA_WHEELHOUSE:-}" ]] || PIP_ARGS+=(--no-index --find-links "$MINA_WHEELHOUSE")
"$RUNTIME/.venv/bin/python" -m pip install "${PIP_ARGS[@]}" -r "$RUNTIME/requirements-linux.txt"
{
  printf '#!/usr/bin/env bash\nset -Eeuo pipefail\n'
  printf 'export PYTHONPATH=%q\nexport MINA_DRIVER_HOME=%q\n' "$SOURCE_ROOT/backend" "$DRIVERS"
  printf 'exec %q %q "$@"\n' "$RUNTIME/.venv/bin/python" "$SOURCE_ROOT/backend/run_deployment.py"
} > "$RUNTIME/mina-runtime"
chmod 755 "$RUNTIME/mina-runtime"
if [[ "${MINA_BUILD_JAVA_BRIDGE:-false}" == true ]]; then
  command -v javac >/dev/null || { echo 'JDK 17+ is required for build_java_bridge=true' >&2; exit 1; }
  mkdir -p "${MINA_JAVA_BRIDGE_HOME:?}/classes"
  javac -encoding UTF-8 -d "$MINA_JAVA_BRIDGE_HOME/classes" "$SOURCE_ROOT/java-bridge/src/com/mina/bridge/MinaJavaBridge.java"
fi
