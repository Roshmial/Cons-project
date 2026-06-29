# Sprint 3 — File Contour Implementation Backlog

> Для Hermes: это implementation backlog следующего шага после Sprint 2 assistant layer. Задача Sprint 3 — не добавлять «ещё файловые фичи», а довести file contour до отдельного, читаемого и прикладного продуктового слоя.

**Goal:** сделать file contour first-class рабочим контуром: пользователь должен понимать, какой файл был загружен, что из него удалось извлечь, был ли он реально использован в ответе, что было сгенерировано как результат и что можно переиспользовать дальше.

**Architecture:** опираемся на уже существующий local-first контур внутри `services/backend/app.py`, `services/frontend-react/src/App.jsx`, `services/frontend-react/src/styles.css` и текущий `user_files` / message-meta / download-preview paths. Новую инфраструктуру не добавляем. Главный принцип Sprint 3: input files, reused profile files и generated files должны быть разделены семантически и визуально, а file lifecycle должен быть прозрачен.

**Tech Stack:** Flask backend, DuckDB/Postgres compatibility layer, React/Vite frontend, unittest smoke suite, local Hermes runtime.

---

## 1. Что точно входит в Sprint 3

### Product scope
- файл должен стать понятной рабочей сущностью, а не только attachment у сообщения;
- пользователь должен видеть:
  - файл загружен;
  - текст извлечён / не извлечён;
  - preview доступен;
  - файл был использован в конкретном ответе или нет;
  - файл сохранён для повторного использования;
  - файл был сгенерирован системой как результат;
- generated files и input files не должны смешиваться в голове пользователя;
- reuse должен быть понятен и в чате, и в профиле;
- file contour должен быть пригоден для document-heavy сценариев: ТЗ, КП, разбор документов, табличные файлы.

### In scope
- file lifecycle semantics в backend и frontend;
- прозрачность extraction / preview / reuse / used-in-response;
- явное разделение attachment / export / artifact / generated file result;
- deliverable path для generated files;
- acceptance по форматам: `txt`, `csv`, `pdf-text`, `docx`, `xlsx`.

### Out of scope
- полноценный OCR/vision-first document pipeline;
- новая отдельная file-service архитектура;
- сложный workflow layer поверх файлов;
- глубокие интеграции с внешними DMS / cloud storage;
- dashboard-first визуализация file contour.

---

## 2. Фактическая база, от которой идём

### Уже есть после Sprint 2
- `services/backend/app.py`
  - таблица `user_files`;
  - extraction helpers для `txt` / `pdf` / `docx` / `xlsx` / `pptx`;
  - file upload / reuse / download paths;
  - message export path;
  - message/file meta semantics.
- `services/frontend-react/src/App.jsx`
  - composer attachments;
  - existing files picker;
  - file preview modal;
  - artifact/file-aware rendering после Sprint 2.
- `services/frontend-react/src/styles.css`
  - стили для files popover / profile files / preview modal.
- `services/backend/test_smoke.py`
  - smoke на export/file response flows;
  - базовые regression tests по attachment/export semantics.

### Главные текущие рабочие точки в коде
- backend schema / upload / extraction / serialization: `services/backend/app.py`
- frontend chat/profile file surface: `services/frontend-react/src/App.jsx`
- frontend visual states: `services/frontend-react/src/styles.css`
- tests: `services/backend/test_smoke.py`

---

## 3. Критерии Done для Sprint 3

Sprint 3 можно считать закрытым, если подтверждено:

1. Для input file и generated file есть разные user-facing semantics.
- input file;
- reused file;
- generated result file;
- export of previous answer.

2. Для каждого файла UI понимает и показывает:
- origin/source;
- extraction status;
- preview availability;
- used_in_response / exported_from_message / generated_by_system semantics;
- возможное следующее действие: открыть, скачать, переиспользовать.

3. В чате видно, какие файлы реально участвовали в ответе, а не просто были когда-то прикреплены.

4. В profile/files или смежной file surface видно различие между:
- просто сохранённый файл;
- файл с извлечённым текстом;
- файл, использованный в ответах;
- сгенерированный системой deliverable.
- файлы текущего диалога доступны отдельно от личных profile files.

