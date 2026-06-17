# Backend service

## Назначение

Backend — это прикладной API Hermes Web MVP. Он владеет operational-состоянием web-приложения и интегрирует frontend с Hermes runtime.

Backend отвечает за:
- аутентификацию и сессии;
- пользователей и их профиль;
- чаты и сообщения;
- feedback;
- backend-справочники;
- admin CRUD по пользователям;
- audit trail и versioning для admin-сущностей;
- bridge к Hermes cron;
- вызовы Hermes API Server.

## Основная БД

Текущая рабочая БД backend:
- `data/hermes_web_app.duckdb`

Legacy SQLite допускается только как источник миграции старых данных. Рабочий operational store — DuckDB.

## Что уже есть

Пользовательские endpoint-ы:
- login/logout
- восстановление сессии по token
- profile read/update
- thread list/create/update/detail
- archive/unarchive thread
- messages + Hermes reply
- feedback reasons + feedback save

Admin endpoint-ы:
- admin health
- admin users list/detail/create/update/history
- admin user import
- admin reference data list
- admin reference item create/update/history
- admin user sources

## Ключевые data-сущности

- `users`
- `sessions`
- `threads`
- `messages`
- `feedback`
- `reference_catalogs`
- `reference_items`
- `user_change_log`
- `reference_item_change_log`

## Версионность и аудит

Для admin-сущностей используется простой production-like минимум:
- `users.version`
- `reference_items.version`
- `user_change_log`
- `reference_item_change_log`

В change log пишется snapshot состояния после изменения, актор, тип изменения и время.

## Важные env-переменные

- `HERMES_WEB_BACKEND_HOST`
- `HERMES_WEB_BACKEND_PORT`
- `HERMES_WEB_CORS_ALLOW_ORIGIN`
- `HERMES_WEB_MODE`
- `HERMES_WEB_BACKEND_DATA_DIR`
- `HERMES_WEB_BACKEND_DB_PATH`
- `HERMES_WEB_BACKEND_SCHEMA`
- `HERMES_WEB_API_PREFIX`
- `HERMES_WEB_HERMES_API_BASE_URL`
- `HERMES_WEB_HERMES_API_KEY`
- `HERMES_WEB_HERMES_API_MODEL`

## Ключевые принципы

- backend ничего не знает о frontend-статике;
- frontend можно перенести отдельно и перепривязать через `config.js`;
- backend остаётся отдельным app-слоем со своим storage;
- справочники и пользователи управляются через backend, а не через frontend hardcode;
- jobs не должны дублироваться в app DB, если их operational truth уже живёт в Hermes cron.

## Проверка после изменений

Минимальный набор:
- `python3 -m py_compile app.py`
- `python3 test_smoke.py`

Если менялись admin-сущности, дополнительно обязательно проверять:
- create/update user;
- user history;
- create/update reference item;
- reference history;
- рост `version` после update.
