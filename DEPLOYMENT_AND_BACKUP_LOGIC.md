# Deployment and backup logic

## Что считается боевым контуром

- UI для пользователей: frontend на `95.182.85.233:8803`.
- Основной API/runtime: backend на `178.104.207.89:8791`.
- Дополнительные runtime-компоненты: frontend `8793` и CopilotKit `8794` на 178 как часть deploy/runtime контура.
- Telegram data contour: `TG-API` на 95 как отдельный, но связанный operational компонент.

## Почему backup комбинированный

- Если сохранять только 178, теряется реальный production frontend `8803`.
- Если сохранять только 95, теряется backend/deploy/runtime часть 178.
- Поэтому weekly refresh собирает combined backup из двух хостовых зон в один GitHub repo `Cons-project`.

## Что делает weekly refresh

1. Очищает только рабочие каталоги backup, не трогая `.git`.
2. Копирует локальный web project с 95 в `local-95/project`.
3. Копирует локальный TG API contour в `local-95/tg-api`, но без session/runtime/secrets.
4. Копирует relevant systemd unit/drop-in фронта `8803`.
5. По SSH забирает curated snapshot проекта и systemd-логики с 178 в `remote-178/**`.
6. Перегенерирует описательные root-файлы репозитория.
7. Делает `git add`, commit и push в `origin/main`, если есть изменения.

## Расписание

- Hermes cron job: `cons-project-backup-weekly`
- Job id: `cf27d7146dc2`
- Schedule: `0 1 * * 1` (это `04:00 МСК`, то есть внутри окна `03:00–06:00 МСК`).

## Что не попадает в GitHub backup

- secrets и `.env*`;
- runtime DB и локальные state-файлы;
- TG API `session/`, `runtime/`, `raw_logs/`, `exports/`, `reports/`;
- кэши, `node_modules`, `.venv`, build artifacts, логи.
