#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_ROOT"

FRONTEND_PORT="${HERMES_WEB_FRONTEND_PORT:-8803}"
FRONTEND_URL="${HERMES_WEB_FRONTEND_URL:-http://95.182.85.233:${FRONTEND_PORT}/}"
BACKEND_BASE="${HERMES_WEB_FRONTEND_BACKEND_BASE:-http://178.104.207.89:8791}"
BACKEND_API="${HERMES_WEB_BACKEND_API:-${BACKEND_BASE}/api}"

echo '== systemd status =='
systemctl --user --no-pager --full status hermes-web-backend-8791.service hermes-web-copilotkit-8794.service hermes-web-frontend-8803.service hermes-web-frontend-8793.service || true

echo
echo '== listening ports =='
ss -ltnp | egrep ':(8791|8793|8794|8803)\b' || true

echo
echo '== http checks =='
curl -fsS http://127.0.0.1:8791/api/service-info && echo
curl -I -fsS "$FRONTEND_URL" | head -n 5 || true
curl -I -fsS http://127.0.0.1:8794/copilotkit | head -n 5 || true

echo
echo '== build and smoke =='
python3 -m py_compile services/backend/app.py
npm run react:build
python3 -m unittest services/backend/test_smoke.py

echo
echo '== optional browser acceptance =='
if [[ -n "${HERMES_WEB_SMOKE_EMAIL:-}" && -n "${HERMES_WEB_SMOKE_PASSWORD:-}" && -f scripts/ui_acceptance_smoke_react.mjs ]]; then
  env \
    HERMES_WEB_FRONTEND_URL="$FRONTEND_URL" \
    HERMES_WEB_FRONTEND_PORT="$FRONTEND_PORT" \
    HERMES_WEB_FRONTEND_BACKEND_BASE="$BACKEND_BASE" \
    HERMES_WEB_BACKEND_API="$BACKEND_API" \
    ./scripts/browser_runtime_env.sh node scripts/ui_acceptance_smoke_react.mjs
else
  echo 'Skipping UI smoke: set HERMES_WEB_SMOKE_EMAIL and HERMES_WEB_SMOKE_PASSWORD to enable.'
fi

echo
echo 'Deployment verification completed.'
