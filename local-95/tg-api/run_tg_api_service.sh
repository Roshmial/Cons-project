#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"
REQ_FILE="$SCRIPT_DIR/requirements.txt"
REQ_STAMP="$VENV_DIR/.requirements.sha256"
cd "$SCRIPT_DIR"
if [[ -f "$HOME/.hermes/.env" ]]; then
  set -a
  source "$HOME/.hermes/.env"
  set +a
fi
if [[ -f "$HOME/.hermes/tg-api.env" ]]; then
  set -a
  source "$HOME/.hermes/tg-api.env"
  set +a
fi
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
export TG_API_PROJECT_DIR="${TG_API_PROJECT_DIR:-$SCRIPT_DIR}"
export TG_API_HOST="${TG_API_HOST:-127.0.0.1}"
export TG_API_PORT="${TG_API_PORT:-8001}"
exec waitress-serve --listen="${TG_API_HOST}:${TG_API_PORT}" app:app
