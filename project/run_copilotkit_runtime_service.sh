#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
export PATH="$HOME/.hermes/node/bin:$PATH"
source "$SCRIPT_DIR/scripts/runtime_env.sh"
exec node scripts/copilotkit_runtime_8794.cjs
