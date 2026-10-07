#!/usr/bin/env bash
# Compatibility entry: now installs only the Control Plane. Data Planes are separate.
set -Eeuo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${MINA_PYTHON:-python3}" "$SCRIPT_DIR/mina-setup.py" control-plane --config "${MINA_CONFIG_FILE:-$SCRIPT_DIR/mina-control-plane.ini}" "$@"
