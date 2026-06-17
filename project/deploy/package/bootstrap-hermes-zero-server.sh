#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

if ! command -v hermes >/dev/null 2>&1; then
  echo 'Hermes CLI not found. Install Hermes first:' >&2
  echo '  curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash' >&2
  exit 1
fi

echo '== Hermes basic health =='
hermes doctor || true

echo
echo '== Hermes config hints =='
echo 'Run these if the server is truly new:'
echo '  hermes setup'
echo '  hermes gateway install'
echo '  hermes config set api_server.enabled true'
echo '  hermes config set api_server.host 127.0.0.1'
echo '  hermes config set api_server.port 8642'
echo '  hermes config set api_server.cors_origins http://127.0.0.1:8793'
echo
echo 'Then ensure ~/.hermes/.env contains API_SERVER_KEY and a working model/provider config.'

echo
echo '== Install project Node dependencies =='
cd "$PROJECT_ROOT"
npm install

echo
echo '== Prepare backend venv =='
./run_backend_service.sh >/tmp/hermes_web_backend_bootstrap.log 2>&1 &
BOOT_PID=$!
sleep 10 || true
kill "$BOOT_PID" >/dev/null 2>&1 || true
wait "$BOOT_PID" >/dev/null 2>&1 || true

echo
echo '== Bootstrap finished =='
echo 'Next steps:'
echo '  1. ./deploy/package/install-systemd-user.sh '$PROJECT_ROOT
echo '  2. systemctl --user restart hermes-web-backend-8791.service hermes-web-copilotkit-8794.service hermes-web-frontend-8793.service'
echo '  3. ./deploy/package/verify-deployment.sh'
