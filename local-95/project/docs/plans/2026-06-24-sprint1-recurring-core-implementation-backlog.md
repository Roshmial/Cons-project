# Sprint 1 — Recurring Core Implementation Backlog

> Для Hermes: это implementation backlog следующего шага после Sprint 0 baseline. Задача Sprint 1 — не расширять продукт во все стороны, а довести recurring / jobs / monitoring до first-class рабочего ядра.

**Goal:** сделать recurring / cron / monitoring контур устойчивым, читаемым и операционно понятным на уровне backend, frontend и live-проверки.

**Architecture:** опираемся на уже внедрённый Sprint 0 semantic baseline и усиливаем именно существующий local-first контур: `jobs`, `job_runs`, `job_subscriptions`, jobs UI и recurring delivery path. Новую инфраструктуру не добавляем; работаем внутри текущих `services/backend/app.py`, `services/frontend-react/src/App.jsx` и существующего smoke-контура.

**Tech Stack:** Flask backend, DuckDB, React/Vite frontend, unittest smoke suite, local Hermes runtime.

---

## 1. Что точно входит в Sprint 1

### Product scope
- jobs должны выглядеть как first-class функция, а не как скрытый cron-хвост;
- по каждому run пользователь должен понимать:
  - что произошло;
  - был ли результат;
  - была ли ошибка;
  - был ли empty result;
  - был ли partial / degraded result;
  - кому ушла доставка;
- monitoring output должен читаться единообразно;
- recurring failure cases должны быть хотя бы базово операционно видимы.

### In scope
- jobs list / detail / run history;
- run/result semantics и причины ошибок;
- delivery/subscription clarity;
- базовый stuck/pending control;
- cleanup красных recurring-related smoke там, где они мешают Sprint 1 acceptance.

### Out of scope
- полноценный workflow layer;
- полноценная artifact domain-model;
- assistant layer beyond recurring-specific follow-ups;
- file contour beyond recurring outputs;
- новый orchestration stack или отдельные сервисы.

---

## 2. Фактическая база, от которой идём

### Уже есть после Sprint 0
- `services/backend/app.py`
  - `classify_job_run_surface(...)`
  - `serialize_job_run_row(...)`
  - `derive_message_surface(...)`
  - `last_run_public_status` в job serializer
- `services/frontend-react/src/App.jsx`
  - public status для jobs/runs
  - surface labels в chat messages
  - улучшенный jobs list/detail/run history
- `services/backend/test_smoke.py`
  - smoke на job run public surface
  - smoke на message surface

### Главные текущие рабочие точки в коде
- backend schema / jobs tables: `services/backend/app.py`
- chat task queue: `claim_pending_chat_tasks(...)`, `build_pending_assistant_meta(...)`
- jobs UI: `JobsScreen`, `JobDraftModal`, `JobMembersModal` в `services/frontend-react/src/App.jsx`
- tests: `services/backend/test_smoke.py`

---

## 3. Критерии Done для Sprint 1

Sprint 1 можно считать закрытым, если подтверждено:

1. В jobs UI видно различие между:
- completed;
- completed_with_limitations;
- failed;
- empty_result;
- running.

2. Для последнего запуска и run history есть:
- краткий итог;
- причина ошибки или ограничений;
- delivered_count / delivery target visibility;
- timestamp started/finished.

3. Monitoring/digest outputs читаются единообразно:
- summary;
- статус;
- есть ли результат;
- есть ли ограничения.

4. Есть базовый контроль зависших состояний:
- pending/running cases не висят без объяснения бесконечно;
- есть хотя бы recovery или явная маркировка stuck-like cases.

5. Sprint 1 acceptance подтверждён:
- `py_compile`;
- `react:build`;
- целевые smoke-тесты на recurring core;
- live mock-runtime smoke по jobs flow.

---

## 4. Implementation backlog

## Workstream A — backend semantics и run/result contract

### A1. Ввести отдельную классификацию degraded / empty / failed / completed для recurring runs

**Objective:** перестать полагаться только на raw `success/error` и вывести recurring-friendly public contract.

**Files:**
- Modify: `services/backend/app.py`
- Test: `services/backend/test_smoke.py`

**Что сделать:**
- расширить `classify_job_run_surface(...)`, чтобы она различала:
  - `completed`
  - `completed_with_limitations`
  - `failed`
  - `empty_result`
  - `running`
- добавить более явные правила:
  - `error_text` => `failed`
  - пустой `result_text` при успешном run => `empty_result`
  - частичный/ограниченный результат => `completed_with_limitations`
