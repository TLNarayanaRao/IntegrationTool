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

export MINA_ADMIN_HOST="$(ini_value control-plane host)"
export MINA_ADMIN_PORT="$(ini_value control-plane port)"
export MINA_ADMIN_HOME="$(ini_value control-plane home)"
export MINA_ADMIN_DATA_DIR="$(ini_value control-plane data_dir)"
export MINA_ADMIN_LOG_DIR="$(ini_value control-plane log_dir)"
export MINA_ADMIN_PID_DIR="$(ini_value control-plane pid_dir)"
export MINA_ADMIN_API_KEY="$(ini_value control-plane api_key)"
export MINA_ADMIN_SECRET_KEY="$(ini_value control-plane secret_key)"
export MINA_DATA_DIR="$(ini_value runtime data_dir)"
export MINA_RUNTIME_LOG_DIR="$(ini_value runtime log_dir)"
export MINA_DRIVER_HOME="$(ini_value runtime driver_home)"
runtime_command="$(ini_value control-plane runtime_command)"
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
