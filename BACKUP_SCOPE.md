# Backup scope

- `local-95/project/**` — локальный prod/frontend contour 8803
- `local-95/tg-api/**` — код и конфигурация TG API контура на 95
- `local-95/runtime-systemd/**` — unit/drop-in фронта 8803
- `remote-178/project/**` — backend/runtime/deploy contour 178
- `remote-178/runtime-systemd/**` — systemd units и backend drop-ins 178

Осознанно исключено:
- runtime-данные, БД, логи, кэши, `.env*`, TG API session и export-артефакты
