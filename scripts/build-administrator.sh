#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ADMIN="$ROOT/administrator"
VERSION="${FABRIC_VERSION:-${1:-2.1.0}}"
if [[ ! "$VERSION" =~ ^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$ ]]; then
  echo "Invalid semantic version: $VERSION" >&2
  exit 2
fi
cd "$ADMIN"
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller
mkdir -p "$ADMIN/build"
printf '{"version":"%s","builtAt":"%s"}\n' "$VERSION" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$ADMIN/build/build_info.json"
pyinstaller --noconfirm --clean --name IntegrationFabricAdministrator --add-data "$ADMIN/web:web" --add-data "$ADMIN/build/build_info.json:." --paths "$ADMIN" run_admin.py
mkdir -p "$ADMIN/dist/IntegrationFabricAdministrator/bin" "$ADMIN/release"
cp "$ADMIN/bin/fabricadmin" "$ADMIN/dist/IntegrationFabricAdministrator/bin/fabricadmin"
chmod +x "$ADMIN/dist/IntegrationFabricAdministrator/bin/fabricadmin"
tar -C "$ADMIN/dist" -czf "$ADMIN/release/IntegrationFabricAdministrator-$VERSION-Linux-x64.tar.gz" IntegrationFabricAdministrator
echo "Linux Administrator $VERSION ready: $ADMIN/dist/IntegrationFabricAdministrator/IntegrationFabricAdministrator"
echo "Linux distribution: $ADMIN/release/IntegrationFabricAdministrator-$VERSION-Linux-x64.tar.gz"
