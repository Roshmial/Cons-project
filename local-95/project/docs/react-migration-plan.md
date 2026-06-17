# План миграции frontend -> React (отдельная копия)

## Цель

Перенести текущий frontend из `services/frontend/index.html + app.js` в React/Vite внутри отдельной копии проекта, не меняя backend-логику и не затрагивая legacy-frontend.

## Что уже сделано в этой копии

- создан новый React/Vite контур в `services/frontend-react`
- сохранён существующий backend API `/api`
- канонический backend этого контура: `http://127.0.0.1:8791`
- канонический frontend-порт React-контура: `8793`
- собран стартовый shell для:
  - первичной инициализации setup/status
  - login/logout
  - session restore
  - загрузки профиля
  - списка тредов
  - просмотра сообщений
  - отправки сообщений и файлов в существующий endpoint `/threads/{id}/messages`

## Архитектура переноса

### 1. Strangler pattern поверх текущего API

Backend остаётся источником истины. React UI работает как новый клиент к тем же endpoint'ам:

- `/api/auth/*`
- `/api/setup/*`
- `/api/me`
- `/api/bootstrap`
- `/api/threads*`
- `/api/messages/*`
- позже: `/api/jobs*`, `/api/admin*`, `/api/files*`

То есть перенос идёт не через переписывание backend, а через замену browser client слоя.

### 2. Разделение по слоям во frontend-react

- `src/api.js` — transport + token storage + error mapping
- `src/App.jsx` — orchestration и стартовый shell
- далее рекомендуется вынести:
  - `src/features/auth/*`
  - `src/features/chat/*`
  - `src/features/profile/*`
  - `src/features/jobs/*`
  - `src/features/admin/*`
  - `src/components/ui/*`
  - `src/state/*` или `src/store/*`

### 3. Local-first подход

На текущем этапе local-first сохраняется через:

- токен в `localStorage`
- dev proxy без дополнительного gateway
- работу React-frontend локально на `127.0.0.1:8793`
- reuse существующего backend storage и бизнес-логики

Следующий шаг — добавить клиентский cache/query слой, не меняя API:

- React Query или SWR для cache + refetch
- оптимистические обновления для тредов и сообщений
- локальный draft state для composer/job forms/profile

## Практический поэтапный план

### Этап 0. Базовый shell
- [x] Vite + React scaffold
- [x] dev proxy на backend
- [x] login/setup/session restore
- [x] chat list + thread detail + composer

### Этап 1. Паритет chat flow
- перенести unread/read state
- перенести rename/archive thread
- перенести feedback по сообщениям
- перенести прикрепление existing files
- вынести message/thread rendering в отдельные React components

### Этап 2. Profile и files
- перенести `/me`, personalization summary, style preview
- перенести смену пароля
- перенести список файлов и фильтры

### Этап 3. Jobs
- перенести jobs list/detail/meta
- затем job modal/create/edit/schedule flows
- сохранить все payload contract'ы backend без изменений

### Этап 4. Admin
- переносить секциями:
  1. overview
  2. users
  3. reference data
  4. events export
  5. chat notice
- для admin особенно важно сначала выделить typed API adapters и shared form state

### Этап 5. Stabilization
- Playwright/browser smoke должен идти на канонический React URL `8793`
- сравнение ключевых сценариев legacy vs React
- затем можно переключать основной frontend только после полного паритета

## Риски и замечания

- legacy `app.js` очень большой и смешивает state/render/networking, поэтому безопаснее мигрировать slice-by-slice, а не пытаться переносить всё одним коммитом
- если frontend идёт напрямую без proxy, CORS должен разрешать origin `http://127.0.0.1:8793`; в dev сейчас это закрывается текущим proxy-контуром
- admin/jobs ещё не перенесены — текущий scaffold закрывает только начальный chat/auth flow

## Команды

- dev: `npm run react:dev`
- build: `npm run react:build`
- preview: `npm run react:preview`
- helper script: `./run_frontend_react_service.sh`
