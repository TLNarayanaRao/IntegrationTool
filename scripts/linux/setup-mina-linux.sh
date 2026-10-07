#!/usr/bin/env bash
# Legacy alias. See docs/LINUX_SETUP.md; configure version in the INI.
set -Eeuo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${MINA_PYTHON:-python3}" "$SCRIPT_DIR/mina-setup.py" control-plane --config "${MINA_CONFIG_FILE:-$SCRIPT_DIR/mina-control-plane.ini}" "$@"
