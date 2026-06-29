# Sprint 0 Implementation Baseline — Hermes Web MVP

Дата: 2026-06-24
Статус: implemented baseline
Назначение: зафиксировать, что именно было реально внедрено в Sprint 0 поверх product draft-документов.

## Что считалось задачей Sprint 0

Sprint 0 закрывает не весь продукт, а минимальную product-semantic baseline:
- единая рамка статусов и fallback;
- различение основных продуктовых сущностей на surface-уровне;
- backend/frontend contract для jobs/runs/messages;
- минимальная regression-проверка новых semantics.

## Что реально внедрено

### 1. Backend: jobs / runs
Файл:
- `services/backend/app.py`

Добавлено:
- `classify_job_run_surface(...)`
- `serialize_job_run_row(...)`
- расширенный `fetch_job_runs(...)`
- `last_run_public_status` в `row_to_job_dict(...)`

Что это даёт:
- backend по run history теперь возвращает не только raw `status`, но и:
  - `public_status`
  - `result_kind`
  - `delivered_count`
  - `has_result_text`
  - `has_error`
- UI больше не обязан угадывать, что означает raw `success/error/running`.

### 2. Backend: message surface
Файл:
- `services/backend/app.py`

Добавлено:
- `derive_message_surface(...)`
- поле `surface` в `serialize_message(...)`

Что это даёт:
- каждое сообщение теперь может нести surface-семантику:
  - `status`
  - `entity_kind`
  - `label`
  - `message_kind`
  - флаги по attachments / dashboard artifact
- это создаёт нормальную основу для разведения:
  - обычного ответа,
  - файла,
  - артефакта,
  - уточнения,
  - статуса обработки,
  - результата задачи.

### 3. Frontend: status and entity cleanup
Файл:
- `services/frontend-react/src/App.jsx`

Добавлено / изменено:
- расширенные humanize-функции для run statuses;
- humanize для `result_kind`;
- humanize для message surface status;
- MessageBubble теперь показывает продуктовую surface-плашку;
- jobs list использует `last_run_public_status`;
- job details используют public status вместо raw internal status;
- run history показывает:
  - нормализованный статус,
  - тип результата,
  - summary,
  - число получателей.

Что это даёт:
- UI меньше смешивает internal execution state и user-visible outcome.
- На поверхности лучше видна разница между:
  - выполнено,
  - выполнено с ограничениями,
  - без результата,
  - ошибка,
  - нужно уточнение.

### 4. Regression coverage
Файл:
- `services/backend/test_smoke.py`

Добавлены smoke-тесты на:
- job run public surface serialization;
- message surface classification;
- attachment download URL path сохраняется.

## Что пока осознанно НЕ закрыто Sprint 0

Это не сделано и не должно подаваться как уже завершённое:
- полная persistence-модель для всех `result_kind` и `handoff`-состояний в БД;
- отдельная materialized сущность artifact;
- полноценный workflow/handoff layer;
- сквозной state-machine для chat/file/job/artifact transitions;
- UI-polish всех экранов под новую терминологию;
- отдельные admin screens для semantic governance.

## Где Sprint 0 теперь опирается на документы

Связанные документы:
- `PRODUCT_CORE_DEFINITION_V1.md`
- `PRODUCT_DELIVERY_SPRINT_PLAN_V1.md`
- `PRODUCT_CONTRACT_ACCEPTANCE_MATRIX_V1_DRAFT.md`
- `PRODUCT_ENTITY_GLOSSARY_V1_DRAFT.md`
- `PRODUCT_STATUS_AND_FALLBACK_RULES_V1_DRAFT.md`

## Минимальная граница Done для Sprint 0

Sprint 0 считается закрытым, если подтверждено:
- backend возвращает normalized run semantics;
- backend возвращает message surface semantics;
- frontend их реально использует в jobs/chat surface;
- smoke-тесты и сборка не сломаны;
- документы синхронизированы с внедрённой baseline.

## Короткий итог

Sprint 0 в текущем виде — это не косметика и не только docs.

Это уже реальная semantic baseline между backend, frontend и product-contract:
- jobs/runs получили user-visible статусный слой;
- chat messages получили surface-классификацию;
- UI начал показывать различие между типами результата и состояниями;
- базовые правила зафиксированы в docs и покрыты smoke-проверкой.
