#!/usr/bin/env bash
set -euo pipefail

echo '== systemd status =='
systemctl --user --no-pager --full status hermes-web-backend-8791.service hermes-web-copilotkit-8794.service hermes-web-frontend-8793.service || true

echo
echo '== listening ports =='
ss -ltnp | egrep ':(8791|8793|8794)\b' || true

echo
echo '== http checks =='
curl -fsS http://127.0.0.1:8791/api/service-info && echo
curl -I -fsS http://127.0.0.1:8793 | head -n 5 || true
curl -I -fsS http://127.0.0.1:8794/copilotkit | head -n 5 || true

echo
echo '== build and smoke =='
python3 -m py_compile services/backend/app.py
npm run react:build
python3 -m unittest services/backend/test_smoke.py

echo
echo '== optional browser acceptance =='
if [[ -n "${HERMES_WEB_SMOKE_EMAIL:-}" && -n "${HERMES_WEB_SMOKE_PASSWORD:-}" && -f scripts/ui_acceptance_smoke_react.mjs ]]; then
  bash -lc 'source scripts/runtime_env.sh && ./scripts/browser_runtime_env.sh node scripts/ui_acceptance_smoke_react.mjs'
else
  echo 'Skipping UI smoke: set HERMES_WEB_SMOKE_EMAIL and HERMES_WEB_SMOKE_PASSWORD to enable.'
fi

echo
echo 'Deployment verification completed.'
