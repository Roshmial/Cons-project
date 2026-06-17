# Production contour architecture

```
Browser / user
    |
    v
178:8793  (frontend runtime)
    |
    v
178:8791  (backend API / chat / jobs / dashboard)
    |\
    | +--> 178:8794 (CopilotKit runtime)
    |
    +--> local Hermes runtime / jobs / scripts

178: TG-API
    |
    +--> Telegram monitoring / auth helper / digest contour
```

- Это single-host prod contour, где все runtime-компоненты живут на одной машине 178.
- TG-API логически отдельный operational слой, но физически расположен на том же сервере и поэтому входит в backup.