- если нужна минимальная эвристика для degraded, использовать явные маркеры в `summary`/`result_text` или специальный флаг из producer path, без нового сервиса и без тяжёлой схемы.

**Verification:**
- добавить targeted tests в `services/backend/test_smoke.py`;
- прогнать только эти тесты до полного `PASS`.

### A2. Расширить `serialize_job_run_row(...)` причинами и user-facing полями

**Objective:** чтобы frontend не угадывал, почему run считается failed/degraded/empty.

**Files:**
- Modify: `services/backend/app.py`
- Test: `services/backend/test_smoke.py`

**Что сделать:**
- добавить в serialized run:
  - `status_reason`
  - `status_detail`
  - `delivery_summary`
  - `finished_at`
  - `duration_ms`
- `delivery_summary` делать из `delivered_to_json` и/или recipients data;
- `status_reason` должен быть коротким и годным для UI.

**Verification:**
- test на failed run;
- test на empty_result;
- test на degraded/partial result.

### A3. Стабилизировать логику последнего запуска на уровне job serializer

**Objective:** jobs list/detail должны показывать консистентный last run state.

**Files:**
- Modify: `services/backend/app.py`
- Test: `services/backend/test_smoke.py`

**Что сделать:**
- убедиться, что `row_to_job_dict(...)` отдаёт:
  - `last_run_public_status`
  - `last_run_summary`
  - `last_run_finished_at`
  - `last_run_delivery_summary`
- не смешивать старые поля с новыми semantically conflicting shortcuts.

**Verification:**
- targeted serialization test для job payload.

---

## Workstream B — jobs UX / frontend surface

### B1. Довести hero/detail block для active job

**Objective:** в карточке задачи пользователь сразу видит operational truth.

**Files:**
- Modify: `services/frontend-react/src/App.jsx`
- Optional CSS touch: `services/frontend-react/src/styles.css`

**Что сделать:**
- в hero/detail блоке показать:
  - public status;
  - итог последнего run;
  - started/finished timestamps;
  - summary;
  - delivery summary;
  - явную причину ошибки/ограничений.
- отдельной строкой показать difference между:
  - «не сработала»
  - «отработала, но сигнала нет».

**Verification:**
- `npm run react:build`
- визуальная проверка через mock-runtime jobs screen.

### B2. Довести `История запусков` до реально читаемого operational log

**Objective:** run history должна стать не архивом статусов, а рабочим экраном диагностики.

**Files:**
- Modify: `services/frontend-react/src/App.jsx`

**Что сделать:**
- в каждой записи run history показать:
  - public status;
  - result kind;
  - started/finished;
  - duration;
  - status reason;
  - delivery summary;
- длинные тексты summary/detail скрывать под `details` или компактным expandable pattern.

**Verification:**
- build + live mock smoke.

### B3. Сделать subscriptions и recipients понятными из одного экрана

**Objective:** убрать двусмысленность между «кому уходит результат» и «кто подписан». 

**Files:**
- Modify: `services/frontend-react/src/App.jsx`
- Modify: `services/backend/app.py` при необходимости сериализации

**Что сделать:**
- развести в UI:
  - recipients (маршрут доставки задачи);
  - subscriptions (личное получение/подписка пользователя);
- если backend сейчас отдаёт это недостаточно явно, добавить отдельные payload fields без ломки текущего API.

**Verification:**
- smoke на subscribe/unsubscribe path;
- live job detail check.

---

## Workstream C — monitoring output contract

### C1. Ввести recurring output summary envelope

**Objective:** digest / audit / triage / recurring review должны читаться одинаково хотя бы на уровне summary layer.

**Files:**
- Modify: `services/backend/app.py`
- Test: `services/backend/test_smoke.py`

**Что сделать:**
- определить минимальный recurring summary contract:
  - `headline`
  - `summary`
  - `result_kind`
  - `public_status`
  - `status_reason`
  - `has_artifact`
- не строить новый universal schema-движок; просто ввести единый envelope для recurring outputs, где это уже контролируется backend.

**Verification:**
- targeted tests на 2-3 recurring shapes;
- readback payload inspection.

### C2. Привести recurring delivery messages к одному message-kind family

**Objective:** delivery messages в chat/thread не должны выглядеть каждый раз как другой продукт.

**Files:**
- Modify: `services/backend/app.py`
- Test: `services/backend/test_smoke.py`

**Что сделать:**
- выровнять `message_kind` и `surface.label` для recurring delivery:
  - job delivery
  - monitoring result
  - empty monitoring result
  - degraded recurring result
- это нужно не для красоты, а чтобы threads/jobs/recurring UX потом не расползались.

**Verification:**
- targeted message serialization tests.

---

