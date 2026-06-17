# TG API scope inside Cons-project backup

## Что включено

- Основной Python-код: `app.py`, `monitor_client.py`, `telegram_monitor_pipeline.py`, `collect_daily_pipeline.py` и связанные модули.
- Auth/web-flow: `telegram_web_auth.py`, `create_auth_link.py`, `check_chat_access.py`, `login.py`, `ensure_api.py`.
- Build/analytics helpers: `build_digest_context.py`, `build_export_dashboard.py`, `build_local_analytics_dashboard.py`, `generate_processed_csv.py`, `weekly_monitor_qa.py`.
- Конфиги и справочные файлы: `channels*.yml`, `requirements.txt`, `post_type_glossary.md`, `private_profile_setup.md`, `telegram_web_auth.md`, `instruction_for_tg_login.txt`, `run_tg_api_service.sh`, `install_hermes_tg_cron.py`, `hermes_tg_cron_manifest.json`.

## Что исключено

- `session/` и `*.session`;
- `runtime/`, `raw_logs/`, `archive/`, `exports/`, `reports/`;
- `private-profile.env`, auth/state-файлы и прочие чувствительные локальные артефакты;
- `.venv`, `__pycache__`, логи и временные generated outputs.

## Зачем TG API лежит в этом backup

- Это operational часть общего пользовательского контура на 95.
- Без неё backup `Cons-project` не отражал бы весь фактический runtime и вспомогательную автоматизацию агента.
