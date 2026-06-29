# Sprint 2 — Assistant Layer Implementation Backlog

> Для Hermes: это implementation backlog следующего шага после Sprint 1 recurring core. Задача Sprint 2 — не расползтись в "ещё один general LLM chat", а довести assistant layer до прикладного, операционно понятного и продуктово управляемого контура.

**Goal:** сделать assistant layer устойчивым рабочим инструментом для прикладных задач: research, расчёты, таблицы, structured outputs, artifact delivery и перевод результата в следующий контур.

**Architecture:** опираемся на уже внедрённые Sprint 0/Sprint 1 semantics и усиливаем существующий local-first контур внутри `services/backend/app.py`, `services/frontend-react/src/App.jsx`, существующих policy/spec файлов и smoke-suite. Новую внешнюю инфраструктуру не добавляем. Главный принцип Sprint 2: assistant result должен быть продуктовой сущностью с явным типом результата, понятным fallback и маршрутом дальнейшего действия.

**Tech Stack:** Flask backend, DuckDB/Postgres compatibility layer, React/Vite frontend, unittest smoke suite, local Hermes runtime.

---

## 1. Что точно входит в Sprint 2

### Product scope
- assistant должен стабильно решать повседневные прикладные задачи, а не только отвечать свободным текстом;
- пользователь должен понимать, что именно он получил:
  - обычный ответ;
  - research result;
  - table result;
  - structured result;
  - artifact/file result;
  - handoff/job transition;
- assistant должен явно показывать, когда:
  - данных недостаточно;
  - нужен clarify;
  - результат частичный;
  - результат можно оформить/сохранить/передать дальше;
- чат не должен смешивать internal analysis, технические поля и пользовательский deliverable.

### In scope
- assistant result contract в backend и frontend;
- сценарии research / calculations / tables / structured outputs;
- явные output modes: chat answer / structured result / file-artifact / handoff / save-as-job;
- fallback/clarify semantics для неоднозначных задач;
- acceptance и smoke для прикладных assistant flows.

### Out of scope
- полноценный workflow layer между всеми сущностями продукта;
- полноценная artifact domain-model для всех форматов;
- новый orchestration stack;
- расширение recurring/file/dashboard контуров вне assistant-specific нужд.

---

## 2. Фактическая база, от которой идём

### Уже есть после Sprint 0 / Sprint 1
- `services/backend/app.py`
  - message surface semantics;
  - `message_kind` и часть result-specific meta;
  - message export path;
  - dashboard/file/job delivery paths;
  - recent cleanup: `display_text` для безопасного assistant rendering.
- `services/frontend-react/src/App.jsx`
  - rich markdown rendering;
  - dashboard rendering;
  - file/download handling;
  - jobs handoff hooks для dashboard/job flows.
- `services/backend/test_smoke.py`
  - smoke вокруг jobs/messages/dashboard semantics;
  - targeted regressions на delivery/display behavior.

### Главные текущие рабочие точки в коде
- backend routing / assistant processing / message serialization: `services/backend/app.py`
- frontend chat rendering and action affordances: `services/frontend-react/src/App.jsx`
- backend policies: `services/backend/policies/chat_routing_policy.json` и связанные policy/spec datasets
- tests: `services/backend/test_smoke.py`

---

## 3. Критерии Done для Sprint 2

Sprint 2 можно считать закрытым, если подтверждено:

1. Assistant result всегда имеет user-facing тип результата:
- `chat_answer`;
- `research_result`;
- `table_result`;
- `structured_result`;
- `file_result` / `artifact_result`;
- `handoff_result` / `job_transition`;
- `clarification_needed`.

2. Для каждого assistant результата UI понимает:
- что это за сущность;
- что можно сделать дальше;
- есть ли файл/таблица/структурированный блок;
- является ли результат окончательным, частичным или требующим уточнения.

3. Прикладные assistant сценарии читаются единообразно:
- research;
- calculations;
- table outputs;
- structured summaries/results.

4. Internal analysis и технический мусор не попадают в user-facing render path.

5. Есть acceptance на ключевые assistant flows:
- compile/build;
- targeted smoke on backend semantics;
- live/mock runtime smoke на chat flows.

