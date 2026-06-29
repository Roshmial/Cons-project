#!/usr/bin/env bash
set -euo pipefail
ROOT="/home/hermes/workspace/hermes-web-mvp-react-8793/.local-browser-libs/extracted"
LIB_PATH=$(find "$ROOT" -type d \( -path '*/usr/lib/x86_64-linux-gnu' -o -path '*/lib/x86_64-linux-gnu' -o -path '*/usr/lib' -o -path '*/lib' \) | paste -sd: -)
export LD_LIBRARY_PATH="$LIB_PATH${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export GTK_PATH=$(find "$ROOT" -type d -path '*/usr/lib/x86_64-linux-gnu/gtk-3.0' | head -n1)
export GIO_MODULE_DIR=$(find "$ROOT" -type d -path '*/usr/lib/x86_64-linux-gnu/gio/modules' | head -n1)
exec "$@"
