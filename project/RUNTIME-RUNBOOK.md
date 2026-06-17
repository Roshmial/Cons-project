# Hermes Web MVP React 8793 — runbook запуска и перезапуска

## Канонический контур

Этот контур считается основным для CopilotKit-интеграции и live-приёмки:

- frontend React/Vite: `127.0.0.1:8793`
- backend Flask: `127.0.0.1:8791`
- CopilotKit runtime sidecar: `127.0.0.1:8794`
- legacy backend из соседнего дерева: `127.0.0.1:8788` — не использовать для этого контура

## Быстрый принцип

Всегда проверять не только порт, но и `cwd` процесса.
Для корректного контура процессы должны идти из дерева:
`/home/hermes/workspace/hermes-web-mvp-react-8793`

## Запуск компонентов

### 1. Backend

Из корня проекта:

`./run_backend_service.sh`

Что делает скрипт:
- активирует `services/backend/.venv`
- при необходимости доставляет `requirements.txt`
- выставляет:
  - `HERMES_WEB_BACKEND_PORT=8791`
  - `HERMES_WEB_CORS_ALLOW_ORIGIN=http://127.0.0.1:8793,http://localhost:8793`
  - `HERMES_WEB_COPILOTKIT_RUNTIME_BASE_URL=http://127.0.0.1:8794`
- запускает `python app.py`

Проверки после старта:
- `GET http://127.0.0.1:8791/api/health`
- `GET http://127.0.0.1:8791/api/service-info`
- `GET http://127.0.0.1:8791/api/copilotkit/info`

Ожидаемо:
- health = `200`
- service-info = `mode: hermes-api`
- copilotkit/info = `200`

### 2. Frontend

Из корня проекта:

`./run_frontend_react_service.sh`

Что делает скрипт:
- выставляет `HERMES_WEB_FRONTEND_BACKEND_BASE=http://127.0.0.1:8791`
- выставляет `HERMES_WEB_FRONTEND_PORT=8793`
- выставляет `VITE_COPILOTKIT_RUNTIME_URL=/api/copilotkit`
- запускает `npm run react:dev`

Проверки после старта:
- открыть `http://127.0.0.1:8793/`
- убедиться, что это Vite/React UI
- убедиться, что frontend ходит в `/api` текущего backend-контура

### 3. CopilotKit runtime sidecar

Запускать из корня проекта:

`node scripts/copilotkit_runtime_8794.cjs`

Проверки:
- `GET http://127.0.0.1:8794/copilotkit/info`
- `GET http://127.0.0.1:8791/api/copilotkit/info`

Оба должны отвечать `200`.

## Корректный порядок полного старта

1. Поднять sidecar `8794`
2. Поднять backend `8791`
3. Поднять frontend `8793`
4. Проверить `health`, `service-info`, `copilotkit/info`
5. Только после этого идти в browser acceptance

## Корректный порядок перезапуска

### Если менялся только frontend

1. Перезапустить только `run_frontend_react_service.sh`
2. Проверить `8793`
3. Прогнать targeted UI acceptance

### Если менялся backend

1. Остановить процесс на `8791`
2. Снова запустить `./run_backend_service.sh`
3. Проверить `health`, `service-info`, `copilotkit/info`
4. Если frontend уже жив, обновить страницу и проверить flow

### Если менялся sidecar/runtime

1. Остановить `scripts/copilotkit_runtime_8794.cjs`
2. Поднять заново
3. Проверить прямой `8794/copilotkit/info`
4. Проверить backend proxy `8791/api/copilotkit/info`

### Если менялось всё

1. Остановить frontend `8793`
2. Остановить backend `8791`
3. Остановить sidecar `8794`
4. Поднять `8794`
5. Поднять `8791`
6. Поднять `8793`
7. Пройти health-check и acceptance

## Обязательные live-проверки перед приёмкой

### Backend
- `/api/health` — быстрый liveness/readiness-check без вызова Hermes cron subprocess; использует локальные счётчики из app DB
- `/api/service-info`
- `/api/copilotkit/info`
- `/api/files?limit=1` с авторизацией
- `/api/bootstrap` не должен повторно собирать весь runtime reference payload по два раза; допускается revision-aware cache для reference views
- `/api/admin/user-sources` и `/api/admin/dashboard-policy` не должны делать write-on-GET и не должны тянуть Hermes cron bridge на каждый запрос
- `/api/admin/jobs` допускает Hermes cron bridge только через короткий TTL-cache, а не прямой subprocess на каждый reload
- при изменениях вокруг admin/runtime-контура отдельно прогонять конкурентную проверку `/api/admin/chat-notice`

### Frontend
- app shell открывается на `8793`
- чат рендерится
- профиль рендерится
- вкладка `Файлы` в профиле показывает загруженные файлы
- jobs/admin открываются
- для полного React smoke использовать:
  - `source scripts/runtime_env.sh && ./scripts/browser_runtime_env.sh node scripts/ui_acceptance_smoke_react.mjs`

### File/open-link flows
- `GET /api/files` возвращает `download_url`
- `GET /api/files/<id>/download` отвечает `200`
- attachment links из сообщений открываются
- `api.openFile()` открывает blob/object URL в новом окне

## Browser runtime

Для browser/playwright acceptance использовать только:

`./scripts/browser_runtime_env.sh <command>`

Скрипт выставляет:
- `FONTCONFIG_PATH=$HOME/.local/browser-runtime/root/etc/fonts`
- `FONTCONFIG_FILE=$HOME/.local/browser-runtime/root/etc/fonts/fonts.conf`
- `XDG_DATA_DIRS=$HOME/.local/browser-runtime/root/usr/share`
- `LD_LIBRARY_PATH=$HOME/.hermes/browser-libs/root/usr/lib/x86_64-linux-gnu`

Это канонический путь. Не использовать временный `workspace/.local-libs` как постоянный источник истины.

## Как понять, что поднят не тот контур

Сигналы ошибки:
- frontend проксирует в `8788`
- backend process слушает нужный порт, но `cwd` у него из другого дерева
- UI будто не видит свежие backend-правки
- `/api/service-info` жив, но реальные payload/роуты не совпадают с текущим кодом

В таком случае обязательно проверить:
- PID на порту
- `cwd` процесса
- `HERMES_WEB_*` env именно у этого PID

## Архитектурные правила

1. Канонический backend для этого контура — `8791`, не `8788`
2. Frontend должен ходить только через backend-owned `/api/copilotkit`
3. Sidecar `8794` — внутренняя деталь реализации, а не пользовательский endpoint
4. Browser acceptance должен идти через стабильный runtime wrapper `browser_runtime_env.sh`
5. Любой новый smoke нужно проверять на актуальных селекторах UI, а не на legacy-лейблах

## Известные хвосты

1. В `services/backend/data` лежат legacy/backup базы:
- `hermes_web_app_8800.duckdb`
- `hermes_web_app.duckdb.bak_before_hard_cleanup_non_admin`
- `hermes_web_app.duckdb.bak_pre_non_admin_cleanup`
- `hermes_web_mvp.sqlite3`

Их нужно либо архивировать отдельно, либо явно пометить как неканонические.

2. В соседнем дереве жив legacy backend на `8788`.
Если он не нужен для других задач, его лучше не держать постоянно поднятым.

3. UI smoke `scripts/ui_acceptance_smoke_react.mjs` нужно поддерживать синхронно с реальными label/placeholder/табами текущего UI.
