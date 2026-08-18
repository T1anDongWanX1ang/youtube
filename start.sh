#!/usr/bin/env bash
# Start both long-running components: the polling worker and the on-demand API.
# Run from the repository root with: ./start.sh

set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required. Install it first: https://docs.astral.sh/uv/" >&2
  exit 1
fi

if [[ ! -f .env ]]; then
  echo "Missing $PROJECT_DIR/.env; copy .env.example and configure it before starting." >&2
  exit 1
fi

mkdir -p logs
WEB_HOST="${YOUTUBE_WEB_HOST:-0.0.0.0}"
WEB_PORT="${YOUTUBE_WEB_PORT:-8000}"

uv sync --frozen

echo "Starting polling worker..."
uv run python -m youtube_crypto >logs/polling.log 2>&1 &
POLL_PID=$!

echo "Starting API at http://${WEB_HOST}:${WEB_PORT}..."
uv run uvicorn youtube_crypto.web.app:app --host "$WEB_HOST" --port "$WEB_PORT" \
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
