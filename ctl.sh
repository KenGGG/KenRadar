#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env}"
if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

CONFIG_PATH="${CONFIG_PATH:-$ROOT_DIR/config/config.yaml}"
PID_FILE="${PID_FILE:-/tmp/kenradar.pid}"
WORKER_PID_FILE="${WORKER_PID_FILE:-/tmp/kenradar-worker.pid}"
LOG_FILE="${LOG_FILE:-$ROOT_DIR/data/kenradar.log}"
MODE="${MODE:-web}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8765}"
DEFAULT_PYTHON="/home/ken/miniconda3/envs/openclaw/bin/python"
if [[ -z "${PYTHON_BIN:-}" && -x "$DEFAULT_PYTHON" ]]; then
  PYTHON_BIN="$DEFAULT_PYTHON"
else
  PYTHON_BIN="${PYTHON_BIN:-python}"
fi

mkdir -p "$ROOT_DIR/data"

usage() {
  cat <<EOF
用法: ./kenradarctl.sh {start|stop|restart|status|logs|start-worker|stop-worker|status-worker|start-funasr|stop-funasr|restart-funasr|status-funasr|logs-funasr}

环境变量:
  MODE=web|schedule        默认 web
  HOST=0.0.0.0             web 模式监听地址（默认 0.0.0.0 开放局域网）
  PORT=8765                web 模式监听端口
  CONFIG_PATH=...          配置文件路径
  PYTHON_BIN=...           Python 命令；默认优先使用 openclaw 环境
  PID_FILE=...             PID 文件路径
  LOG_FILE=...             日志文件路径
  FUNASR_IDLE_TIMEOUT_SECONDS=300 FunASR 空闲退出秒数；0 表示禁用自动退出
  FUNASR_DEVICE=cuda:0     FunASR 按需使用的设备；默认 cuda:0
  FUNASR_PORT=18002        FunASR HTTP 端口

安全说明:
  默认监听 0.0.0.0 开放局域网访问。如需仅限本机，请设置 HOST=127.0.0.1。
  建议在 config.yaml 中设置 app.web_password 添加访问密码。

示例:
  ./kenradarctl.sh start                              # 启动，开放局域网
  HOST=127.0.0.1 ./kenradarctl.sh start               # 启动，仅本机
  MODE=schedule ./kenradarctl.sh restart               # 调度模式
  PYTHON_BIN=/home/ken/miniconda3/envs/openclaw/bin/python ./kenradarctl.sh start
EOF
}

funasr_pid_file() {
  echo "${FUNASR_PID_FILE:-$ROOT_DIR/data/funasr_server.pid}"
}

funasr_log_file() {
  echo "${FUNASR_LOG_FILE:-$ROOT_DIR/data/funasr_server.log}"
}

