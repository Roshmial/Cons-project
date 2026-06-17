# Dependency inventory for Hermes Web MVP

## 1. Системные зависимости нового сервера

Минимум:
- Linux x86_64
- bash
- curl
- tar
- systemd user services
- Python 3.12+
- python3-venv
- Node.js 20+
- npm

Для smoke/browser acceptance дополнительно нужны runtime-библиотеки браузера.
Канонический путь в этом проекте:
- browser runtime root: `$HOME/.local/browser-runtime/root`
- browser libs root: `$HOME/.hermes/browser-libs/root`

## 2. Backend Python dependencies

Фактически подтверждённый набор из venv:
- blinker==1.9.0
- click==8.4.1
- duckdb==1.5.3
- Flask==3.1.3
- itsdangerous==2.2.0
- Jinja2==3.1.6
- MarkupSafe==3.0.3
- waitress==3.0.2
- Werkzeug==3.1.8

Минимальный source requirements-файл проекта:
- flask
- duckdb
- werkzeug
- waitress

## 3. Frontend / runtime Node dependencies

Фактически подтверждённый верхний уровень:
- @copilotkit/react-core==1.59.5
- @copilotkit/react-ui==1.59.5
- @copilotkit/runtime==1.59.5
- @copilotkit/runtime-client-gql==1.59.5
- playwright==1.60.0
- react==18.3.1
- react-dom==18.3.1
- @vitejs/plugin-react==4.7.0
- vite==5.4.21

## 4. Что нужно именно для Hermes

Для работы web-контура Hermes нужен не просто установленный CLI, а минимально настроенный runtime:
- Hermes Agent установлен;
- Hermes gateway установлен и запускается;
- Hermes API Server включён;
- настроен хотя бы один рабочий model/provider для API Server;
- в `~/.hermes/.env` задан `API_SERVER_KEY`;
- CORS для frontend разрешён.

Практически необходимы:
- `hermes setup`
- `hermes doctor`
- `hermes gateway install`
- `hermes gateway status`
- `hermes config set ...` для API Server

## 5. First-run и стартовые данные

Backend умеет автоматически засидить стартовые demo-учётки и демо-данные на пустой базе через `seed_if_empty(...)`, если включён demo-mode.

На практике это означает:
- для completely fresh server можно поднять систему с пустой DuckDB;
- если demo-data включены, backend сам создаст как минимум `misha@demo.local / demo123` и `admin@demo.local / demo123`;
- для production-like контура эти учётки потом нужно заменить или отключить demo-seed.

## 6. Что нужно для проверки работоспособности

Минимум:
- backend venv и Python dependencies;
- node_modules проекта;
- Playwright package;
- browser runtime env wrapper;
- smoke user credentials;
- рабочий Hermes API Server.

Команды проверки:
- `python3 -m py_compile services/backend/app.py`
- `npm run react:build`
- `python3 -m unittest services/backend/test_smoke.py`
- `./deploy/package/verify-deployment.sh`
- `./scripts/run_ui_acceptance_smoke.sh`
