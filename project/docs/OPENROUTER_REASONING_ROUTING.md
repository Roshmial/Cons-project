# OpenRouter routing для Hermes Web backend

Этот документ описывает текущую логику маршрутизации запросов между двумя моделями OpenRouter в уже работающем Hermes Web backend.

## Цель

- по умолчанию все обычные запросы идут в `openrouter/owl-alpha`;
- `deepseek/deepseek-r1-0528` включается только для реально сложных reasoning-задач;
- для R1 действуют жёсткие лимиты по числу запросов и по суточному бюджету;
- решение остаётся прозрачным: маршрут и лимиты видны в backend health и meta ответа.

## Где реализовано

Основная логика живёт в `services/backend/app.py`:

- `route_task(task_description, user_id, usage_stats, request_policy)` — выбирает модель;
- `reasoning_usage_stats(...)` — считает глобальные и пользовательские лимиты по R1;
- `record_llm_usage_event(...)` — пишет usage-события в `app.llm_usage_events`;
- `call_hermes_api(...)` — общий orchestration-слой:
  - по умолчанию вызывает `owl-alpha`;
  - для reasoning-маршрута сначала сжимает контекст через default model;
  - потом отправляет сжатый контекст в R1;
  - при превышении лимитов делает fallback обратно в default model.

Дополнительные runtime defaults вынесены в `scripts/runtime_env.sh`.

## Схема хранения usage

Используется таблица backend DB:

- `app.llm_usage_events`

Поля:

- `usage_date`
- `user_id`
- `model_key`
- `route_mode`
- `route_reason`
- `estimated_cost_usd`
- `actual_cost_usd`
- `request_excerpt`
- `created_at`

Зачем это нужно:

- считать глобальный дневной лимит R1;
- считать дневной лимит R1 на пользователя;
- иметь прозрачный audit trail по включениям reasoning-модели.

## Текущая логика маршрутизации

Псевдокод:

```python
usage_stats = reasoning_usage_stats(conn, user_id)
route = route_task(task_description, user_id, usage_stats, request_policy)

if route.model == DEFAULT_MODEL:
    answer = call_hermes_messages(base_messages, model_name=DEFAULT_MODEL)

elif route.model == REASONING_MODEL:
    compressed_context = call_hermes_messages(summary_messages, model_name=DEFAULT_MODEL)
    answer = call_hermes_messages(reasoning_messages(compressed_context), model_name=REASONING_MODEL)
    record_llm_usage_event(...)

elif route.limit_reason is not None:
    answer = call_hermes_messages(base_messages, model_name=DEFAULT_MODEL)
    prepend_notice_about_limit()
```

Правила выбора:

1. По умолчанию — `openrouter/owl-alpha`.
2. R1 включается только если есть хотя бы один сигнал:
   - явный запрос пользователя на deep reasoning;
   - архитектурная/стратегическая задача;
   - анализ нескольких документов/источников;
   - высокая цена ошибки.
3. Если `HERMES_WEB_REASONING_MANUAL_ONLY=1`, автопереключение отключается и R1 включается только по явному запросу.
4. Если достигнут любой лимит, backend не вызывает R1 и делает fallback на `owl-alpha`.

## Что считается явным сигналом на R1

Сейчас backend распознаёт фразы вроде:

- `глубокий анализ`
- `используй R1`
- `запусти reasoning`
- `включи reasoning`
- `use r1`
- `deep analysis`

Также backend поддерживает задел под UI/manual switch через `request_policy.analysis_mode`:

- `deep` — ручной запрос на reasoning;
- `standard` — принудительно оставить обычный режим.

## Контекст перед R1

Перед вызовом R1 backend не отправляет всю сырую историю как есть.

Сначала default model делает компактное сжатие:

- цель пользователя;
- подтверждённые факты;
- открытые вопросы и конфликты;
- что именно надо решить.

Дальше именно это сжатое представление уходит в R1.

## Runtime-переменные

### Модели

- `HERMES_WEB_HERMES_API_MODEL=openrouter/owl-alpha`
- `HERMES_WEB_REASONING_MODEL=deepseek/deepseek-r1-0528`

