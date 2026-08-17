# Cons project backup

Это curated backup составного живого контура Hermes Web: frontend 8803 на сервере 95.182.85.233 + backend/runtime-контур на 178.104.207.89 + TG API contour на 95.

Что включено:
- local-95: production frontend contour 8803, project code, launcher-скрипты и systemd units
- local-95/tg-api: код, конфиги, cron/install-логика и документация TG API контура
- remote-178: backend/runtime/deploy contour, project code, launcher-скрипты и systemd units
- deploy/package, docs, scripts, backend/frontend-react/frontend компоненты
- отдельные root-docs по архитектуре, логике и границам prod-контура

Что исключено:
- node_modules, dist, .venv
- services/backend/data и runtime DB
- TG API session/runtime/raw_logs/exports/reports/analytics и секретные env/state-файлы
- .env*, логи, кэши, __pycache__, runtime-артефакты

Назначение:
- backup полного рабочего контура агента под репозиторий Cons-project
- хранение frontend 8803, backend 178 и TG API в одном private GitHub repo

Последнее обновление: 2026-08-17 01:02:06 UTC
