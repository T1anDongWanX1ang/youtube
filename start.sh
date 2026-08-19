#!/usr/bin/env bash
# Start both long-running components in the background.
# Usage: ./start.sh {start|stop|restart|status}

set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv not found; installing it for the current user..."
  if ! command -v curl >/dev/null 2>&1; then
    echo "curl is required to install uv automatically. Install curl, then retry." >&2
    exit 1
  fi
  curl --proto '=https' --tlsv1.2 -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "uv installation completed but uv is not on PATH; open a new shell and retry." >&2
  exit 1
fi

if [[ ! -f .env ]]; then
  echo "Missing $PROJECT_DIR/.env; copy .env.example and configure it before starting." >&2
  exit 1
fi

# Dependencies belong in the project virtual environment, not in .env.  Keeping
# the location explicit makes the worker and API use exactly the same packages.
export UV_PROJECT_ENVIRONMENT="${UV_PROJECT_ENVIRONMENT:-$PROJECT_DIR/.venv}"
export PYTHONUNBUFFERED=1

mkdir -p logs
WEB_HOST="${YOUTUBE_WEB_HOST:-0.0.0.0}"
WEB_PORT="${YOUTUBE_WEB_PORT:-8000}"
WORKER_PID_FILE="logs/polling.pid"
API_PID_FILE="logs/api.pid"

# Creates .venv when absent and installs the dependency versions pinned in uv.lock.
uv sync --frozen

PYTHON_BIN="$UV_PROJECT_ENVIRONMENT/bin/python"
UVICORN_BIN="$UV_PROJECT_ENVIRONMENT/bin/uvicorn"
WORKER_BIN="$UV_PROJECT_ENVIRONMENT/bin/youtube-crypto"
if [[ ! -x "$PYTHON_BIN" || ! -x "$UVICORN_BIN" || ! -x "$WORKER_BIN" ]]; then
  echo "Virtual environment setup failed: expected executables under $UV_PROJECT_ENVIRONMENT" >&2
  exit 1
fi

# Fail before backgrounding services when the deployment has an incomplete
# database/API/Secret Manager configuration.  The command intentionally never
# prints a key or connection string.
if ! "$PYTHON_BIN" -c '
from youtube_crypto.config.config import YouTubeCryptoSettings
from pathlib import Path
settings = YouTubeCryptoSettings.from_env()
_ = settings.youtube_data_api_keys
_ = settings.resolved_youtube_gemini_api_key
if not Path("point_of_view_llm.txt").is_file():
    raise RuntimeError("point_of_view_llm.txt is missing")
print("Configuration and Gemini Secret Manager access verified.")
'; then
  echo "Startup preflight failed; check .env and Secret Manager credentials." >&2
  exit 1
fi

is_running() {
  local pid_file="$1"
  [[ -f "$pid_file" ]] && kill -0 "$(cat "$pid_file")" 2>/dev/null
}

start_process() {
  local name="$1"
  local pid_file="$2"
  local log_file="$3"
  shift 3

  if is_running "$pid_file"; then
    echo "$name is already running: pid=$(cat "$pid_file")"
    return
  fi
  rm -f "$pid_file"
  nohup "$@" >>"$log_file" 2>&1 </dev/null &
  echo $! >"$pid_file"
  echo "Started $name in background: pid=$(cat "$pid_file") log=$log_file"
}

stop_process() {
  local name="$1"
  local pid_file="$2"
  if is_running "$pid_file"; then
    kill "$(cat "$pid_file")"
    echo "Stopped $name: pid=$(cat "$pid_file")"
  else
    echo "$name is not running"
  fi
  rm -f "$pid_file"
}

start() {
  start_process "polling worker" "$WORKER_PID_FILE" "logs/polling.log" \
    "$WORKER_BIN"
  start_process "API" "$API_PID_FILE" "logs/api.log" \
    "$UVICORN_BIN" youtube_crypto.web.app:app --host "$WEB_HOST" --port "$WEB_PORT"
}

stop() {
  stop_process "polling worker" "$WORKER_PID_FILE"
  stop_process "API" "$API_PID_FILE"
}

status() {
  if is_running "$WORKER_PID_FILE"; then
    echo "polling worker: running pid=$(cat "$WORKER_PID_FILE")"
  else
    echo "polling worker: stopped"
  fi
  if is_running "$API_PID_FILE"; then
    echo "API: running pid=$(cat "$API_PID_FILE")"
  else
    echo "API: stopped"
  fi
}

case "${1:-start}" in
  start) start ;;
  stop) stop ;;
  restart) stop; start ;;
  status) status ;;
  *) echo "usage: $0 {start|stop|restart|status}"; exit 2 ;;
esac
