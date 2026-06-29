#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_DIR="$SCRIPT_DIR/services/backend"
VENV_DIR="$SERVICE_DIR/.venv"
REQ_FILE="$SERVICE_DIR/requirements.txt"
REQ_STAMP="$VENV_DIR/.requirements.sha256"
source "$SCRIPT_DIR/scripts/runtime_env.sh"
cd "$SERVICE_DIR"
if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  python3 -m venv "$VENV_DIR"
fi
source "$VENV_DIR/bin/activate"
CURRENT_REQ_HASH="$(sha256sum "$REQ_FILE" | awk '{print $1}')"
INSTALLED_REQ_HASH="$(cat "$REQ_STAMP" 2>/dev/null || true)"
if [[ "$CURRENT_REQ_HASH" != "$INSTALLED_REQ_HASH" ]]; then
  python -m pip install --quiet -r "$REQ_FILE"
  printf '%s' "$CURRENT_REQ_HASH" > "$REQ_STAMP"
fi
BACKEND_THREADS="${HERMES_WEB_BACKEND_THREADS:-8}"
BACKEND_HOST="${HERMES_WEB_BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${HERMES_WEB_BACKEND_PORT:-8791}"
cleanup_stale_backend_listener() {
  if ! command -v fuser >/dev/null 2>&1; then
    return 0
  fi
  local existing_pids pid cmdline wait_left
  existing_pids="$(fuser -n tcp "$BACKEND_PORT" 2>/dev/null || true)"
  [[ -z "${existing_pids// }" ]] && return 0
  for pid in $existing_pids; do
    [[ -r "/proc/$pid/cmdline" ]] || continue
    cmdline="$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)"
    if [[ "$cmdline" == *"$SERVICE_DIR/.venv/bin/waitress-serve"* || "$cmdline" == *"$SERVICE_DIR/.venv/bin/python"*"app:app"* || "$cmdline" == *"$SCRIPT_DIR/run_backend_service.sh"* ]]; then
      kill -TERM "$pid" 2>/dev/null || true
    fi
  done
  wait_left=20
  while fuser -n tcp "$BACKEND_PORT" >/dev/null 2>&1; do
    ((wait_left--)) || break
    sleep 1
  done
}
cleanup_stale_backend_listener
exec waitress-serve --threads="$BACKEND_THREADS" --listen="${BACKEND_HOST}:${BACKEND_PORT}" app:app
