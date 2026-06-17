# Руководство по развёртыванию Hermes Web MVP на новом сервере

## 1. Цель

Этот документ описывает, как развернуть Hermes Web MVP на другом Linux-сервере так, чтобы получить тот же канонический контур:
- frontend на `8793`;
- backend на `8791`;
- CopilotKit runtime на `8794`;
- backend, подключённый к Hermes API Server.

## 2. Что должно быть на сервере заранее

Нужно подготовить:
- Linux-хост;
- пользователя, под которым будет работать Hermes и web-контур;
- установленный Hermes Agent;
- рабочий Hermes gateway без подключённого Telegram: gateway нужен только как runtime-обвязка для API Server, а не как Telegram-шлюз;
- включённый Hermes API Server;
- Python 3.12 или совместимый Python 3;
- Node.js и npm;
- доступ на запись в домашний каталог пользователя и в директорию проекта.

## 3. Базовая структура

Ожидаемая структура:
- проект: например `/home/hermes/workspace/hermes-web-mvp-react-8793`
- Hermes env: `~/.hermes/.env`
- user systemd units: `~/.config/systemd/user/`

## 4. Обязательные переменные Hermes

В `~/.hermes/.env` должны быть доступны как минимум:
- `API_SERVER_ENABLED=true`
- `API_SERVER_HOST=127.0.0.1`
- `API_SERVER_PORT=8642`
- `API_SERVER_KEY=[REDACTED]`

Желательно также явно указать CORS для frontend, например:
- `API_SERVER_CORS_ORIGINS=http://127.0.0.1:8793`

После изменения `.env` нужно перезапустить Hermes gateway.

## 5. Что делает каждый runtime-скрипт

### 5.1 `run_backend_service.sh`

Скрипт:
- подхватывает `~/.hermes/.env`;
- выставляет backend host/port;
- прокидывает адрес и ключ Hermes API Server;
- поднимает backend на `127.0.0.1:8791` через `waitress-serve`.

### 5.2 `run_frontend_react_service.sh`

Скрипт:
- подхватывает Node runtime;
- выставляет URL backend для frontend;
- поднимает Vite dev server на `127.0.0.1:8793`.

### 5.3 `run_copilotkit_runtime_service.sh`

Скрипт:
- подхватывает `~/.hermes/.env`;
- выставляет порт `8794`;
- подключает runtime к Hermes API Server;
- поднимает CopilotKit runtime на `127.0.0.1:8794`.

## 6. Порядок развёртывания вручную

### Шаг 1. Скопировать проект

Пример:
`cp -R hermes-web-mvp-react-8793 /home/hermes/workspace/hermes-web-mvp-react-8793`

### Шаг 2. Проверить зависимости backend

Из корня проекта:
- `./run_backend_service.sh`

Скрипт сам создаст virtualenv в `services/backend/.venv`, если его нет.

### Шаг 3. Проверить зависимости frontend

Из корня проекта:
- `npm install`
- `npm run react:build`

### Шаг 4. Проверить CopilotKit runtime

Из корня проекта:
- `./run_copilotkit_runtime_service.sh`

### Шаг 5. Проверить frontend

Из корня проекта:
- `./run_frontend_react_service.sh`

## 7. Переход на systemd user services

Для постоянного запуска рекомендуемый вариант — user services.

Нужны три unit-файла:
- `hermes-web-backend-8791.service`
- `hermes-web-frontend-8793.service`
- `hermes-web-copilotkit-8794.service`

Шаблоны и install-скрипт лежат в:
- `deploy/package/systemd/`
- `deploy/package/install-systemd-user.sh`

## 8. Активация systemd units

После копирования unit-файлов:
1. `systemctl --user daemon-reload`
2. `systemctl --user enable hermes-web-backend-8791.service`
3. `systemctl --user enable hermes-web-copilotkit-8794.service`
4. `systemctl --user enable hermes-web-frontend-8793.service`
5. `systemctl --user restart hermes-web-backend-8791.service hermes-web-copilotkit-8794.service hermes-web-frontend-8793.service`

