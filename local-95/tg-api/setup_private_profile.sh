#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${1:-$PROJECT_DIR/private-profile.env}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Не найден env-файл: $ENV_FILE"
  echo "Скопируй $PROJECT_DIR/private-profile.env.example в private-profile.env, заполни локально и запусти снова."
  exit 1
fi

set -a
source "$ENV_FILE"
set +a

: "${TG_API_ID:?TG_API_ID is required}"
: "${TG_API_HASH:?TG_API_HASH is required}"
: "${PROFILE:?PROFILE is required}"
: "${TG_API_PROJECT_DIR:?TG_API_PROJECT_DIR is required}"

mkdir -p "$TG_API_PROJECT_DIR/session"
chmod 700 "$TG_API_PROJECT_DIR/session" || true

cd "$PROJECT_DIR"

echo "== Логин нового Telegram-профиля =="
echo "PROFILE=$PROFILE"
echo "PROJECT_DIR=$TG_API_PROJECT_DIR"
echo "Session path: $TG_API_PROJECT_DIR/session/${PROFILE}.session"
echo
python3 login.py

echo
echo "Готово. Если логин прошел успешно, проверь наличие файла:"
echo "  $TG_API_PROJECT_DIR/session/${PROFILE}.session"
