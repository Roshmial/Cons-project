Временная web-авторизация Telegram

Что это делает
- создаёт одноразовую или временную ссылку для авторизации Telegram-аккаунта;
- пользователь открывает страницу с телефона или компьютера;
- вводит номер телефона, затем код из Telegram;
- если включена двухфакторная защита, вводит пароль 2FA;
- после успеха на сервере появляется session-файл `session/<profile>.session`.

Что уже есть
- endpoint создания ссылки: `POST /auth/telegram/admin/create_link`
- страница входа: `GET /auth/telegram/<token>`
- проверка статуса: `GET /auth/telegram/<token>/status`
- шаги входа:
  - `POST /auth/telegram/<token>/send_phone`
  - `POST /auth/telegram/<token>/verify_code`
  - `POST /auth/telegram/<token>/verify_password`
  - `POST /auth/telegram/<token>/cancel`
- вспомогательный CLI: `python3 create_auth_link.py profile_private 20`

Как поднять локально
1. Запустить TG-API как раньше.
2. Убедиться, что в env заданы `TG_API_ID` и `TG_API_HASH`.
3. Создать ссылку:
   - через API: `curl -X POST http://127.0.0.1:8001/auth/telegram/admin/create_link -H 'Content-Type: application/json' -d '{"profile":"profile_private","ttl_minutes":20}'`
   - или через CLI: `python3 create_auth_link.py profile_private 20`
4. Отдать пользователю `auth_url`.
5. После авторизации проверить session и доступ к чату через `check_chat_access.py`.

Ограничения текущего MVP
- если `TG_AUTH_ADMIN_TOKEN` не задан, endpoint создания ссылки разрешён только с loopback (`127.0.0.1` / `::1`);
- если `TG_AUTH_ADMIN_TOKEN` задан, его нужно передавать в `X-Auth-Token` или `Authorization: Bearer ...`;
- state хранится локально в `auth_link_state.json`;
- это одношаговый локальный MVP, а не полноценный кабинет;
- секреты не возвращаются в UI, но сама страница должна открываться только по HTTPS, если доступ идёт через интернет.

Что я бы добавляла следующим слоем
- Basic Auth или nginx-ограничение на admin endpoint создания ссылок;
- отдельный внешний base URL через `TG_AUTH_PUBLIC_BASE_URL`;
- автоочистку использованных ссылок раньше 24 часов;
- rate limiting на попытки по коду и паролю.
