#!/usr/bin/env bash
# Keep the durable-task worker recoverable when the kernel kills a memory-heavy
# child. ctl.sh owns the supervisor PID, so stop/restart remain unchanged.
set -u -o pipefail

PYTHON_BIN="$1"
CONFIG_PATH="$2"
WORKER_NAME="$3"
RESTART_DELAY_SECONDS="${4:-15}"
child_pid=""

stop_child() {
  if [[ -n "$child_pid" ]] && kill -0 "$child_pid" 2>/dev/null; then
    kill "$child_pid" 2>/dev/null || true
    wait "$child_pid" 2>/dev/null || true
  fi
  exit 0
}
trap stop_child INT TERM

while true; do
  "$PYTHON_BIN" -m kenradar --config "$CONFIG_PATH" worker --name "$WORKER_NAME" &
  child_pid="$!"
  wait "$child_pid"
  exit_code="$?"
  child_pid=""
  if [[ "$exit_code" -eq 0 ]]; then
    exit 0
  fi
  echo "KenRadar worker 异常退出（code=$exit_code），${RESTART_DELAY_SECONDS}s 后重启" >&2
  sleep "$RESTART_DELAY_SECONDS" &
  wait "$!" || exit 0
done
