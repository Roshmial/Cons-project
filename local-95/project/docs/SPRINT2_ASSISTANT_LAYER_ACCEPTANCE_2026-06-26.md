# Sprint 2 — Assistant Layer Acceptance

Дата: 2026-06-26
Статус: обновлено после Sprint 2 leftovers pass

## Что считается закрытым

### 1. Backend assistant result contract
Подтверждено, что backend сериализует и различает user-facing assistant result kinds:
- `chat_answer`
- `clarification_needed`
- `file_result`
- `artifact_result`
- `structured_result`
- `research_result`
- `table_result`
- `job_result`
- `status_update`

Для assistant messages сериализуются:
- `assistant_result_kind`
- `output_mode`
- `next_actions`
- `display_text` как безопасный user-facing текст

### 2. Frontend assistant rendering
Подтверждено, что frontend имеет отдельные rendering branches / cards для:
- clarification
- file/artifact result
- structured result
- research result
- table result

UI не обязан трактовать все assistant outputs как обычный markdown bubble.

### 3. Action semantics
`next_actions` остаётся главным продуктовым источником affordances для:
- export
- save-as-job
- open artifact
- clarify request

### 4. Acceptance checks
Минимальный acceptance для Sprint 2:
- backend compile
- targeted backend smoke на assistant result semantics
- frontend build
- визуальная / live проверка, когда в runtime есть соответствующий payload

## Команды проверки

### Backend compile
`python3 -m py_compile services/backend/app.py services/backend/test_smoke.py`

### Targeted backend smoke
`python3 -m unittest services.backend.test_smoke.HermesWebBackendSmokeTest.test_serialize_message_exposes_assistant_result_contract`

### Frontend build
`npm run react:build`

## Что подтверждено в этом проходе
- `python3 -m py_compile ...` -> OK
- `python3 -m unittest ...test_serialize_message_exposes_assistant_result_contract` -> OK
- `npm run react:build` -> OK

## Что именно добавлено этим проходом
- backend mapping для `research_result`
- backend mapping для `table_result`
- frontend cards для `research_result`
- frontend cards для `table_result`
- acceptance doc для Sprint 2

## Что пока не считается частью этого прохода
- отдельный live business scenario, который генерирует `research_result` не через synthetic/test payload, а через полноценный user flow
- richer domain-specific cards beyond current lightweight result cards
- новый orchestration/workflow layer

## Интерпретация статуса
После этого прохода Sprint 2 assistant layer закрыт как product contract / renderer / acceptance baseline.
Если следующим шагом потребуется дальнейшее усиление, это уже не базовый contract Sprint 2, а product polish или прикладные сценарии поверх него.
