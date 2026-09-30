#!/usr/bin/env bash
set -euo pipefail
shopt -s extglob

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INI_FILE="${MINA_ADMIN_INI:-$SCRIPT_DIR/mina-control-plane.ini}"
[[ -f "$INI_FILE" ]] || { echo "Configuration file not found: $INI_FILE" >&2; exit 1; }

ini_value() {
  local wanted_section="$1" wanted_key="$2" section="" line key value
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"
    line="${line#${line%%[![:space:]]*}}"
    [[ -z "$line" || "$line" == \#* || "$line" == \;* ]] && continue
    if [[ "$line" =~ ^\[([^]]+)\]$ ]]; then section="${BASH_REMATCH[1]}"; continue; fi
    [[ "$section" == "$wanted_section" && "$line" == *=* ]] || continue
    key="${line%%=*}"; value="${line#*=}"
    key="${key##+([[:space:]])}"; key="${key%%+([[:space:]])}"
    value="${value#${value%%[![:space:]]*}}"; value="${value%%+([[:space:]])}"
    [[ "$key" == "$wanted_key" ]] || continue
    if [[ "$value" == \"*\" && "$value" == *\" ]]; then value="${value:1:${#value}-2}"; fi
    printf '%s' "$value"; return 0
  done < "$INI_FILE"
}

ini_value_or_empty() { ini_value "$1" "$2" || true; }
INSTALL_ROOT="${MINA_INSTALL_ROOT:-$(ini_value_or_empty setup install_root)}"
[[ -n "$INSTALL_ROOT" ]] || INSTALL_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
export MINA_INSTALL_ROOT="$INSTALL_ROOT"

configured_home="$(ini_value_or_empty control-plane home)"
configured_data="$(ini_value_or_empty control-plane data_dir)"
configured_log="$(ini_value_or_empty control-plane log_dir)"
configured_pid="$(ini_value_or_empty control-plane pid_dir)"
export MINA_ADMIN_HOST="$(ini_value_or_empty control-plane host)"
export MINA_ADMIN_PORT="$(ini_value_or_empty control-plane port)"
export MINA_ADMIN_HOME="${configured_home:-$INSTALL_ROOT/control-plane}"
export MINA_ADMIN_DATA_DIR="${configured_data:-$INSTALL_ROOT/control-plane-data}"
export MINA_ADMIN_LOG_DIR="${configured_log:-$INSTALL_ROOT/logs/control-plane}"
export MINA_ADMIN_PID_DIR="${configured_pid:-$INSTALL_ROOT/run}"
export MINA_ADMIN_API_KEY="$(ini_value control-plane api_key)"
export MINA_ADMIN_SECRET_KEY="$(ini_value control-plane secret_key)"
configured_runtime_data="$(ini_value_or_empty runtime data_dir)"
configured_runtime_log="$(ini_value_or_empty runtime log_dir)"
configured_driver_home="$(ini_value_or_empty runtime driver_home)"
export MINA_DATA_DIR="${configured_runtime_data:-$INSTALL_ROOT/runtime/data}"
export MINA_RUNTIME_LOG_DIR="${configured_runtime_log:-$INSTALL_ROOT/logs/runtime}"
export MINA_DRIVER_HOME="${configured_driver_home:-$INSTALL_ROOT/drivers}"
runtime_command="$(ini_value_or_empty control-plane runtime_command)"
[[ -n "$runtime_command" ]] || runtime_command="$INSTALL_ROOT/runtime/mina-runtime --application {application} --environment {environment}"
if [[ -n "$runtime_command" ]]; then export MINA_ADMIN_RUNTIME_COMMAND="$runtime_command"; else unset MINA_ADMIN_RUNTIME_COMMAND; fi

EXECUTABLE="$MINA_ADMIN_HOME/mina-control-plane"
if [[ ! -x "$EXECUTABLE" && -x "$MINA_ADMIN_HOME/MinaAdministrator" ]]; then
  EXECUTABLE="$MINA_ADMIN_HOME/MinaAdministrator"
fi
PID_FILE="$MINA_ADMIN_PID_DIR/control-plane.pid"
PROCESS_LOG="$MINA_ADMIN_LOG_DIR/administrator.log"
mkdir -p "$MINA_ADMIN_DATA_DIR" "$MINA_ADMIN_LOG_DIR" "$MINA_ADMIN_PID_DIR"
running() { [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; }
start() { if running; then echo "Already running (PID $(cat "$PID_FILE"))"; return; fi; [[ -x "$EXECUTABLE" ]] || { echo "Executable not found: $EXECUTABLE" >&2; return 1; }; nohup "$EXECUTABLE" >> "$PROCESS_LOG" 2>&1 & echo $! > "$PID_FILE"; echo "Started (PID $(cat "$PID_FILE"))"; }
stop() { if ! running; then echo "Already stopped"; rm -f "$PID_FILE"; return; fi; kill "$(cat "$PID_FILE")"; for _ in {1..30}; do running || break; sleep 1; done; running && { echo "Did not stop gracefully" >&2; return 1; }; rm -f "$PID_FILE"; echo "Stopped"; }
status() { if running; then echo "RUNNING PID $(cat "$PID_FILE")"; else echo "STOPPED"; fi; }
case "${1:-start}" in start) start;; stop) stop;; restart) stop; start;; status) status;; *) echo "Usage: $0 {start|stop|restart|status}" >&2; exit 2;; esac