## Workstream D — operational stability

### D1. Разобрать красные recurring-related smoke и отделить их от нерелевантного шума

**Objective:** Sprint 1 должен опираться на честную тестовую картину, а не на «пол-suite красный где-то рядом».

**Files:**
- Modify: `services/backend/test_smoke.py`
- Modify: `services/backend/app.py` по мере исправления
- Optional docs: `docs/TESTING_SCENARIO.md`

**Что сделать:**
- отдельно выписать failing tests, относящиеся именно к recurring/chat task queue:
  - pending/running queue;
  - recurring execution;
  - CSV/delivery outputs, если они реально recurring-related;
- не расползаться на весь backend suite;
- починить first-order failures, которые мешают Sprint 1 acceptance.

**Verification:**
- отдельная команда запуска целевого recurring subset.

### D2. Добавить базовый stuck/running recovery policy

**Objective:** висящие chat/recurring tasks не должны навсегда оставаться в ambiguous running.

**Files:**
- Modify: `services/backend/app.py`
- Test: `services/backend/test_smoke.py`

**Что сделать:**
- использовать уже существующие recovery touchpoints вокруг `chat_tasks` и scheduler loop;
- добавить явное правило:
  - когда running/pending считается зависшим;
  - что делаем: reset to pending / mark failed / annotate recovered;
- не добавлять новый daemon — встроить в текущий lifecycle.

**Verification:**
- smoke на recovered-after-restart / stuck recovery.

---

## Workstream E — acceptance и live verification

### E1. Собрать отдельный Sprint 1 verification checklist

**Objective:** чтобы recurring core можно было принимать не по ощущениям.

**Files:**
- Create: `docs/SPRINT1_ACCEPTANCE_CHECKLIST_DRAFT.md`
- Optional update: `docs/TESTING_SCENARIO.md`

**Что сделать:**
- сценарии:
  1. создать задачу;
  2. запустить вручную;
  3. увидеть `running`;
  4. получить `completed`;
  5. получить `empty_result`;
  6. получить `failed`;
  7. проверить recipients/subscriptions;
  8. проверить run history;
  9. проверить recovery после restart.

### E2. Закрепить минимальный набор команд проверки

**Objective:** у Sprint 1 должна быть стандартная проверка перед финальным done.

**Runbook:**
- `python3 -m py_compile services/backend/app.py services/backend/test_smoke.py`
- `python3 -m unittest -v services/backend.test_smoke.HermesWebBackendSmokeTest.test_job_run_surface_serialization_exposes_public_status_and_result_kind`
- `python3 -m unittest -v [целевой recurring subset после Sprint 1 cleanup]`
- `npm run react:build`
- live mock-runtime smoke на jobs screen

---

## 5. Приоритеты исполнения

### P0 — без этого Sprint 1 не считается состоявшимся
1. A1
2. A2
3. A3
4. B1
5. B2
6. D1
7. E1

### P1 — очень желательно внутри того же спринта
8. B3
9. C1
10. C2
11. D2
12. E2

### P2 — только если P0/P1 уже зелёные
13. дополнительная UI-полировка jobs screen
14. вторичный cleanup copy/labels
15. расширенный ops-summary в admin/read-only представлениях

---

## 6. Рекомендуемый порядок выполнения

1. Сначала backend contract для run/result states.
2. Потом jobs detail/history UI.
3. Потом subscriptions/recipients clarity.
4. Потом monitoring output normalization.
5. Потом stuck/recovery.
6. В конце — acceptance checklist и live verification.

Это снижает риск делать UI поверх плавающего backend semantics.

---

## 7. Риски и компромиссы

### Риск 1. Слишком рано полезть в "универсальный workflow"
Это размоет Sprint 1 и сожрёт время.

**Правильный компромисс:** Sprint 1 делает recurring ядро понятным; workflow layer остаётся следующей темой.

### Риск 2. Попытка сразу «озеленить весь backend suite»
Это создаст видимость движения, но может не сдвинуть recurring core.

**Правильный компромисс:** чинить сначала recurring-related failures и только их использовать как acceptance gate Sprint 1.

### Риск 3. Слишком богатая новая schema для outputs
Можно утонуть в инфраструктуре вместо практического улучшения UX.

**Правильный компромисс:** минимальный envelope поверх уже существующих payloads.

---

## 8. Короткий итог

Sprint 1 — это не «добавить ещё cron-фич». 

Это спринт, в котором recurring core должен стать:
- понятным для пользователя;
- операционно читаемым;
- приемлемым для live support;
- достаточно стабильным, чтобы его можно было показывать как главный продуктовый контур Hermes.
