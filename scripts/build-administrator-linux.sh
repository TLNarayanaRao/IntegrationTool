#!/usr/bin/env bash
set -euo pipefail

# Self-contained Linux Control Plane build. This script does not call
# build-administrator.sh, which may be an older Windows copy.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ADMIN="$ROOT/administrator"
VERSION="${1:-${FABRIC_VERSION:-2.4.0}}"
PYTHON="${FABRIC_PYTHON:-python3}"
PIP_INDEX_ARGS=()
if [[ -n "${FABRIC_PYPI_INDEX_URL:-}" ]]; then PIP_INDEX_ARGS=(--index-url "$FABRIC_PYPI_INDEX_URL"); fi

[[ "$VERSION" =~ ^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$ ]] || { echo "Invalid semantic version: $VERSION" >&2; exit 2; }
command -v "$PYTHON" >/dev/null 2>&1 || { echo "Python executable not found: $PYTHON" >&2; exit 2; }
"$PYTHON" -c 'import sys; raise SystemExit("Python 3.10 or newer is required; found %s" % sys.version.split()[0] if sys.version_info < (3, 10) else 0)'
[[ -f "$ADMIN/bin/fabricadmin" ]] || { echo "Required file is missing: $ADMIN/bin/fabricadmin" >&2; exit 2; }
[[ -d "$ADMIN/web" ]] || { echo "Required folder is missing: $ADMIN/web" >&2; exit 2; }

cd "$ADMIN"
"$PYTHON" -m venv --clear .venv
. .venv/bin/activate
python -m pip install --upgrade pip "${PIP_INDEX_ARGS[@]}"
python -m pip install -r requirements.txt "pyinstaller>=6.15,<7" "${PIP_INDEX_ARGS[@]}"
mkdir -p "$ADMIN/build"
printf '{"version":"%s","builtAt":"%s"}\n' "$VERSION" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$ADMIN/build/build_info.json"
pyinstaller --noconfirm --clean --name IntegrationFabricAdministrator \
  --add-data "$ADMIN/web:web" --add-data "$ADMIN/build/build_info.json:." \
  --paths "$ADMIN" run_admin.py
mkdir -p "$ADMIN/dist/IntegrationFabricAdministrator/bin" "$ADMIN/release"
cp "$ADMIN/bin/fabricadmin" "$ADMIN/dist/IntegrationFabricAdministrator/bin/fabricadmin"
chmod +x "$ADMIN/dist/IntegrationFabricAdministrator/bin/fabricadmin"
cp "$ROOT/scripts/linux/integration-fabric-control-plane.ini" "$ADMIN/dist/IntegrationFabricAdministrator/integration-fabric-control-plane.ini"
cp "$ROOT/scripts/linux/start-control-plane.sh" "$ADMIN/dist/IntegrationFabricAdministrator/start-control-plane.sh"
chmod +x "$ADMIN/dist/IntegrationFabricAdministrator/start-control-plane.sh"
tar -C "$ADMIN/dist" -czf "$ADMIN/release/IntegrationFabricAdministrator-$VERSION-Linux-x64.tar.gz" IntegrationFabricAdministrator
echo "Linux Administrator $VERSION ready: $ADMIN/release/IntegrationFabricAdministrator-$VERSION-Linux-x64.tar.gz"
