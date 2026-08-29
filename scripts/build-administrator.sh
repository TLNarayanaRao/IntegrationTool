#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ADMIN="$ROOT/administrator"
cd "$ADMIN"
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller
pyinstaller --noconfirm --clean --name IntegrationFabricAdministrator --add-data "$ADMIN/web:web" --paths "$ADMIN" run_admin.py
mkdir -p "$ADMIN/dist/IntegrationFabricAdministrator/bin" "$ADMIN/release"
cp "$ADMIN/bin/fabricadmin" "$ADMIN/dist/IntegrationFabricAdministrator/bin/fabricadmin"
chmod +x "$ADMIN/dist/IntegrationFabricAdministrator/bin/fabricadmin"
tar -C "$ADMIN/dist" -czf "$ADMIN/release/IntegrationFabricAdministrator-Linux-x64.tar.gz" IntegrationFabricAdministrator
echo "Linux Administrator ready: $ADMIN/dist/IntegrationFabricAdministrator/IntegrationFabricAdministrator"
echo "Linux distribution: $ADMIN/release/IntegrationFabricAdministrator-Linux-x64.tar.gz"
