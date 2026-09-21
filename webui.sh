#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_DIR="$ROOT/.webui-run"
BACKEND_PID="$RUN_DIR/backend.pid"
FRONTEND_PID="$RUN_DIR/frontend.pid"
BACKEND_LOG="$RUN_DIR/backend.log"
FRONTEND_LOG="$RUN_DIR/frontend.log"

usage() {
  cat <<'USAGE'
Usage: bash webui.sh {start|stop|restart|status|logs}

Commands:
  start    Start backend on :8000 and frontend on :5173
  stop     Stop both services
  restart  Stop, then start both services
  status   Show service PIDs and URLs
  logs     Follow backend and frontend logs
USAGE
}

pid_from_file() {
  local pidfile="$1"
  if [[ -f "$pidfile" ]]; then
    tr -dc '0-9' < "$pidfile"
  fi
}

is_running() {
  local pidfile="$1"
  local pid
  pid="$(pid_from_file "$pidfile")"
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

start_service() {
  local name="$1"
  local pidfile="$2"
  local logfile="$3"
  shift 3

  mkdir -p "$RUN_DIR"

  if is_running "$pidfile"; then
    echo "$name already running (PID $(pid_from_file "$pidfile"))"
    return
  fi

  rm -f "$pidfile"
  echo "Starting $name..."
  (
    cd "$ROOT"
    exec setsid "$@"
  ) > "$logfile" 2>&1 < /dev/null &
  echo "$!" > "$pidfile"
  echo "$name PID: $(cat "$pidfile")"
  echo "$name log: $logfile"
}

stop_service() {
  local name="$1"
  local pidfile="$2"
  local pid
  pid="$(pid_from_file "$pidfile")"

  if [[ -z "$pid" ]] || ! kill -0 "$pid" 2>/dev/null; then
    echo "$name not running"
    rm -f "$pidfile"
    return
  fi

  echo "Stopping $name (PID $pid)..."
  kill -TERM "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true

  for _ in {1..20}; do
    if ! kill -0 "$pid" 2>/dev/null; then
      rm -f "$pidfile"
      echo "$name stopped"
      return
    fi
    sleep 0.5
  done

  echo "$name did not stop cleanly; killing it."
  kill -KILL "-$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null || true
  rm -f "$pidfile"
}

status_service() {
  local name="$1"
  local pidfile="$2"
  local url="$3"

  if is_running "$pidfile"; then
    echo "$name: running (PID $(pid_from_file "$pidfile")) - $url"
  else
    echo "$name: stopped"
  fi
}

start_all() {
  start_service "backend" "$BACKEND_PID" "$BACKEND_LOG" make dev-backend
  start_service "frontend" "$FRONTEND_PID" "$FRONTEND_LOG" make dev-frontend
  echo
  echo "Backend:  http://localhost:8000/api/health"
  echo "Frontend: http://localhost:5173"
}

stop_all() {
  stop_service "frontend" "$FRONTEND_PID"
  stop_service "backend" "$BACKEND_PID"
}

case "${1:-start}" in
  start)
    start_all
    ;;
  stop)
    stop_all
    ;;
  restart)
    stop_all
    start_all
    ;;
  status)
    status_service "backend" "$BACKEND_PID" "http://localhost:8000"
    status_service "frontend" "$FRONTEND_PID" "http://localhost:5173"
    ;;
  logs)
    mkdir -p "$RUN_DIR"
    touch "$BACKEND_LOG" "$FRONTEND_LOG"
    tail -f "$BACKEND_LOG" "$FRONTEND_LOG"
    ;;
  -h|--help|help)
    usage
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
