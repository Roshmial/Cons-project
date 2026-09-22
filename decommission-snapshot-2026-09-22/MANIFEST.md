# Snapshot before decommission of 178

Created: 2026-09-22 UTC

Included:
- systemd user unit files and non-secret Hermes configuration example
- current Hermes cron definitions
- Hermes Web DuckDB data directory
- Memory Archive source, database, originals and derived artifacts (models excluded: downloadable dependency)
- TG API runtime data and collection history

Excluded intentionally:
- credentials, auth files, SSH keys, Telegram session, .env files
- Hermes state.db and session history: no user-facing data is being preserved from this retired runtime
- virtualenvs, node_modules, caches, logs and downloadable models

Restore: use project source in this repository, restore data folders to their original relative paths, set fresh credentials, install dependencies, then enable only services actually required on the new host.
