# Cons project backup

Это curated backup составного живого контура Hermes Web: frontend 8803 на сервере 95.182.85.233 + backend/runtime-контур на 178.104.207.89.

Что включено:
- local-95: production frontend contour 8803, project code, launcher-скрипты и systemd units
- remote-178: backend/runtime/deploy contour, project code, launcher-скрипты и systemd units
- deploy/package, docs, scripts, backend/frontend-react/frontend компоненты

Что исключено:
- node_modules, dist, .venv
- services/backend/data и runtime DB
- .env*, логи, кэши, __pycache__, runtime-артефакты

Назначение:
- backup полного рабочего контура агента под репозиторий Cons-project
- хранение frontend 8803 и backend 178 в одном private GitHub repo

Последнее обновление: 2026-06-17 19:55:35 UTC
