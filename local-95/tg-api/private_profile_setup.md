Ниже — безопасный локальный порядок запуска нового Telegram-профиля без отправки секретов в чат.

Файлы:
- `private-profile.env.example` — шаблон локального env-файла.
- `setup_private_profile.sh` — интерактивный запуск логина и создание новой `.session`.
- `check_chat_access.py` — проверка, видит ли новый профиль нужный закрытый чат.

Шаги:
1. Скопировать шаблон:
   `cp /home/hermes/workspace/TG-API/private-profile.env.example /home/hermes/workspace/TG-API/private-profile.env`
2. Заполнить в `private-profile.env` локально:
   - `TG_API_ID`
   - `TG_API_HASH`
   - `PROFILE` (например `profile_private`)
   - при необходимости оставить `TG_API_PROJECT_DIR=/home/hermes/workspace/TG-API`
3. Ограничить доступ к env-файлу:
   `chmod 600 /home/hermes/workspace/TG-API/private-profile.env`
4. Запустить логин:
   `/home/hermes/workspace/TG-API/setup_private_profile.sh`
5. Ввести номер телефона, код из Telegram и при необходимости 2FA-пароль только в локальном терминале.
6. Проверить, что создалась сессия:
   `ls -l /home/hermes/workspace/TG-API/session/<profile>.session`
7. Проверить доступ к закрытому чату:
   `set -a && source /home/hermes/workspace/TG-API/private-profile.env && set +a && python3 /home/hermes/workspace/TG-API/check_chat_access.py <profile> <chat_id> [message_id] [limit]`

Пример проверки:
`set -a && source /home/hermes/workspace/TG-API/private-profile.env && set +a && python3 /home/hermes/workspace/TG-API/check_chat_access.py profile_private -1003758328239 1 10`

Интерпретация:
- `authorized=True` и `entity_ok=True` — профиль видит чат.
- `message_found=True` — конкретное сообщение доступно.
- `last_count=...` — удалось прочитать последние сообщения.