5. Есть acceptance:
- `py_compile`;
- `react:build`;
- targeted smoke на file lifecycle / export / reuse / generated result semantics;
- локальная runtime-проверка хотя бы по одному document-heavy сценарию.

6. Для каждого спринта по UI обязательны два rails:
- `UI stabilization with world practices`: cleanup product surface после функциональных изменений, удаление служебных тегов/contract-noise, проверка против типовых паттернов современных chat/file UX;
- `UI-driven testing`: обязательная проверка пользовательского маршрута из интерфейса, а не только backend/unit/build.

---

## 4. Implementation backlog

## Workstream A — backend file lifecycle contract

### A1. Ввести явный file surface contract в serializer/meta

**Objective:** перестать полагаться только на разрозненные `attachments` и ad hoc meta-поля.

**Files:**
- Modify: `services/backend/app.py`
- Test: `services/backend/test_smoke.py`

**Что сделать:**
- определить lightweight file contract для message/file payload:
  - `file_kind`;
  - `file_origin`;
  - `extraction_status`;
  - `preview_status`;
  - `used_in_response`;
  - `generated_from` / `exported_from_message_id` при наличии;
  - `next_actions`.
- использовать существующий meta/serializer path без нового сервиса;
- сохранить обратную совместимость со старыми rows/messages.

**Verification:**
- targeted serializer tests для input file / reused file / generated file / exported answer file.

### A2. Нормализовать lifecycle states для `user_files`

**Objective:** file contour должен различать не просто наличие файла, а его рабочее состояние.

**Files:**
- Modify: `services/backend/app.py`
- Optional schema touch: `services/backend/app.py` migrations block
- Test: `services/backend/test_smoke.py`

**Что сделать:**
- ввести или вычислять user-facing состояния:
  - `uploaded`;
  - `recognized`;
  - `not_recognized`;
  - `used_in_answer`;
  - `saved_for_reuse`;
  - `generated_result`.
- не тащить тяжёлую domain-model без необходимости: где возможно, вычислять состояние из уже имеющихся полей и message meta.

**Verification:**
- tests на state derivation для `txt`, `docx`, `xlsx`, `pdf-text`.

### A3. Сделать явную связь «какие файлы реально использованы в ответе»

**Objective:** убрать неопределённость между «файл был прикреплён» и «файл реально участвовал в ответе».

**Files:**
- Modify: `services/backend/app.py`
- Test: `services/backend/test_smoke.py`

**Что сделать:**
- в assistant message meta или serialized surface отдавать список `used_file_ids` / `used_files`;
- для generated/export flows отдавать `source_message_id` и/или `source_file_ids` там, где это уместно;
- не пытаться решать provenance идеально — только продуктово полезный минимальный contract.

**Verification:**
- regression tests на chat-task с upload/reuse/export flows.

---

## Workstream B — extraction / preview transparency

### B1. Довести extraction status и user-facing explanation

**Objective:** пользователь должен понимать, что именно система извлекла или почему не извлекла текст.

**Files:**
- Modify: `services/backend/app.py`
- Modify: `services/frontend-react/src/App.jsx`
- Test: `services/backend/test_smoke.py`

**Что сделать:**
- нормализовать user-facing explanation из `text_extracted`, `extraction_note`, `preview_text`, `extracted_text`;
- показывать статусы вроде:
  - «текст извлечён»;
  - «извлечён частично»;
  - «текст не удалось извлечь».
- не выводить технический мусор библиотек напрямую в UI.

**Verification:**
- targeted tests + frontend build.

### B2. Улучшить preview для текстовых и табличных форматов

**Objective:** preview должен быть не просто modal, а объяснять, что система увидела внутри файла.

**Files:**
- Modify: `services/frontend-react/src/App.jsx`
- Modify: `services/frontend-react/src/styles.css`
- Optional backend touch: `services/backend/app.py`

**Что сделать:**
- для `txt` / `csv` / `docx` / `xlsx` / `pdf-text` показывать компактный preview summary;
- для таблиц показывать хотя бы shape/лист/первые строки, а не только raw dump;
- рядом с preview показывать extraction note/status.

**Verification:**
- `npm run react:build`;
- визуальная локальная проверка preview modal.

---

## Workstream C — reuse and generated deliverables

### C1. Довести reuse files picker и profile/files до продуктовой ясности

