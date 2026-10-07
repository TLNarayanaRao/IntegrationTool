#!/usr/bin/env bash
# Compatibility alias; Linux builds have one implementation.
set -Eeuo pipefail
exec bash "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/build-administrator-linux.sh" "$@"