---

## 4. Implementation backlog

## Workstream A — assistant result contract

### A1. Ввести явный `assistant_result_kind` / `output_mode` в backend message contract

**Objective:** перестать выводить тип результата эвристически только из `message_kind` и контента.

**Files:**
- Modify: `services/backend/app.py`
- Test: `services/backend/test_smoke.py`

**Что сделать:**
- определить минимальный assistant result contract:
  - `assistant_result_kind`;
  - `output_mode`;
  - `public_status`;
  - `status_reason`;
  - `display_text`;
  - `next_actions`.
- использовать существующий `meta`-контур и serializer без нового сервиса;
- сохранить обратную совместимость для старых messages.

**Verification:**
- targeted serializer tests for `chat_answer`, `structured_result`, `file_result`, `clarification_needed`.

### A2. Нормализовать mapping между `message_kind` и user-facing result kinds

**Objective:** чтобы `chat_response`, `dashboard_result`, `file_response`, `collection_contract`, `job_delivery` и прочие типы не жили как разрозненные острова.

**Files:**
- Modify: `services/backend/app.py`
- Test: `services/backend/test_smoke.py`

**Что сделать:**
- сделать единый mapping backend -> UI contract;
- развести:
  - обычный ответ;
  - оформленный structured output;
  - file/artifact result;
  - clarification contract;
  - handoff/job transition.

**Verification:**
- regression tests на serialized payload и surface/meta consistency.

### A3. Вытащить `next_actions` в сериализованный payload

**Objective:** фронт должен знать не только "что это", но и "что с этим можно делать".

**Files:**
- Modify: `services/backend/app.py`
- Test: `services/backend/test_smoke.py`

**Что сделать:**
- для assistant result добавлять список допустимых действий:
  - `reply_in_chat`;
  - `export_result`;
  - `save_as_job`;
  - `open_artifact`;
  - `clarify_request`;
  - `handoff`.
- пока держать это как lightweight contract в serializer/meta.

**Verification:**
- targeted tests на `next_actions` для разных message/result kinds.

---

## Workstream B — прикладные assistant scenarios

### B1. Довести research result как отдельный продуктовый результат

**Objective:** прикладной research должен отличаться от свободного ответа и от dashboard/file flows.

**Files:**
- Modify: `services/backend/app.py`
- Modify: `services/frontend-react/src/App.jsx`
- Test: `services/backend/test_smoke.py`

**Что сделать:**
- ввести читаемый `research_result` contract;
- показывать summary/evidence/caveats как user-facing блоки;
- не смешивать research result с clarification или dashboard fallback.

**Verification:**
- targeted smoke на research payload + frontend build.

### B2. Довести table result / calculations result

**Objective:** таблицы и расчёты должны быть first-class output, а не просто markdown внутри ответа.

**Files:**
- Modify: `services/backend/app.py`
- Modify: `services/frontend-react/src/App.jsx`
- Test: `services/backend/test_smoke.py`

**Что сделать:**
- договориться о minimal contract для table/calculation outputs:
  - summary;
  - tabular payload или table hint;
  - optional export affordance;
  - notes/caveats.
- reuse существующий markdown-table renderer, но не ограничиваться им semantic-уровнем.

**Verification:**
- targeted tests на serialization + frontend build.

### B3. Довести structured result / artifact result

**Objective:** structured outputs и generated artifacts должны читаться отдельно от обычного chat answer.

**Files:**
- Modify: `services/backend/app.py`
- Modify: `services/frontend-react/src/App.jsx`
- Test: `services/backend/test_smoke.py`

**Что сделать:**
- развести structured JSON-like result, downloadable artifact и обычный текст;
- показать в UI, что результат можно скачать/использовать дальше.

**Verification:**
- smoke на serialized structured/file result + build.

---

## Workstream C — frontend assistant UX

### C1. Ввести result header / badge / action strip для assistant messages

**Objective:** в чате сразу видно тип результата и допустимые действия.

**Files:**
- Modify: `services/frontend-react/src/App.jsx`
- Optional CSS touch: `services/frontend-react/src/styles.css`

