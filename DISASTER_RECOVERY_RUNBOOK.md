# Zero-start deployment runbook

Это runbook для развёртки standalone-контура 178 с нуля на чистом Linux-сервере.

## Минимальная шпаргалка по командам

```bash
git clone --branch standalone-178 git@github.com:Roshmial/Cons-project.git ~/cons-project-178
cd ~/cons-project-178/project
cp deploy/package/env/hermes-web.env.example ~/.hermes/.env   # как шаблон, затем заполнить вручную
bash deploy/package/bootstrap-hermes-zero-server.sh
bash deploy/package/install-project-deps.sh
bash deploy/package/install-systemd-user.sh $(pwd)
systemctl --user daemon-reload
systemctl --user enable --now hermes-web-backend-8791.service
systemctl --user enable --now hermes-web-frontend-8793.service
systemctl --user enable --now hermes-web-copilotkit-8794.service
bash deploy/package/verify-deployment.sh
```

## TG-API

1. Развернуть каталог `tg-api/` в отдельный рабочий путь.
2. Внести вручную `private-profile.env`, session-файлы и auth state.
3. Проверить ручной запуск.
4. Только потом активировать `tg-api.service` и связанные cron/jobs.

## Hermes layer

1. Установить Hermes: `curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash`.
2. Восстановить `hermes-runtime/config.yaml`, `hermes-runtime/cron/jobs.json`, `hermes-runtime/scripts/*` при необходимости.
3. Не переносить secrets/state автоматически; их нужно заполнить локально.
4. Проверить `hermes doctor` и `hermes cron list`.

## Проверка

- backend `8791` отвечает
- frontend `8793` открывается
- CopilotKit `8794` жив
- TG-API запускается
- gateway/jobs не падают после включения
