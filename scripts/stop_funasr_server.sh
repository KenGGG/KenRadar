#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PID_FILE="${FUNASR_PID_FILE:-$ROOT_DIR/data/funasr_server.pid}"

if [[ ! -f "$PID_FILE" ]]; then
  echo "FunASR server is not running"
  exit 0
fi

pid="$(cat "$PID_FILE" 2>/dev/null || true)"
if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
  kill "$pid"
  for _ in $(seq 1 20); do
    if ! kill -0 "$pid" 2>/dev/null; then
      break
    fi
    sleep 0.5
  done
  if kill -0 "$pid" 2>/dev/null; then
    kill -9 "$pid" 2>/dev/null || true
  fi
  echo "FunASR server stopped, PID=$pid"
else
  echo "FunASR server is not running"
fi

rm -f "$PID_FILE"
