# Cons project backup — standalone 178

Это standalone curated backup рабочего контура на 178.104.207.89: backend/runtime, frontend 8793, CopilotKit 8794, TG-API, Hermes runtime и deploy-артефакты.

Что включено:
- `project/**` — код проекта `hermes-web-mvp-react-8793` с deploy/package, docs и scripts
- `tg-api/**` — operational код и конфигурация TG API без runtime/state/secrets
- `runtime-systemd/**` — user-level unit и drop-in файлы текущего live-контура
- `hermes-runtime/**` — `config.yaml`, `cron/jobs.json`, `scripts/*`
- root-docs по архитектуре, логике, zero-start развёртке и model fallback

Что исключено:
- `.env*`, токены, auth/session state, runtime DB
- `services/backend/data/`, `node_modules/`, `.venv/`, build caches, logs
- TG API `session/`, `runtime/`, `raw_logs/`, `exports/`, `reports/`, `analytics/`

Назначение:
- полноценный backup под ключ именно для standalone-контура 178
- безопасная публикация в `Cons-project` на отдельной ветке без перезаписи combined backup с 95

Последнее обновление: 2026-07-20 01:30:22 UTC