### Переключатели

- `HERMES_WEB_REASONING_ROUTING_ENABLED=1` — включает автоматическую маршрутизацию;
- `HERMES_WEB_REASONING_MANUAL_ONLY=0` — если поставить `1`, автоматическое включение R1 отключится;
- `HERMES_WEB_REASONING_ENABLED=1` — общий kill switch для R1.

### Лимиты

- `HERMES_WEB_REASONING_DAILY_MAX_REQUESTS=60`
- `HERMES_WEB_REASONING_DAILY_MAX_PER_USER=6`
- `HERMES_WEB_REASONING_DAILY_MAX_COST_USD=2.5`
- `HERMES_WEB_REASONING_COST_FALLBACK_USD=0.20`

Последний параметр нужен как запасной механизм, если downstream usage не вернул реальную стоимость. Если Hermes/OpenRouter usage начнёт возвращать `cost`/`cost_usd`, backend возьмёт фактическое значение.

## UX-поведение

### Когда выбран R1

Backend добавляет заметку в начало ответа:

- что включён глубокий reasoning-режим;
- что он лимитирован и дороже обычного режима.

### Когда R1 недоступен из-за лимитов

Backend добавляет заметку:

- почему R1 не был вызван;
- что задача выполняется в обычном режиме через `owl-alpha`.

### Прозрачность

`GET /api/health` теперь показывает:

- default model;
- reasoning model;
- включена ли маршрутизация;
- manual-only или нет;
- текущие лимиты;
- текущий дневной usage по R1.

## Runbook

### 1. Как поменять лимиты

На сервере в `~/.hermes/.env`:

```bash
HERMES_WEB_REASONING_DAILY_MAX_REQUESTS=60
HERMES_WEB_REASONING_DAILY_MAX_PER_USER=6
HERMES_WEB_REASONING_DAILY_MAX_COST_USD=2.5
HERMES_WEB_REASONING_COST_FALLBACK_USD=0.20
```

Потом:

```bash
systemctl --user restart hermes-web-backend-8791.service
```

### 2. Как временно отключить R1 полностью

```bash
HERMES_WEB_REASONING_ENABLED=0
systemctl --user restart hermes-web-backend-8791.service
```

### 3. Как оставить только ручной запуск R1

```bash
HERMES_WEB_REASONING_ROUTING_ENABLED=1
HERMES_WEB_REASONING_MANUAL_ONLY=1
systemctl --user restart hermes-web-backend-8791.service
```

Тогда R1 включится только по явной команде пользователя.

### 4. Как полностью выключить автологику маршрутизации

```bash
HERMES_WEB_REASONING_ROUTING_ENABLED=0
systemctl --user restart hermes-web-backend-8791.service
```

В этом режиме всё пойдёт через default model.

### 5. Как сменить default model

```bash
HERMES_WEB_HERMES_API_MODEL=openrouter/owl-alpha
systemctl --user restart hermes-web-backend-8791.service
```

### 6. Как сменить reasoning model

```bash
HERMES_WEB_REASONING_MODEL=deepseek/deepseek-r1-0528
systemctl --user restart hermes-web-backend-8791.service
```

### 7. Где смотреть usage и состояние

Проверить health:

```bash
curl -s http://127.0.0.1:8791/api/health | jq '.llm_routing'
```

Проверить usage в БД:

```sql
SELECT usage_date, user_id, model_key, route_mode, route_reason,
       estimated_cost_usd, actual_cost_usd, created_at
FROM app.llm_usage_events
ORDER BY id DESC
LIMIT 50;
```

## Ограничения текущей версии

- ручной UI switch в web-интерфейсе пока не добавлен; сейчас ручной вызов R1 работает по явной фразе пользователя или через `request_policy.analysis_mode`;
- бюджетный лимит по долларам максимально точен только если downstream usage возвращает стоимость; иначе используется fallback estimate;
- классификация simple vs reasoning пока эвристическая, по ключевым сигналам и явному запросу пользователя.