funasr_is_running() {
  local file pid
  file="$(funasr_pid_file)"
  [[ -f "$file" ]] || return 1
  pid="$(<"$file")"
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

start_funasr() {
  "$ROOT_DIR/scripts/start_funasr_server.sh"
}

stop_funasr() {
  "$ROOT_DIR/scripts/stop_funasr_server.sh"
}

status_funasr() {
  local endpoint="${FUNASR_ENDPOINT:-http://${FUNASR_HOST:-127.0.0.1}:${FUNASR_PORT:-18002}}"
  if funasr_is_running; then
    echo "FunASR 运行中，PID=$(<"$(funasr_pid_file)")，日志: $(funasr_log_file)"
    curl -fsS "$endpoint/health" 2>/dev/null || true
    echo
  else
    echo "FunASR 未运行"
  fi
}

logs_funasr() {
  touch "$(funasr_log_file)"
  tail -f "$(funasr_log_file)"
}

is_running() {
  [[ -f "$PID_FILE" ]] || return 1
  local pid
  pid="$(<"$PID_FILE")"
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

worker_is_running() {
  [[ -f "$WORKER_PID_FILE" ]] || return 1
  local pid
  pid="$(<"$WORKER_PID_FILE")"
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

start_worker() {
  if worker_is_running; then
    echo "KenRadar worker 已在运行，PID=$(<"$WORKER_PID_FILE")"
    return 0
  fi
  (
    cd "$ROOT_DIR"
    setsid nohup "$PYTHON_BIN" -m kenradar --config "$CONFIG_PATH" worker --name "local-worker" >>"$LOG_FILE" 2>&1 &
    echo $! >"$WORKER_PID_FILE"
  )
  sleep 0.5
  if worker_is_running; then
    echo "KenRadar worker 启动成功，PID=$(<"$WORKER_PID_FILE")"
  else
    echo "KenRadar worker 启动失败，请查看日志: $LOG_FILE" >&2
    rm -f "$WORKER_PID_FILE"
    exit 1
  fi
}

stop_worker() {
  if ! worker_is_running; then
    rm -f "$WORKER_PID_FILE"
    echo "KenRadar worker 未运行"
    return 0
  fi
  local pid
  pid="$(<"$WORKER_PID_FILE")"
  kill "$pid" 2>/dev/null || true
  for _ in {1..20}; do
    if ! kill -0 "$pid" 2>/dev/null; then
      rm -f "$WORKER_PID_FILE"
      echo "KenRadar worker 已停止"
      return 0
    fi
    sleep 0.25
  done
  kill -9 "$pid" 2>/dev/null || true
  rm -f "$WORKER_PID_FILE"
}

status_worker() {
  if worker_is_running; then
    echo "KenRadar worker 运行中，PID=$(<"$WORKER_PID_FILE")"
  else
    echo "KenRadar worker 未运行"
  fi
}

web_port_pid() {
  command -v ss >/dev/null 2>&1 || return 1
  ss -ltnp "sport = :$PORT" 2>/dev/null | sed -n 's/.*pid=\([0-9][0-9]*\).*/\1/p' | head -n 1
}

is_kenradar_pid() {
  local pid="${1:-}"
  [[ -n "$pid" ]] || return 1
  local args
  args="$(ps -p "$pid" -o args= 2>/dev/null || true)"
  [[ "$args" == *"kenradar"* && "$args" == *" web "* ]]
}

start() {
  if is_running; then
    echo "KenRadar 已在运行，PID=$(<"$PID_FILE")"
    [[ "$MODE" == "web" ]] && start_worker
    return 0
  fi

  if [[ "$MODE" == "web" ]]; then
    local port_pid
    port_pid="$(web_port_pid || true)"
    if [[ -n "$port_pid" ]]; then
      if is_kenradar_pid "$port_pid"; then
        echo "$port_pid" >"$PID_FILE"
        echo "KenRadar 已在运行，PID=$port_pid"
        if [[ "$HOST" == "0.0.0.0" ]]; then
          echo "Web 地址: http://$(hostname -I 2>/dev/null | awk '{print $1}' || echo '<局域网IP>'):$PORT"
          echo "本机访问: http://127.0.0.1:$PORT"
        else
          echo "Web 地址: http://$HOST:$PORT"
        fi
        return 0
      fi
      echo "端口 $PORT 已被 PID=$port_pid 占用，请先释放端口或设置 PORT=其他端口" >&2
      exit 1
    fi
  fi

  "$PYTHON_BIN" -m kenradar --config "$CONFIG_PATH" migrate >>"$LOG_FILE" 2>&1

  local -a cmd
  if [[ "$MODE" == "web" ]]; then
    export KENRADAR_EMBEDDED_WORKER=0
    cmd=("$PYTHON_BIN" -m kenradar --config "$CONFIG_PATH" web --host "$HOST" --port "$PORT")
  elif [[ "$MODE" == "schedule" ]]; then
    cmd=("$PYTHON_BIN" -m kenradar --config "$CONFIG_PATH" schedule)
  else
    echo "不支持的 MODE: $MODE，仅支持 web 或 schedule" >&2
    exit 2
  fi
  printf '启动 KenRadar: '
  printf '%q ' "${cmd[@]}"
  printf '\n'
  (
    cd "$ROOT_DIR"
    setsid nohup "${cmd[@]}" >>"$LOG_FILE" 2>&1 &
    echo $! >"$PID_FILE"
  )
  sleep 1

  if is_running; then
    echo "启动成功，PID=$(<"$PID_FILE")，日志: $LOG_FILE"
    if [[ "$MODE" == "web" ]]; then
      start_worker
      if [[ "$HOST" == "0.0.0.0" ]]; then
        echo "Web 地址: http://$(hostname -I 2>/dev/null | awk '{print $1}' || echo '<局域网IP>'):$PORT"
        echo "本机访问: http://127.0.0.1:$PORT"
      else
        echo "Web 地址: http://$HOST:$PORT"
      fi
    fi
  else
    echo "启动失败，请查看日志: $LOG_FILE" >&2
    rm -f "$PID_FILE"
    exit 1
  fi
}

stop() {
  stop_worker
  if ! is_running; then
    if [[ "$MODE" == "web" ]]; then
      local port_pid
      port_pid="$(web_port_pid || true)"
      if is_kenradar_pid "$port_pid"; then
        echo "停止 KenRadar，PID=$port_pid"
        kill "$port_pid" 2>/dev/null || true
        rm -f "$PID_FILE"
        echo "已停止"
        return 0
      fi
    fi
    echo "KenRadar 未运行"
    rm -f "$PID_FILE"
    return 0
  fi

  local pid
  pid="$(<"$PID_FILE")"
  echo "停止 KenRadar，PID=$pid"
  kill "$pid" 2>/dev/null || true

  for _ in {1..20}; do
    if ! kill -0 "$pid" 2>/dev/null; then
      rm -f "$PID_FILE"
      echo "已停止"
      return 0
    fi
    sleep 0.5
  done

  echo "进程未正常退出，强制停止 PID=$pid"
  kill -9 "$pid" 2>/dev/null || true
  rm -f "$PID_FILE"
  echo "已停止"
}

status() {
  if is_running; then
    echo "KenRadar 运行中，PID=$(<"$PID_FILE")，MODE=$MODE，日志: $LOG_FILE"
  elif [[ "$MODE" == "web" ]]; then
    local port_pid
    port_pid="$(web_port_pid || true)"
    if is_kenradar_pid "$port_pid"; then
      echo "KenRadar 运行中，PID=$port_pid，MODE=$MODE，日志: $LOG_FILE（已补写 PID 文件）"
      echo "$port_pid" >"$PID_FILE"
      return 0
    fi
    echo "KenRadar 未运行"
  else
    echo "KenRadar 未运行"
  fi
  status_worker
}

logs() {
  touch "$LOG_FILE"
  tail -f "$LOG_FILE"
}

case "${1:-}" in
  start) start ;;
  stop) stop ;;
  restart) stop; start ;;
  status) status ;;
  logs) logs ;;
  start-worker) start_worker ;;
  stop-worker) stop_worker ;;
  status-worker) status_worker ;;
  start-funasr) start_funasr ;;
  stop-funasr) stop_funasr ;;
  restart-funasr) stop_funasr; start_funasr ;;
  status-funasr) status_funasr ;;
  logs-funasr) logs_funasr ;;
  -h|--help|help) usage ;;
  *) usage; exit 2 ;;
esac
