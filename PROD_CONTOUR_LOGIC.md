# Production contour logic

1. Пользователь приходит во frontend `8793`.
2. Frontend обращается к backend `8791`.
3. Backend обслуживает chat, jobs, dashboard и смежные runtime-пайплайны.
4. CopilotKit runtime `8794` используется как дополнительный слой там, где он нужен.
5. TG-API параллельно обслуживает Telegram auth/monitoring/digest сценарии.
6. Hermes runtime layer управляет jobs/scripts/gateway поверх этого же хоста.
