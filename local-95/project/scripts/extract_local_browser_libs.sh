#!/usr/bin/env bash
set -euo pipefail
ROOT="${1:-/home/hermes/workspace/hermes-web-mvp-react-8793/.local-browser-libs}"
DEB_DIR="$ROOT/debs"
EXTRACT_DIR="$ROOT/extracted"
mkdir -p "$DEB_DIR" "$EXTRACT_DIR"
cd "$DEB_DIR"
packages=(
  libnspr4 libnss3 libatk1.0-0t64 libatk-bridge2.0-0t64 libx11-6 libxcomposite1 libxdamage1 libxext6 libxfixes3 libxrandr2 libxrender1 libgbm1 libxcb1 libxkbcommon0 libasound2t64 libatspi2.0-0t64 libglib2.0-0t64 libgtk-3-0t64 libcairo2 libpango-1.0-0 libpangocairo-1.0-0 libpangoft2-1.0-0 libxshmfence1 libdrm2 libwayland-client0 libwayland-server0 libwayland-egl1 libwayland-cursor0 libharfbuzz0b libfontconfig1 libfribidi0 libthai0 libcairo-gobject2 libgdk-pixbuf-2.0-0 libepoxy0 libxi6 libxcursor1 libxinerama1 libxcb-render0 libxcb-shm0 libpixman-1-0 libxau6 libxdmcp6
)
for pkg in "${packages[@]}"; do
  apt download "$pkg"
done
for deb in ./*.deb; do
  dir="$EXTRACT_DIR/$(basename "$deb" .deb)"
  mkdir -p "$dir"
  dpkg-deb -x "$deb" "$dir"
done
find "$EXTRACT_DIR" -type f \( -name '*.so' -o -name '*.so.*' \) | sed 's#^#LIB #'
