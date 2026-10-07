#!/usr/bin/env bash
set -euo pipefail

# Self-contained Linux Control Plane build. This script does not call
# build-administrator.sh, which may be an older Windows copy.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ADMIN="$ROOT/administrator"
VERSION="${1:-${MINA_VERSION:-2.4.0}}"
PYTHON="${MINA_PYTHON:-python3}"
PIP_INDEX_ARGS=()
if [[ -n "${MINA_PYPI_INDEX_URL:-}" ]]; then PIP_INDEX_ARGS=(--index-url "$MINA_PYPI_INDEX_URL"); fi
if [[ -n "${MINA_WHEELHOUSE:-}" ]]; then PIP_INDEX_ARGS+=(--no-index --find-links "$MINA_WHEELHOUSE"); fi

[[ "$VERSION" =~ ^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$ ]] || { echo "Invalid semantic version: $VERSION" >&2; exit 2; }
command -v "$PYTHON" >/dev/null 2>&1 || { echo "Python executable not found: $PYTHON" >&2; exit 2; }
"$PYTHON" -c 'import sys; raise SystemExit("Python 3.10 or newer is required; found %s" % sys.version.split()[0] if sys.version_info < (3, 10) else 0)'
[[ -f "$ADMIN/bin/minaadmin" ]] || { echo "Required file is missing: $ADMIN/bin/minaadmin" >&2; exit 2; }
[[ -d "$ADMIN/web" ]] || { echo "Required folder is missing: $ADMIN/web" >&2; exit 2; }

cd "$ADMIN"
[[ -x .venv/bin/python ]] || "$PYTHON" -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip "${PIP_INDEX_ARGS[@]}"
python -m pip install -r requirements.txt "pyinstaller>=6.15,<7" "${PIP_INDEX_ARGS[@]}"
mkdir -p "$ADMIN/build"
printf '{"version":"%s","builtAt":"%s"}\n' "$VERSION" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$ADMIN/build/build_info.json"
pyinstaller --noconfirm --clean --name MinaAdministrator \
  --add-data "$ADMIN/web:web" --add-data "$ADMIN/build/build_info.json:." \
  --paths "$ADMIN" run_admin.py
mkdir -p "$ADMIN/dist/MinaAdministrator/bin" "$ADMIN/release"
cp "$ADMIN/bin/minaadmin" "$ADMIN/dist/MinaAdministrator/bin/minaadmin"
chmod +x "$ADMIN/dist/MinaAdministrator/bin/minaadmin"
cp "$ROOT/scripts/linux/mina-control-plane.ini" "$ADMIN/dist/MinaAdministrator/mina-control-plane.ini"
cp "$ROOT/scripts/linux/start-control-plane.sh" "$ADMIN/dist/MinaAdministrator/start-control-plane.sh"
chmod +x "$ADMIN/dist/MinaAdministrator/start-control-plane.sh"
tar -C "$ADMIN/dist" -czf "$ADMIN/release/MinaAdministrator-$VERSION-Linux-x64.tar.gz" MinaAdministrator
echo "Linux Administrator $VERSION ready: $ADMIN/release/MinaAdministrator-$VERSION-Linux-x64.tar.gz"