**Objective:** выбор файла из профиля должен быть понятным и полезным, а не просто списком имён.

**Files:**
- Modify: `services/frontend-react/src/App.jsx`
- Modify: `services/frontend-react/src/styles.css`
- Optional backend touch: `services/backend/app.py`

**Что сделать:**
- в picker/profile list показать:
  - file type;
  - extraction status;
  - preview summary;
  - где использовался последний раз;
  - generated/input distinction.
- сделать более понятным сценарий «выбрать уже сохранённый файл для новой задачи».

**Verification:**
- frontend build + визуальная smoke-проверка reuse path.

### C2. Развести attachment / export / artifact / generated file result

**Objective:** пользователь не должен гадать, что именно он получил: приложенный input, экспорт ответа или новый сгенерированный deliverable.

**Files:**
- Modify: `services/backend/app.py`
- Modify: `services/frontend-react/src/App.jsx`
- Test: `services/backend/test_smoke.py`

**Что сделать:**
- нормализовать user-facing labels и action strip для:
  - input attachment;
  - reused file;
  - exported previous answer;
  - generated artifact/result file.
- привести generated files к понятному deliverable path и consistent naming.

**Verification:**
- targeted smoke + frontend build.

### C3. Довести минимальный business-path acceptance

**Objective:** Sprint 3 должен завершаться не только unit/smoke логикой, но и рабочим прикладным сценарием.

**Files:**
- Modify as needed: `services/backend/app.py`
- Modify as needed: `services/frontend-react/src/App.jsx`
- Test: `services/backend/test_smoke.py`
- Optional script touch: `scripts/ui_acceptance_smoke.mjs`

**Что сделать:**
- выбрать 1–2 сценария:
  - загрузка `docx`/`pdf` и ответ по содержимому;
  - reuse сохранённого файла;
  - генерация итогового файла как deliverable.
- убедиться, что path читается как цельный пользовательский маршрут.

**Verification:**
- `python3 -m py_compile services/backend/app.py services/backend/test_smoke.py`
- `npm run react:build`
- targeted unittest/smoke
- локальная live-проверка выбранного сценария.

---

## 5. Предлагаемый порядок выполнения

### P0 — first useful slice
1. A1 — file surface contract
2. A3 — used-files provenance
3. C2 — attachment/export/artifact/generated distinction
4. targeted backend smoke

### P1 — readability slice
5. B1 — extraction status explanation
6. B2 — preview improvement
7. frontend build + visual check

### P2 — reuse/productization slice
8. C1 — clearer reuse picker/profile files
9. C3 — business-path acceptance
10. UI stabilization with world practices
11. UI-driven testing from the real interface

---

## 6. Сквозные продуктовые rails для каждого следующего спринта

Эти две задачи считаются обязательными для каждого спринта, где меняется пользовательский интерфейс:

1. UI stabilization with world practices
- убрать служебные теги, backend contract-strip и технические статусы из default user view;
- сверять surface с типовыми паттернами современных chat/file products: компактная card, ясные primary actions, details по запросу;
- не плодить уникальные визуальные сущности без явной продуктовой пользы.

2. UI-driven testing
- проверять сценарий из интерфейса, а не только serializer/unit/build;
- минимально проходить путь пользователя end-to-end: открыть чат, прикрепить/открыть файл, получить результат, открыть deliverable, проверить доступность файлов диалога;
- регрессии фиксировать в smoke/acceptance scripts.

---

## 7. Что реально меняет ситуацию, а что нет

### Реально меняет
- явное различие input/reuse/generated/export;
- видимость used files в конкретном ответе;
- extraction status и preview как понятные user-facing состояния;
- generated deliverable path как отдельный результат.

### Создаёт видимость движения, но не решает core problem
- только косметическая полировка modal без lifecycle semantics;
- добавление новых иконок/бейджей без backend contract;
- новый file screen без понятного reuse/provenance;
- преждевременный OCR/workflow layer до стабилизации базового file contour.

---

## 7. Recommended next step

Начать с P0 slice: `A1 + A3 + C2`.

Это минимальный, но уже продуктово значимый инкремент:
- станет ясно, что именно за файл перед пользователем;
- станет видно, был ли он использован в ответе;
- generated/export/input paths перестанут смешиваться.
