#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-/home/ken/miniconda3/envs/openclaw/bin/python}"
LOG_FILE="${FUNASR_LOG_FILE:-$ROOT_DIR/data/funasr_server.log}"
PID_FILE="${FUNASR_PID_FILE:-$ROOT_DIR/data/funasr_server.pid}"

mkdir -p "$ROOT_DIR/data"

if [[ -f "$PID_FILE" ]]; then
  old_pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -n "$old_pid" ]] && kill -0 "$old_pid" 2>/dev/null; then
    echo "FunASR server already running, PID=$old_pid"
    exit 0
  fi
fi

export FUNASR_HOST="${FUNASR_HOST:-127.0.0.1}"
export FUNASR_PORT="${FUNASR_PORT:-18002}"
export FUNASR_MODEL="${FUNASR_MODEL:-paraformer-zh}"
export FUNASR_VAD_MODEL="${FUNASR_VAD_MODEL:-fsmn-vad}"
export FUNASR_PUNC_MODEL="${FUNASR_PUNC_MODEL:-ct-punc}"
export FUNASR_DEVICE="${FUNASR_DEVICE:-cuda:0}"
export FUNASR_NCPU="${FUNASR_NCPU:-6}"
export FUNASR_PRELOAD="${FUNASR_PRELOAD:-true}"

if curl -fsS "http://${FUNASR_HOST}:${FUNASR_PORT}/health" >/dev/null 2>&1; then
  port_pid=""
  if command -v ss >/dev/null 2>&1; then
    port_pid="$(ss -ltnp "sport = :${FUNASR_PORT}" 2>/dev/null | sed -n 's/.*pid=\([0-9][0-9]*\).*/\1/p' | head -n 1)"
  fi
  if [[ -n "$port_pid" ]]; then
    echo "$port_pid" > "$PID_FILE"
    echo "FunASR server already healthy, PID=$port_pid, URL=http://${FUNASR_HOST}:${FUNASR_PORT}"
  else
    echo "FunASR server already healthy, URL=http://${FUNASR_HOST}:${FUNASR_PORT}"
  fi
  exit 0
fi

setsid "$PYTHON_BIN" "$ROOT_DIR/scripts/funasr_openai_server.py" >"$LOG_FILE" 2>&1 < /dev/null &
pid="$!"
echo "$pid" > "$PID_FILE"

deadline=$((SECONDS + ${FUNASR_STARTUP_TIMEOUT:-180}))
while (( SECONDS < deadline )); do
  if ! kill -0 "$pid" 2>/dev/null; then
    echo "FunASR server exited during startup, log=$LOG_FILE" >&2
    rm -f "$PID_FILE"
    exit 1
  fi
  if curl -fsS "http://${FUNASR_HOST}:${FUNASR_PORT}/health" >/dev/null 2>&1; then
    echo "FunASR server started, PID=$pid, URL=http://${FUNASR_HOST}:${FUNASR_PORT}, device=${FUNASR_DEVICE}, log=$LOG_FILE"
    exit 0
  fi
  sleep 2
done

echo "FunASR server startup timed out, PID=$pid, log=$LOG_FILE" >&2
exit 1
