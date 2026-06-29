# Sprint 1 Recurring Core Acceptance — Hermes Web MVP

Дата: 2026-06-24
Статус: implemented / verified locally
Назначение: зафиксировать, что именно считается done по Sprint 1 recurring core, чем это подтверждено и что ещё остаётся вне границы текущей приёмки.

## 1. Цель Sprint 1

Sprint 1 доводит recurring / cron / monitoring ядро до состояния, где оно:
- продуктово понятно пользователю;
- даёт единый контракт статусов и результатов;
- не смешивает delivery route и personal subscription;
- честно показывает stuck / pending / empty-result cases;
- имеет минимальную regression-проверку на recurring semantics.

## 2. Что реально внедрено

### 2.1 Backend: run/result contract
Файл:
- `services/backend/app.py`

Добавлено / усилено:
- `classify_job_run_surface(...)`
- `build_job_run_status_reason(...)`
- `build_job_run_status_detail(...)`
- `build_job_run_delivery_summary(...)`
- `serialize_job_run_row(...)`
- `fetch_job_runs(...)`
- расширенный last-run contract в jobs payload

Что это даёт:
- каждый run имеет user-visible поля:
  - `public_status`
  - `result_kind`
  - `status_reason`
  - `status_detail`
  - `delivery_summary`
  - `delivered_count`
  - `finished_at`
  - `duration_ms`
- UI больше не должен угадывать смысл raw `running/ok/error`.

### 2.2 Backend: recurring message contract
Файл:
- `services/backend/app.py`

Добавлено:
- `build_recurring_summary_envelope(...)`
- recurring summary в `serialize_message(...)`
- recurring-aware `derive_message_surface(...)`

Что это даёт:
- recurring/job family теперь получает единый summary envelope:
  - `status`
  - `summary`
  - `status_reason`
  - `status_detail`
  - `delivery_summary`
  - `result_kind`
  - `has_result`
  - `has_limitations`
  - `delivered_count`
- chat-side rendering может опираться на один contract, а не на россыпь частных `meta`-полей.

### 2.3 Backend: stuck / recovery baseline
Файл:
- `services/backend/app.py`

Добавлено:
- `CHAT_TASK_STUCK_SECONDS`
- `JOB_RUN_STUCK_SECONDS`
- `is_timestamp_stale(...)`
- `recover_stuck_chat_tasks(...)`
- stuck-aware serialization для `job_runs`
- stuck-aware recurring summary для `processing_status`
- recovery hook внутри `claim_pending_chat_tasks(...)`

Что это даёт:
- старый `running` больше не может бесконечно выглядеть как живой normal state;
- зависшие `chat_tasks` переводятся обратно в `pending` внутри текущего backend lifecycle;
- stuck recurring message получает явный `failed/stuck` смысл вместо вечного `running`.

### 2.4 Frontend: jobs UX cleanup
Файл:
- `services/frontend-react/src/App.jsx`

Добавлено / усилено:
- hero/detail block для активной задачи;
- отдельный блок `Итог последнего запуска`;
- operational `История запусков`;
- helper-функции humanize/status rendering;
- явное разделение:
  - `Куда отправляется результат`
  - `Моя подписка`

Что это даёт:
- jobs screen отвечает на нормальные operational questions:
  - запуск завершился или нет;
  - есть ли результат;
  - доставлен ли результат;
  - это ошибка, empty result или degraded;
  - подписан ли текущий пользователь лично.

### 2.5 Frontend: recurring chat rendering
Файл:
- `services/frontend-react/src/App.jsx`

Добавлено:
- отдельный recurring summary block в `MessageBubble(...)`

Что это даёт:
- recurring/job delivery messages отображаются как структурированный operational result, а не как обычный плоский assistant text.

## 3. Acceptance checklist

Sprint 1 считается принятым локально, если подтверждено всё ниже.

### 3.1 Backend semantics
- [x] run serialization отдаёт `public_status`, `result_kind`, `status_reason`, `status_detail`, `delivery_summary`
- [x] jobs payload несёт last-run contract, пригодный для UI
- [x] recurring messages получают `meta.recurring_summary`
- [x] message surface знает о recurring summary
- [x] stuck `job_run` сериализуется как `failed/stuck`
- [x] stuck `processing_status` сериализуется как `failed/stuck`
- [x] зависший `chat_task` возвращается в `pending`

### 3.2 Frontend UX
- [x] jobs detail показывает итог последнего запуска
- [x] jobs history показывает operational log вместо сырого статуса
- [x] доставка результата и подписка пользователя не смешаны
- [x] recurring summary рендерится отдельным блоком в chat UI
- [x] frontend собирается после изменений

### 3.3 Verification
- [x] `python3 -m py_compile services/backend/app.py services/backend/test_smoke.py`
- [x] targeted recurring smoke tests прошли
- [x] targeted stuck/pending smoke tests прошли
- [x] `npm run react:build` прошёл успешно

## 4. Локальный verification runbook

Минимальный порядок проверки:

### Backend
1. `python3 -m py_compile services/backend/app.py services/backend/test_smoke.py`
2. targeted tests на recurring summary:
   - `test_serialize_message_adds_surface_metadata`
   - `test_serialize_message_adds_recurring_summary_envelope_for_job_delivery`
   - `test_serialize_message_adds_recurring_summary_envelope_for_processing_status`
3. targeted tests на stuck/recovery:
   - `test_serialize_job_run_marks_stuck_running_as_failed`
   - `test_serialize_message_marks_stuck_processing_status`
   - `test_recover_stuck_chat_tasks_resets_running_task_to_pending`

### Frontend
1. `npm run react:build`
2. визуально проверить jobs detail/history и recurring message block на живом runtime, если runtime поднят.

## 5. Что реально проверено в этой сессии

Подтверждено:
- `python3 -m py_compile services/backend/app.py services/backend/test_smoke.py` → ok
- `npm run react:build` → ok
- programmatic runner для recurring summary tests → ok
- programmatic runner для stuck/recovery tests → ok

## 6. Что не считать закрытым этим документом

Этот acceptance документ не означает автоматически, что:
- live runtime уже перезапущен на новых артефактах;
- user-systemd units уже применены;
- production/server contour уже обновлён;
- выполнен end-to-end UI smoke в браузере на поднятом стенде.

Это локальная implementation + verification приёмка кода и артефактов.

## 7. Open questions

Следующий уровень после Sprint 1:
- live runtime acceptance на поднятом контуре;
- единый deploy/restart runbook для frontend/backend services;
- более широкий recurring end-to-end smoke, если нужен already-running стенд.

## 8. Короткий итог

Sprint 1 recurring core в текущем рабочем дереве уже не просто «работает», а имеет:
- единый контракт статусов и результатов;
- читаемый jobs UX;
- recurring chat rendering;
- базовую stuck/recovery semantics;
- подтверждённую локальную сборку и targeted smoke coverage.
