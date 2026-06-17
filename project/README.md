# Hermes Web MVP

## Что это

Hermes Web MVP — local-first web-интерфейс вокруг Hermes Agent с разделением на три независимых runtime-компонента:
- frontend React/Vite на `8793`;
- backend API на `8791`;
- CopilotKit runtime на `8794`.

Канонический пользовательский контур:
`Browser -> Frontend 8793 -> Backend 8791 -> Hermes API Server 8642/v1`

CopilotKit runtime работает отдельным внутренним контуром и не заменяет backend. Он используется как вспомогательный runtime для chat-first сценариев, а не как самостоятельный источник истины по данным, пользователям и истории.

## Для кого система

Система рассчитана на два основных типа ролей:
- пользователь — ведёт чаты, работает с файлами, профилем и задачами без доступа к глобальным настройкам;
- администратор — управляет пользователями, справочниками, объявлениями, политикой источников и состоянием рабочего контура.

## Что реально проверено

На текущем состоянии проекта подтверждено:
- `python3 -m py_compile services/backend/app.py` — успешно;
- `npm run react:build` — успешно;
- `python3 -m unittest services/backend/test_smoke.py` — 7 тестов, `OK`;
- live runtime на канонических портах поднят:
  - `8791` backend;
  - `8793` frontend;
  - `8794` CopilotKit runtime;
- login в живой backend подтверждён;
- `GET/PATCH/GET /api/admin/dashboard-policy` подтверждён на live runtime;
- перенос коннектора между внутренним и внешним контуром подтверждён на live runtime и затем возвращён в исходное состояние;
- `scripts/ui_acceptance_smoke_react.mjs` подтвердил живой round-trip по chat/profile/jobs/admin, включая create user и pause/resume job.

## Ключевые продуктовые договорённости

### 1. Пользовательская модель policy

В чате пользователь видит только три режима:
- `local_only`
- `local_first`
- `global_only`

Пользователь не управляет составом реестра источников и не раскладывает коннекторы по контурам вручную.

### 2. Явный источник — не отдельный глобальный режим

Сценарии вида:
- «проанализируй этот файл»;
- «возьми эту ссылку»;
- «построй по конкретному датасету»

трактуются как request-level source override, а не как отдельный четвёртый пользовательский режим.

### 3. Классификация internal/external управляется из админки

Принадлежность API или маршрута к внутреннему либо внешнему контуру задаётся администратором. Эта классификация хранится как override поверх системного inventory, а не как одноразовый эффект discovery.

## Основные возможности

### Пользовательский контур
- login/logout и восстановление сессии;
- профиль пользователя и персонализация;
- список чатов;
- создание, переименование и архивирование чатов;
- история сообщений;
- отправка сообщений и файлов;
- dashboard-oriented запросы;
- feedback по ответам;
- задачи и подписки в пользовательском объёме.

### Админский контур
- обзор рабочего контура;
- состояние пользователей, чатов и задач;
- CRUD по пользователям;
- справочники и их история изменений;
- объявление в чате;
- политика источников;
- разрешённые источники;
- классификация коннекторов на внутренний и внешний контур;
- versioning и audit trail для админских сущностей.

## Важные файлы

### Runtime и запуск
- `run_backend_service.sh`
- `run_frontend_react_service.sh`
- `run_copilotkit_runtime_service.sh`
- `services/backend/app.py`
- `services/backend/test_smoke.py`
- `services/backend/data/hermes_web_app.duckdb`

### Frontend
- `services/frontend-react/src/App.jsx`
- `services/frontend-react/src/api.js`
- `services/frontend-react/src/styles.css`

### Документация
- `docs/SYSTEM_OVERVIEW.md`
- `docs/DEPLOYMENT_GUIDE.md`
- `docs/TESTING_SCENARIO.md`
- `docs/BACKLOG.md`
- `deploy/package/README.md`

## Порты и адреса
- frontend: `http://127.0.0.1:8793`
- backend: `http://127.0.0.1:8791`
- CopilotKit runtime: `http://127.0.0.1:8794`
- Hermes API Server: `http://127.0.0.1:8642/v1`

## Быстрый локальный запуск

1. Убедиться, что Hermes gateway и Hermes API Server доступны.
2. Запустить backend:
   `./run_backend_service.sh`
3. Запустить CopilotKit runtime:
   `./run_copilotkit_runtime_service.sh`
4. Запустить frontend:
   `./run_frontend_react_service.sh`
5. Открыть `http://127.0.0.1:8793`

## Проверки

Минимальный набор:
- `python3 -m py_compile services/backend/app.py`
- `npm run react:build`
- `python3 -m unittest services/backend/test_smoke.py`

## Следующие эксплуатационные документы

Для полного понимания системы смотри:
- `docs/SYSTEM_OVERVIEW.md` — полное описание системы;
- `docs/DEPLOYMENT_GUIDE.md` — развёртывание на новом сервере;
- `docs/TESTING_SCENARIO.md` — пользовательский сценарий тестирования для роли user;
- `deploy/package/README.md` — состав deploy-пакета и порядок применения.
