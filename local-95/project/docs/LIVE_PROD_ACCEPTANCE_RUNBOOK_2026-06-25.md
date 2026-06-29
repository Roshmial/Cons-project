# Hermes Web live acceptance + deploy/verify runbook

Дата: 2026-06-25

Актуальный прод-контур:
- public frontend: `http://95.182.85.233:8803/`
- backend host/API: `http://178.104.207.89:8791/api`
- runtime host: `178.104.207.89`
- frontend service: `hermes-web-frontend-8803.service`
- backend service: `hermes-web-backend-8791.service`

## 1. Что считать базовой живостью

Минимум перед приёмкой:

```bash
systemctl --user --no-pager --full status hermes-web-backend-8791.service hermes-web-frontend-8803.service
ss -ltnp | egrep ':(8791|8803)\b'
curl -fsS http://127.0.0.1:8791/api/service-info && echo
curl -I -fsS http://95.182.85.233:8803/ | head -n 5
```

Ожидаемо:
- backend `active (running)`;
- frontend `active (running)`;
- `8791` слушает backend;
- `8803` слушает prod frontend;
- `service-info` отвечает `status=ok`.

## 2. Safe backend rollout

Если менялся backend-код:

1. Сделать backup текущего `services/backend/app.py` на `178`.
2. Выкатить обновлённый файл.
3. Прогнать syntax-check на хосте.
4. Перезапустить backend.
5. Сразу проверить `api/service-info` и один реальный user-path smoke.

Проверенный путь из этой итерации:

```bash
ssh 178.104.207.89 'mkdir -p /home/hermes/backups/hermes-web-backend && cp /home/hermes/workspace/hermes-web-mvp-react-8793/services/backend/app.py /home/hermes/backups/hermes-web-backend/app.py.$(date -u +%Y%m%dT%H%M%SZ)'
scp services/backend/app.py 178.104.207.89:/home/hermes/workspace/hermes-web-mvp-react-8793/services/backend/app.py
ssh 178.104.207.89 'cd /home/hermes/workspace/hermes-web-mvp-react-8793 && python3 -m py_compile services/backend/app.py'
scp /home/hermes/workspace/restart_backend_8791_live.sh 178.104.207.89:/tmp/restart_backend_8791_live.sh
ssh 178.104.207.89 'bash /tmp/restart_backend_8791_live.sh'
```

Важно:
- не считать rollout подтверждённым только по `py_compile` или `health`;
- после restart обязательно пройти хотя бы один реальный post-login user path.

## 3. Browser-driven acceptance после логина

Рекомендуемый путь — через Playwright smoke script:

```bash
export HERMES_WEB_FRONTEND_URL='http://95.182.85.233:8803/'
export HERMES_WEB_FRONTEND_PORT='8803'
export HERMES_WEB_FRONTEND_BACKEND_BASE='http://178.104.207.89:8791'
export HERMES_WEB_BACKEND_API='http://178.104.207.89:8791/api'
export HERMES_WEB_SMOKE_EMAIL='<live smoke user email>'
export HERMES_WEB_SMOKE_PASSWORD='<live smoke user password>'
./scripts/browser_runtime_env.sh node scripts/ui_acceptance_smoke_react.mjs
```

Что этот smoke теперь реально проверяет:
- login через live API;
- открытие `Чаты`;
- upload файла через кнопку `Файлы`;
- отправку сообщения через кнопку `↑`;
- `Профиль` и список файлов;
- `Задачи`: создание задачи, pause/resume;
- `Управление`: `Пользователи`, `Операции`, `Справочники`, создание пользователя.

## 4. Что было обновлено в smoke под текущий live UI

В этой итерации подтверждено, что старый smoke drift'анул относительно живого UI. Для актуального контура пришлось учесть:
- upload input появляется только после нажатия `Файлы`;
- поле сообщения имеет placeholder `Сообщение`;
- кнопка отправки — `↑`, а не `Отправить`;
- admin tabs больше не используют `data-admin-section`, а переключаются кнопками по тексту.

## 5. Критерий pass

Acceptance считать зелёным, если smoke возвращает JSON с такими флагами:
- `chat: true`
- `profile: true`
- `jobs_create: true`
- `jobs_pause_resume: true`
- `admin_user_create: true`
- `admin_operations_tab: true`
- `admin_references_tab: true`

## 6. Критерий fail

Acceptance не считать закрытым, если:
- login проходит только по API, а UI после логина не доходит до рабочих экранов;
- задачи/чат завершаются только после ручного backend rescue;
- есть `health=ok`, но post-login flow ломается на реальном экране;
- smoke падает не на устаревшем селекторе, а на реальной пользовательской операции.

## 7. Проверенный результат этой итерации

Фактически подтверждено:
- public frontend `95.182.85.233:8803` жив;
- backend `178.104.207.89:8791/api` жив;
- создан отдельный временный acceptance admin;
- live browser smoke прошёл успешно после обновления smoke-сценария под текущий UI.
