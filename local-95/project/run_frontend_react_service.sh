#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR"
cd "$PROJECT_ROOT"
export PATH="$HOME/.hermes/node/bin:$PATH"
source "$PROJECT_ROOT/scripts/runtime_env.sh"
cd "$PROJECT_ROOT"
FRONTEND_MODE="${HERMES_WEB_FRONTEND_MODE:-dev}"
if [[ "$FRONTEND_MODE" == "prod" ]]; then
  exec node "$PROJECT_ROOT/scripts/serve_frontend_prod.mjs"
fi
exec npm run react:dev -- --host "$HERMES_WEB_FRONTEND_HOST" --port "$HERMES_WEB_FRONTEND_PORT"
