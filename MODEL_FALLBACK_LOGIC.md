# Model fallback logic

## Текущая зафиксированная конфигурация

- Primary provider: `openai-codex`
- Primary model: `gpt-5.4`
- `model.fallback_providers`: `["openai-codex"]`
- `model.fallback_models`: `["gemma-4-26b-a4b-it", "gpt-5.4"]`
- Auxiliary routes: `custom` provider на `http://127.0.0.1:8080/v1` с моделью `gemma-4-26b-a4b-it` для `vision`, `web_extract`, `compression`, `skills_hub`, `approval`, `mcp`, `title_generation`.

## Логическая схема

1. Основной chat/runtime contour должен быть доступен через `openai-codex` + `gpt-5.4`.
2. Если основной вызов не отрабатывает, Hermes использует fallback-маршрут в пределах описанной цепочки.
3. Auxiliary-операции не обязаны идти через тот же route: для них уже предусмотрен отдельный локальный inference endpoint.
4. Поэтому при развёртке нужно мыслить двумя слоями: primary inference и auxiliary inference.

## Практический алгоритм ввода в строй

1. Поднять и проверить основной provider route.
2. Поднять и проверить локальный `127.0.0.1:8080/v1`, если в контуре используются auxiliary-задачи.
3. Только после этого включать jobs, browser acceptance и прочие сценарии, которые зависят от этих маршрутов.
4. Если primary route жив, а auxiliary route мёртв, базовый чат может работать, но часть automation будет деградировать или падать.
5. Если нужен перенос на новый сервер, переносить надо не только `config.yaml`, но и сам локальный inference contour, если он используется фактически.
