#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

echo '== Node dependencies =='
npm install

echo
echo '== Backend venv + Python dependencies =='
./run_backend_service.sh >/tmp/hermes_web_backend_dep_install.log 2>&1 &
BOOT_PID=$!
sleep 10 || true
kill "$BOOT_PID" >/dev/null 2>&1 || true
wait "$BOOT_PID" >/dev/null 2>&1 || true

echo
echo '== Done =='
echo 'node_modules installed, backend venv prepared.'