## 9. Что проверить после развёртывания

### 9.1 Сервисы
- `systemctl --user status hermes-web-backend-8791.service`
- `systemctl --user status hermes-web-copilotkit-8794.service`
- `systemctl --user status hermes-web-frontend-8793.service`

### 9.2 Порты
- `ss -ltnp | egrep ':(8791|8793|8794)\b'`

### 9.3 HTTP-ответы
- `GET http://127.0.0.1:8791/api/service-info`
- `GET http://127.0.0.1:8793`
- `GET http://127.0.0.1:8794/copilotkit`

Нормально, если `GET /copilotkit` не даёт красивую страницу. Главное — runtime должен быть запущен и слушать порт.

## 10. Финальные технические проверки

Обязательно выполнить:
- `python3 -m py_compile services/backend/app.py`
- `npm run react:build`
- `python3 -m unittest services/backend/test_smoke.py`
- `./deploy/package/verify-deployment.sh`

Если на сервере уже есть тестовая acceptance-учётка и browser runtime, дополнительно стоит прогнать:
- `bash -lc 'source scripts/runtime_env.sh && ./scripts/browser_runtime_env.sh node scripts/ui_acceptance_smoke_react.mjs'`
- `bash -lc 'source scripts/runtime_env.sh && ./scripts/browser_runtime_env.sh node scripts/policy_admin_acceptance.mjs'`

## 11. Типовые проблемы

### Проблема: порт уже занят

Симптом:
- сервис уходит в restart-loop;
- в журнале есть `Address already in use` или `Port 8793 is already in use`.

Что делать:
- проверить `ss -ltnp`;
- найти ручной процесс или старый сервис;
- остановить конфликтующий runtime;
- перезапустить нужный unit.

### Проблема: backend может конфликтовать на открытии DuckDB под параллельной нагрузкой

Симптом:
- ошибки вокруг `/api/admin/chat-notice` или других admin-read path при очереди параллельных запросов;
- в логах могут встречаться `Binder Error`, `Unique file handle conflict` или `TransactionContext Error` на этапе открытия/инициализации соединения.

Что делать:
- убедиться, что backend запущен из актуального дерева и использует текущий `services/backend/app.py`;
- не держать параллельно второй ручной backend на ту же базу;
- если код старый, подтянуть версию с retry-логикой в `DBConnection` и конкурентным regression-тестом в `services/backend/test_smoke.py`;
- после обновления прогнать `python3 -m unittest services/backend/test_smoke.py` и отдельно живую проверку acceptance-path.

### Проблема: frontend жив, но backend не тот

Симптом:
- frontend берётся из одного проекта, backend — из другого каталога.

Что делать:
- проверить `systemctl --user status` и `ExecStart`;
- проверить `WorkingDirectory`;
- выполнить `systemctl --user daemon-reload` и `restart`.

### Проблема: headless acceptance нестабилен на переключении admin tabs

Симптом:
- исторически это проявлялось как нестабильный переход между `Обзор / Пользователи / Операции / Справочники` в Playwright при искусственном restore-path через `localStorage`.

Что делать:
- использовать актуальный `scripts/ui_acceptance_smoke_react.mjs`, где admin-секции открываются через реальные tab-кнопки `data-admin-section`, а не через `reload`-сценарий;
- если acceptance снова падает, сначала считать это проблемой smoke/testability и только потом искать product-баг;
- смотреть актуальный статус хвостов в `docs/BACKLOG.md`.

## 12. Что входит в deploy-пакет

Смотри каталог:
- `deploy/package/README.md`
- `deploy/package/env/hermes-web.env.example`
- `deploy/package/systemd/*.service`
- `deploy/package/install-systemd-user.sh`
- `deploy/package/verify-deployment.sh`

## 13. Рекомендация по первому запуску на новом сервере

Сначала делай ручной прогон:
- backend;
- CopilotKit runtime;
- frontend;
- smoke-проверки.

Только после этого включай systemd units. Это снижает цену ошибки и упрощает диагностику. 
