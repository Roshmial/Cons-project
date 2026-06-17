#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 /absolute/path/to/project-root" >&2
  exit 1
fi

PROJECT_ROOT="$1"
if [[ ! -d "$PROJECT_ROOT" ]]; then
  echo "Project root not found: $PROJECT_ROOT" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UNIT_SRC_DIR="$SCRIPT_DIR/systemd"
UNIT_DST_DIR="$HOME/.config/systemd/user"
mkdir -p "$UNIT_DST_DIR"

for unit in hermes-web-backend-8791.service hermes-web-frontend-8793.service hermes-web-copilotkit-8794.service; do
  sed "s|__PROJECT_ROOT__|$PROJECT_ROOT|g" "$UNIT_SRC_DIR/$unit" > "$UNIT_DST_DIR/$unit"
  echo "Installed $UNIT_DST_DIR/$unit"
done

systemctl --user daemon-reload
systemctl --user enable hermes-web-backend-8791.service hermes-web-copilotkit-8794.service hermes-web-frontend-8793.service

echo "Units installed. Start with:"
echo "  systemctl --user restart hermes-web-backend-8791.service hermes-web-copilotkit-8794.service hermes-web-frontend-8793.service"
