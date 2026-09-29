#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ADMIN="$ROOT/administrator"
VERSION="${MINA_VERSION:-${1:-2.1.0}}"
PYTHON="${MINA_PYTHON:-python3}"
PIP_INDEX_ARGS=()
if [[ -n "${MINA_PYPI_INDEX_URL:-}" ]]; then
  PIP_INDEX_ARGS=(--index-url "$MINA_PYPI_INDEX_URL")
fi
if [[ ! "$VERSION" =~ ^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$ ]]; then
  echo "Invalid semantic version: $VERSION" >&2
  exit 2
fi
if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "Python executable not found: $PYTHON" >&2
  echo "Install Python 3.10 or newer, or set MINA_PYTHON to its executable." >&2
  exit 2
fi
"$PYTHON" -c 'import sys; raise SystemExit("Python 3.10 or newer is required; found %s" % sys.version.split()[0] if sys.version_info < (3, 10) else 0)'
cd "$ADMIN"
"$PYTHON" -m venv --clear .venv
. .venv/bin/activate
python -m pip install --upgrade pip "${PIP_INDEX_ARGS[@]}"
python -m pip install -r requirements.txt "pyinstaller>=6.15,<7" "${PIP_INDEX_ARGS[@]}"
mkdir -p "$ADMIN/build"
printf '{"version":"%s","builtAt":"%s"}\n' "$VERSION" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$ADMIN/build/build_info.json"
pyinstaller --noconfirm --clean --name MinaAdministrator --add-data "$ADMIN/web:web" --add-data "$ADMIN/build/build_info.json:." --paths "$ADMIN" run_admin.py
if [[ ! -f "$ADMIN/bin/minaadmin" ]]; then
  echo "Required Linux launcher is missing: $ADMIN/bin/minaadmin" >&2
  echo "Copy administrator/bin/minaadmin from the canonical Software source before building." >&2
  exit 2
fi
mkdir -p "$ADMIN/dist/MinaAdministrator/bin" "$ADMIN/release"
cp "$ADMIN/bin/minaadmin" "$ADMIN/dist/MinaAdministrator/bin/minaadmin"
chmod +x "$ADMIN/dist/MinaAdministrator/bin/minaadmin"
cp "$ROOT/scripts/linux/mina-control-plane.ini" "$ADMIN/dist/MinaAdministrator/mina-control-plane.ini"
cp "$ROOT/scripts/linux/start-control-plane.sh" "$ADMIN/dist/MinaAdministrator/start-control-plane.sh"
chmod +x "$ADMIN/dist/MinaAdministrator/start-control-plane.sh"
tar -C "$ADMIN/dist" -czf "$ADMIN/release/MinaAdministrator-$VERSION-Linux-x64.tar.gz" MinaAdministrator
echo "Linux Administrator $VERSION ready: $ADMIN/dist/MinaAdministrator/MinaAdministrator"
echo "Linux distribution: $ADMIN/release/MinaAdministrator-$VERSION-Linux-x64.tar.gz"
