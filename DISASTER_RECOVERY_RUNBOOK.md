# Zero-start deployment runbook

Это runbook не про восстановление старого state 1:1, а про развёртку рабочего prod-контура с нуля на чистой базе.

## Цель

- Поднять с нуля split-host контур, эквивалентный текущему production: frontend на 95, backend/runtime на 178, TG-API на 95.
- Использовать `Cons-project` как curated source of truth по коду, deploy-логике и architecture docs.

## Что нужно заранее

- Два Linux-хоста или их функциональные аналоги: один под frontend/TG-API, второй под backend/runtime.
- Установленные `git`, `python3`, `node`, `npm`, `systemd --user`, `ssh`.
- Установленный Hermes там, где он нужен для cron/scripts/agent runtime.
- Локально подготовленные secrets вне Git: `.env`, `~/.hermes/.env`, auth/session tokens, TG API private env и session state.

## Канонические каталоги из backup

- `local-95/project/` — frontend-oriented project snapshot.
- `local-95/runtime-systemd/` — unit/drop-in фронта 8803.
- `local-95/tg-api/` — operational TG API contour.
- `remote-178/project/` — backend/runtime/deploy snapshot.
- `remote-178/runtime-systemd/` — unit/drop-in backend/frontend/CopilotKit на 178.
- `remote-178/project/deploy/package/` — deploy package и server bootstrap docs.

## Минимальная шпаргалка по командам

### Backend/runtime-хост

```bash
git clone <cons-project-repo> ~/cons-project
cd ~/cons-project/remote-178/project
cp deploy/package/env/hermes-web.env.example ~/.hermes/.env   # как шаблон, затем заполнить вручную
bash deploy/package/bootstrap-hermes-zero-server.sh
bash deploy/package/install-project-deps.sh
bash deploy/package/install-systemd-user.sh $(pwd)
systemctl --user daemon-reload
systemctl --user enable --now hermes-web-backend-8791.service
systemctl --user enable --now hermes-web-frontend-8793.service
systemctl --user enable --now hermes-web-copilotkit-8794.service
bash deploy/package/verify-deployment.sh
```

### Frontend/TG-API-хост

```bash
git clone <cons-project-repo> ~/cons-project
cd ~/cons-project/local-95/project
# заполнить локальные env для frontend вручную
systemctl --user daemon-reload
systemctl --user enable --now hermes-web-frontend-8803.service

cd ~/cons-project/local-95/tg-api
# внести private-profile.env / session / auth state вручную
# затем проверить ручной запуск TG API и только потом включать cron
```

### Hermes-слой

```bash
curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash
hermes setup
hermes doctor
hermes cron list
```

## Шаг 1. Подготовить backend/runtime-хост

1. Развернуть `remote-178/project/` в целевой project root.
2. Прочитать и выполнить шаги из `remote-178/project/deploy/package/README.md`.
3. Использовать `deploy/package/bootstrap-hermes-zero-server.sh` и `install-project-deps.sh`, если сервер действительно чистый.
4. Подготовить `~/.hermes/.env` и project env по примеру `deploy/package/env/hermes-web.env.example`.
5. Установить user-level systemd units из `remote-178/runtime-systemd/` или через `install-systemd-user.sh`.
6. Запустить backend `8791`, frontend `8793` и CopilotKit `8794`, если он нужен в контуре.

## Шаг 2. Подготовить frontend/TG-API-хост

1. Развернуть `local-95/project/` в отдельный project root фронта.
2. Проверить, что frontend-конфиг указывает на целевой backend `8791`, а не на старый адрес по умолчанию.
3. Установить и активировать unit `local-95/runtime-systemd/hermes-web-frontend-8803.service` и его drop-in, если он есть.
4. Развернуть `local-95/tg-api/` в отдельный рабочий каталог.
5. Внести вручную TG API private env, auth-link state и session-данные, которые не входят в backup.
6. При необходимости восстановить Hermes cron/automation для TG API только после проверки ручного запуска.

## Шаг 3. Подготовить Hermes-слой

1. Установить Hermes на нужных хостах: `curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash`.
2. Выполнить `hermes setup` или перенести curated config отдельно из Eva backup / локального контура, если нужен конкретный профиль поведения.
3. Не переносить автоматически secrets из старой машины; их нужно вносить заново локально.
4. Cron/jobs поднимать только после проверки, что web и TG API контуры реально живы.

## Шаг 4. Проверка после развёртки

1. Проверить health backend `8791`.
2. Проверить доступность production frontend `8803`.
3. Проверить round-trip: UI -> backend -> ответ.
4. Проверить запуск TG API и его auth/helper flow.
5. Если используется deploy package acceptance, выполнить `verify-deployment.sh`.
6. Только после этого включать периодические jobs и weekly automation.

## Логика fallback для моделей

- Базовый provider: `openai-codex`.
- Базовая модель: `gpt-5.4`.
- Configured fallback providers: `["openai-codex"]`.
- Configured fallback models: `["gemma-4-26b-a4b-it", "gpt-5.4"]`.

### Алгоритм

1. Hermes сначала пытается отработать на основном маршруте: provider `openai-codex`, model `gpt-5.4`.
2. Если основной вызов недоступен или не проходит по runtime-условиям маршрутизации, используется fallback-цепочка моделей из конфига.
3. В текущем backup это означает: сначала fallback на `gemma-4-26b-a4b-it`, затем повторный fallback на `gpt-5.4` внутри того же provider-контекста, если маршрут позволяет.
4. Для auxiliary-задач (`vision`, `web_extract`, `compression`, `skills_hub`, `approval`, `mcp`, `title_generation`) уже зафиксирован отдельный локальный маршрут через `custom` provider и `http://127.0.0.1:8080/v1` с моделью `gemma-4-26b-a4b-it`.
5. Практическое правило для развёртки: сначала поднимать primary route, затем локальный auxiliary route, и только потом включать jobs, которые зависят от обоих уровней.

### Что проверить после развёртки

- `hermes doctor` не показывает сломанную конфигурацию.
- `hermes chat -q "ping"` отвечает на primary route.
- auxiliary/local route отвечает отдельно, если он используется в контуре.
- cron/jobs, завязанные на локальный auxiliary inference, не падают из-за отсутствия `127.0.0.1:8080/v1`.

## Что не надо делать

- Не смешивать frontend из одного project root и backend из другого без явной сверки env и unit-файлов.
- Не копировать в Git и на новую машину старые runtime DB, `.env`, session/auth state как часть backup-репозитория.
- Не считать, что один сервер полностью описывает весь prod-контур: он split-host по определению.
- Не включать cron до проверки primary и auxiliary model routes, если контур зависит от обоих.

## Практический смысл

Этот runbook нужен, чтобы с нуля развернуть рабочий контур, а не только хранить архив кода. Он фиксирует порядок ввода в строй, границы между 95 и 178, минимальную командную шпаргалку и места, где нужны ручные локальные секреты.
