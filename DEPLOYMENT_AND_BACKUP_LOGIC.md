# Deployment and backup logic

## Что входит в контур

- Web project: backend, frontend, CopilotKit, deploy package, docs, scripts.
- TG API contour как отдельный operational слой на том же сервере.
- Hermes runtime layer: config, jobs, scripts, gateway/runtime units.

## Почему ветка отдельная

- Combined backup на 95 и standalone backup 178 решают разные задачи.
- Поэтому standalone 178 публикуется в тот же GitHub repo, но в отдельную ветку `standalone-178`, чтобы не ломать `main`.

## Что делает weekly refresh

1. Пересобирает curated snapshot `project/`, `tg-api/`, `runtime-systemd/`, `hermes-runtime/`.
2. Перегенерирует описательные документы.
3. Делает commit и push в ветку `standalone-178`.
