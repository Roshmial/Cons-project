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
exec waitress-serve --threads="$BACKEND_THREADS" --listen="${HERMES_WEB_BACKEND_HOST}:${HERMES_WEB_BACKEND_PORT}" app:app
