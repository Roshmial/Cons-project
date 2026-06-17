# Contour map

## Основные runtime-компоненты на 178

- `8791` — backend API и основная бизнес-логика Hermes Web.
- `8793` — frontend runtime на том же хосте.
- `8794` — CopilotKit runtime.
- `tg-api.service` — отдельный Telegram API / monitoring contour.
- `hermes-gateway.service` — messaging gateway Hermes.

## Логика хранения

- Это standalone backup одного хоста, в отличие от combined backup 95+178.
- Он нужен, когда требуется поднять именно сервер 178 как самодостаточный runtime-contour со всеми локальными артефактами, кроме secrets/state.
