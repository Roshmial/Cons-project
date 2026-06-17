# Hermes zero-server checklist

Этот чеклист рассчитан на новый сервер, где Hermes только что развёрнут.

## 1. Установить Hermes
- `curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash`
- `hermes doctor`

## 2. Первичная настройка Hermes
- `hermes setup`
- `hermes gateway install`
- убедиться, что есть рабочий model/provider для Hermes API Server

## 3. Включить Hermes API Server
Проверить или задать:
- `API_SERVER_ENABLED=true`
- `API_SERVER_HOST=127.0.0.1`
- `API_SERVER_PORT=8642`
- `API_SERVER_CORS_ORIGINS=http://127.0.0.1:8793`
- `API_SERVER_KEY=...`

## 4. Определиться с first-run режимом
Если нужен полностью тестовый старт на пустом сервере, оставь включённым demo-seed backend.
Тогда на пустой DuckDB backend сам создаст стартовые учётки `misha@demo.local / demo123` и `admin@demo.local / demo123`.

Если нужен production-like запуск без demo-данных, это нужно отдельно учесть в env/config и не полагаться на demo-учётки.

## 5. Установить зависимости проекта
- `./deploy/package/install-project-deps.sh`

## 6. Установить systemd user units
- `./deploy/package/install-systemd-user.sh /absolute/path/to/project`

## 6. Поднять сервисы
- `systemctl --user restart hermes-web-backend-8791.service hermes-web-copilotkit-8794.service hermes-web-frontend-8793.service`

## 7. Проверить контур
- `./deploy/package/verify-deployment.sh`

## 8. Проверить пользовательский сценарий
- `docs/TESTING_SCENARIO.md`

## 9. При наличии browser runtime прогнать UI smoke
- `./scripts/run_ui_acceptance_smoke.sh`

Важно:
- browser smoke требует подготовленного browser runtime и browser libs;
- frontend, backend и CopilotKit runtime должны быть из одного project root.
