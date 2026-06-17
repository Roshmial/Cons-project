#!/usr/bin/env bash
set -euo pipefail
RUNTIME_ROOT="${HERMES_WEB_BROWSER_RUNTIME_ROOT:-$HOME/.local/browser-runtime/root}"
LIB_ROOT="${HERMES_WEB_BROWSER_LIB_ROOT:-$HOME/.hermes/browser-libs/root}"
export FONTCONFIG_PATH="${FONTCONFIG_PATH:-$RUNTIME_ROOT/etc/fonts}"
export FONTCONFIG_FILE="${FONTCONFIG_FILE:-$RUNTIME_ROOT/etc/fonts/fonts.conf}"
export XDG_DATA_DIRS="${XDG_DATA_DIRS:-$RUNTIME_ROOT/usr/share}"
export LD_LIBRARY_PATH="${LIB_ROOT}/usr/lib/x86_64-linux-gnu:${LD_LIBRARY_PATH:-}"
exec "$@"
