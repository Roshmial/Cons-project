#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_DIR="$SCRIPT_DIR/services/frontend"
export HERMES_WEB_FRONTEND_PORT="${HERMES_WEB_FRONTEND_PORT:-8793}"
export HERMES_WEB_FRONTEND_HOST="${HERMES_WEB_FRONTEND_HOST:-127.0.0.1}"
export HERMES_WEB_FRONTEND_BACKEND_BASE="${HERMES_WEB_FRONTEND_BACKEND_BASE:-http://127.0.0.1:8791}"
cd "$SERVICE_DIR"
exec python3 ./serve_frontend.py
