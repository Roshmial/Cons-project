# Backlog доработок

## 2026-06-11 — React acceptance и backend concurrency добиты, остаются только hardening-хвосты

Статус:
- обновлено 2026-06-11
- основной regression и live smoke закрыты

Что было проблемой:
- `/api/admin/chat-notice` мог нестабильно падать под параллельной нагрузкой при открытии DuckDB-соединения;
- `scripts/ui_acceptance_smoke_react.mjs` был хрупким в admin-части: использовал restore-path через `localStorage` и `reload`, из-за чего acceptance иногда ломался не по продуктовой причине, а на самом тестовом сценарии.

Что подтверждено сейчас:
- backend race закрыт retry-механизмом в `services/backend/app.py`;
- в `services/backend/test_smoke.py` добавлен конкурентный regression-тест на `/api/admin/chat-notice`;
- `scripts/ui_acceptance_smoke_react.mjs` переведён на устойчивый path через реальные admin-tab-кнопки и явные ожидания активной секции/модалки;
- полный live smoke теперь проходит end-to-end.

Фактические проверки:
- `python3 -m py_compile services/backend/app.py` → OK;
- `python3 -m unittest services/backend/test_smoke.py` → `Ran 10 tests ... OK`;
- `npm run react:build` → OK;
- `source scripts/runtime_env.sh && ./scripts/browser_runtime_env.sh node scripts/ui_acceptance_smoke_react.mjs` → OK.

Что больше не является backlog-проблемой:
- нестабильное переключение `Обзор / Пользователи / Операции / Справочники` в текущем headless acceptance;
- хвост вида «full acceptance ещё нужно довести».

Что реально осталось:
1. При желании усилить `loadAdmin()` защитой от stale async-ответов через request token / sequence guard, чтобы дополнительно снизить риск подобных UI-гонок в будущем.
2. Периодически синхронизировать `ui_acceptance_smoke_react.mjs` с актуальными label/placeholder/табами UI, если экран дальше будет меняться.
3. Отдельно решить судьбу legacy backup-баз и соседнего legacy runtime, чтобы не плодить ложные контуры при ручной диагностике.

Почему это важно:
- теперь речь уже не о незакрытом дефекте, а о профилактическом hardening;
- следующий цикл изменений можно планировать от рабочего baseline, а не от плавающей acceptance-приёмки.
