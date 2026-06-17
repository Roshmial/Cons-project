# Backup scope

- `project/**` — live project snapshot 178 без data/secrets/runtime мусора
- `tg-api/**` — curated TG API snapshot 178 без state/runtime artifacts
- `runtime-systemd/**` — systemd user units и drop-ins
- `hermes-runtime/**` — локальный Hermes runtime layer

Excluded:
- `.env*`, auth/session state, logs, DB, caches, generated exports/analytics
