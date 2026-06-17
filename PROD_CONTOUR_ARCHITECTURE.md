# Production contour architecture

## Короткая схема

```
Пользователь / браузер
        |
        v
95.182.85.233 :8803  (production frontend)
        |
        | HTTP / API proxy
        v
178.104.207.89 :8791 (backend API)
        |\
        | \
        |  +--> Hermes / jobs / chat runtime
        |
        +----> 178 :8794 (CopilotKit runtime, when needed)

95.182.85.233 : TG-API
        |
        +--> Telegram monitoring / digest / auth helper contour
```

## Архитектурные роли

- `95:8803` — пользовательская точка входа и production UI.
- `178:8791` — канонический backend/API и логика чатов, задач, jobs, dashboard и routing.
- `178:8794` — вспомогательный runtime для CopilotKit-сценариев.
- `95/TG-API` — отдельный operational контур Telegram-данных, связанный с общим продуктовым контуром, но не являющийся частью browser UI runtime.

## Что важно не путать

- Физическое размещение и логическая принадлежность — не одно и то же.
- Frontend `8803` физически живёт на 95, но логически относится к prod-контуру агента на 178.
- Поэтому архитектурно контур split-host, а backup должен быть combined.