**Что сделать:**
- показывать над/под assistant message:
  - result label;
  - public status;
  - краткий reason при ограничениях;
  - action buttons по `next_actions`.

**Verification:**
- `npm run react:build`
- визуальная проверка на mock/live контуре.

### C2. Развести rendering paths по типу результата

**Objective:** research/table/file/structured result должны рендериться не одинаково по остаточному принципу.

**Files:**
- Modify: `services/frontend-react/src/App.jsx`

**Что сделать:**
- ввести отдельные rendering branches для:
  - plain chat answer;
  - research result;
  - structured result;
  - table result;
  - artifact/file result;
  - clarification-needed.

**Verification:**
- build + targeted mock payload checks.

### C3. Привязать save-as-job / export / handoff к result contract

**Objective:** действия должны зависеть от смысла результата, а не от случайных кнопок в UI.

**Files:**
- Modify: `services/frontend-react/src/App.jsx`
- Modify: `services/backend/app.py` при необходимости

**Что сделать:**
- использовать `next_actions` как главный источник UI affordances;
- не показывать нерелевантные действия для неподходящих result types.

**Verification:**
- build + live/mock interaction checks.

---

## Workstream D — fallback / clarification / ambiguity control

### D1. Нормализовать `clarification_needed` как отдельный assistant result kind

**Objective:** отличить реальный недостаток входных данных от проваленного ответа или generic refusal.

**Files:**
- Modify: `services/backend/app.py`
- Modify: `services/frontend-react/src/App.jsx`
- Test: `services/backend/test_smoke.py`

**Что сделать:**
- ввести явный user-facing contract для clarify state;
- показывать, чего именно не хватает и какой следующий шаг допустим.

**Verification:**
- targeted tests + frontend build.

### D2. Очистить assistant delivery path от технических/analysis leakage по всему контуру

**Objective:** недавний fixed case должен стать общим guardrail, а не частным hotfix.

**Files:**
- Modify: `services/backend/app.py`
- Test: `services/backend/test_smoke.py`

**Что сделать:**
- распространить safe display contract на assistant-specific delivery paths;
- убедиться, что renderer/UI не зависят от сырого `content` как source of truth.

**Verification:**
- regressions на prep-text / technical leakage / display fallback.

---

## Workstream E — acceptance / live verification

### E1. Добавить Sprint 2 acceptance doc

**Objective:** зафиксировать критерии приёмки assistant layer так же явно, как это было сделано для Sprint 1.

**Files:**
- Create: `docs/SPRINT2_ASSISTANT_LAYER_ACCEPTANCE_2026-06-24.md`

**Что сделать:**
- собрать checklist:
  - backend compile;
  - frontend build;
  - targeted assistant smoke;
  - live/mock chat flow checks.

### E2. Добавить targeted smoke suite по assistant result semantics

**Objective:** acceptance не должна опираться только на ручную проверку.

**Files:**
- Modify: `services/backend/test_smoke.py`

**Что сделать:**
- завести tests по минимуму для:
  - result kind normalization;
  - clarification needed;
  - structured/file result payload;
  - display_text safety.

---

## 5. Рекомендуемый порядок внедрения

### P0
1. Workstream A1-A3 — assistant result contract
2. Workstream D1-D2 — fallback/clarification/display safety
3. Workstream C1-C2 — frontend result rendering base

### P1
4. Workstream B1-B3 — research/table/structured/artifact outputs
5. Workstream C3 — action wiring by result contract

### P2
6. Workstream E1-E2 — final acceptance packaging and broader smoke

---

## 6. Первый практический slice

Если идти без распыления, первым кодовым пакетом Sprint 2 должен стать:
- backend assistant result contract (`assistant_result_kind`, `output_mode`, `next_actions`, `display_text` as source of truth);
- frontend preference for contract-driven rendering instead of raw heuristics;
- regression tests for `clarification_needed`, `structured_result`, `file_result` and safe display text.

Это наименьший пакет, который реально переводит продукт из режима "просто чат с разными message_kind" в режим "assistant layer как управляемый продуктовый контур".
