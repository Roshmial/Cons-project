# Contour map

## Сервер 95.182.85.233

- `hermes-web-mvp-react-8793` — локальный project snapshot, из которого берётся production frontend contour `8803`.
- `local-95/runtime-systemd/hermes-web-frontend-8803.service` — unit фронта `8803`.
- `local-95/tg-api/**` — Telegram API/monitoring contour: сбор, подготовка daily digest, web auth, cron/install-скрипты, channel-конфиги и вспомогательная аналитика.
- Логическая роль: пользовательский frontend и TG API находятся на 95, но являются частью общего рабочего контура агента.

## Сервер 178.104.207.89

- `remote-178/project/services/backend/**` — основной backend/API-контур `8791`.
- `remote-178/project/services/frontend/**` и `services/frontend-react/**` — кодовые артефакты backend-side web проекта и deploy package.
- `remote-178/project/deploy/package/**` — package/deploy/runbook/install-логика.
- `remote-178/runtime-systemd/**` — unit-файлы backend, frontend `8793`, CopilotKit `8794` и backend drop-ins.

## Логика хранения

- Репозиторий `Cons-project` — это не просто snapshot одного хоста, а curated combined backup общего боевого контура.
- `local-95` хранит то, что физически живёт на 95 и нужно для работы контура 178.
- `remote-178` хранит runtime/deploy/backend часть, которая физически живёт на 178.
