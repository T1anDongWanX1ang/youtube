#!/usr/bin/env bash
# Start both long-running components: the polling worker and the on-demand API.
# Run from the repository root with: ./start.sh

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

# Creates .venv when absent and installs the dependency versions pinned in uv.lock.
uv sync --frozen

PYTHON_BIN="$UV_PROJECT_ENVIRONMENT/bin/python"
UVICORN_BIN="$UV_PROJECT_ENVIRONMENT/bin/uvicorn"
if [[ ! -x "$PYTHON_BIN" || ! -x "$UVICORN_BIN" ]]; then
  echo "Virtual environment setup failed: expected executables under $UV_PROJECT_ENVIRONMENT" >&2
  exit 1
fi

echo "Starting polling worker..."
"$PYTHON_BIN" -m youtube_crypto >logs/polling.log 2>&1 &
POLL_PID=$!

echo "Starting API at http://${WEB_HOST}:${WEB_PORT}..."
"$UVICORN_BIN" youtube_crypto.web.app:app --host "$WEB_HOST" --port "$WEB_PORT" \
  >logs/api.log 2>&1 &
API_PID=$!

shutdown() {
  trap - INT TERM EXIT
  echo "Stopping polling worker and API..."
  kill "$POLL_PID" "$API_PID" 2>/dev/null || true
  wait "$POLL_PID" "$API_PID" 2>/dev/null || true
}

trap shutdown INT TERM EXIT

# If either service exits, stop the other one and return the failing status.
wait -n "$POLL_PID" "$API_PID"
exit $?
