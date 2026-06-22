# Universal data collection and composition algorithm

Дата: 2026-06-19
Контур: Hermes Web backend `services/backend/app.py`

## Цель

Единый исполнимый алгоритм для запросов класса:
- выгрузи данные из источника;
- обработай данные;
- собери файл по результатам;
- при необходимости предложи аналоги;
- на базе предыдущих подач помоги собрать КП, проект КП, оценку стоимости и требуемых ресурсов по ТЗ или запросу.

Алгоритм должен работать единообразно для:
- одного файла;
- нескольких файлов;
- web-источников;
- API;
- смешанного набора источников.

## Базовый принцип

Не делать отдельный «умный режим» под каждый частный кейс.
Нужен один общий pipeline:

1. intake / контракт запроса
2. routing к одному execution path
3. materialize source list / source config под задачу
4. ingest raw data
5. normalize into rows / entities / evidence
6. analog search and enrichment
7. scoring / estimation / composition
8. artifact generation
9. delivery + provenance

Ключевое правило: на один пользовательский запрос должен выбираться один главный путь исполнения. Внутри него допустимы подшаги и enrichment, но не параллельная конкуренция нескольких верхнеуровневых маршрутов.

## Единый контракт запроса

Каждый data-request должен приводиться к одному объекту `collection_contract`:

```json
{
  "intent_kind": "data_collection",
  "source_kind": "attachment|attachments|api|web|telegram|tenders|mixed",
  "source_items": [],
  "subject": "что ищем / что формируем",
  "task_goal": "dataset|kp_draft|cost_estimate|resource_estimate|comparison|summary",
  "output_format": "csv|xlsx|json|docx|md|pdf",
  "fields": [],
  "since_date": "YYYY-MM-DD",
  "constraints": {
    "must_use_analogs": true,
    "allow_partial_matches": true,
    "use_previous_submissions": true
  }
}
```

## Source classes

### 1. Attachment / attachments

Вход:
- один файл пользователя;
- несколько файлов пользователя;
- архив;
- ТЗ, RFP, старые КП, выгрузки, таблицы.

Обработка:
- сохранить file records;
- извлечь текст / таблицы / метаданные;
- определить тип документа: ТЗ, КП, коммерческая подача, смета, staffing-plan, сравнение, договорный шаблон, переписка;
- разбить на сущности:
  - требования;
  - позиции работ;
  - роли;
  - сроки;
  - цены;
  - допущения;
  - ограничения;
  - признаки домена/отрасли.

### 2. API

Вход:
- base URL / connector;
- endpoint list;
- auth через уже существующий локальный session/env contour;
- параметры периода и фильтров.

Обработка:
- materialize task-specific API config;
- сделать выгрузку сырых данных;
- сохранить raw response и task source manifest;
- привести payload к tabular/entity слою.

### 3. Web / media / generic internet search

Вход:
- явные URL;
- или неявный запрос «собери из интернета / СМИ / открытых источников».

Обработка:
- если URL заданы явно: fetch этих URL;
- если URL не заданы: сначала `search stage`, потом task-specific source list;
- сохранить source manifest с query, найденными URL, rank, title, snippet;
- затем fetch top-N результатов и структурирование.

### 4. Telegram / tenders / special connectors

Это не отдельная логика принятия решения, а частные executors внутри общего pipeline:
- Telegram: task-specific channel list + API export;
- tenders: task-specific source list + active/placeholder coverage;
- дальше тот же normalize / analog / artifact flow.

## Unified execution pipeline

### Stage A. Intake and routing

1. Выделить intent:
- data collection;
- dashboard;
- export previous message;
- recurring job;
- generic chat.

2. Если intent = data collection, дальше не запускать dashboard/job/export route.

3. Для data collection выделить:
- source_kind;
- task_goal;
- output_format;
- fields;
- subject;
- наличие явных источников.

### Stage B. Source materialization

На каждый запрос создаётся отдельный task-specific source artifact:
- `task_source_list` для URL / web search;
- `task_channel_list` для Telegram;
- `task_api_config` для API;
- `task_attachment_bundle` для пользовательских файлов;
- `task_tender_sources` для тендеров.

Это критично, чтобы запрос «не жил в вакууме».

### Stage C. Raw ingest

Собираем raw layer:
- файлы → extracted text / tables / metadata;
- API → raw JSON / CSV / pages;
- web → fetched HTML/text snapshots;
- Telegram → экспорт сообщений;
- mixed → единый ingest manifest.

### Stage D. Normalization

Все источники приводятся к общему набору сущностей:
- `documents`
- `rows`
- `requirements`
- `cost_items`
- `roles`
- `time_estimates`
- `evidence`
- `analogs`

Минимальное правило: каждую нормализованную строку можно трассировать к исходному источнику.

Пример полей provenance:
- `source_type`
- `source_id`
- `source_url`
- `document_id`
- `excerpt`
- `confidence`

### Stage E. Analog search

Для КП и оценки ресурсов прямые совпадения редки, поэтому analog stage обязателен.

Алгоритм:
1. Извлечь профиль запроса:
- отрасль;
- тип работ;
- размер проекта;
- обязательные интеграции;
- уровень зрелости заказчика;
- чувствительность к срокам/стоимости.

2. Найти аналоги в локальном prior corpus:
- предыдущие КП;
- прошлые сметы;
- похожие ТЗ;
- выигранные/проигранные подачи;
- оценённые staffing-модели.

3. Если прямых аналогов нет — искать частичные аналоги по компонентам:
- тот же домен;
- та же архитектурная сложность;
- тот же тип команды;
- тот же класс интеграций;
- тот же диапазон бюджета.

4. Для каждого аналога сохранять:
- тип совпадения: `direct|partial|component|market_proxy`;
- основания совпадения;
- коэффициент применимости;
- что перенесено напрямую, а что только как ориентир.

### Stage F. Estimation and composition

Для `task_goal in {kp_draft, cost_estimate, resource_estimate}` pipeline делает:

1. Requirement mapping
- требования из ТЗ;
- обязательные deliverables;
- неясности и допущения.

2. Work breakdown
- этапы;
- work packages;
- артефакты;
- зависимости.

3. Resource model
- роли;
- seniority;
- загрузка;
- duration;
- критические компетенции.

4. Cost model
- base effort;
- коэффициенты сложности;
- коэффициенты риска;
- стоимость ролей;
- резерв;
- диапазон min/base/max.

5. Analog-backed justification
- какие цифры взяты из прямых аналогов;
- какие из частичных;
- где экспертная оценка, а не подтверждённый исторический факт.

### Stage G. Artifact generation

Выход зависит от цели:

- dataset → `csv/json/xlsx`
- short comparison → `md/docx`
- проект КП → `md/docx/pdf`
- оценка стоимости → `xlsx + md summary`
- staffing / resource estimate → `xlsx/json + md summary`

Для КП минимум два слоя результата:
1. machine-readable artifact
- таблица позиций, ролей, сроков, стоимости, аналогов

2. human-readable artifact
- проект КП / пояснительная записка / summary assumptions

### Stage H. Delivery

В assistant message должны возвращаться:
- итоговый статус;
- attachments;
- `collection_contract`;
- `task_source_list` / `task_api_config` / `task_attachment_bundle`;
- preview rows / preview estimates;
- provenance summary;
- ограничения и неуверенности.

## Route selection contract

Для согласованности верхний routing должен быть взаимоисключающим.

Приоритет:
1. `collection_execution_reply`
2. `collection_contract / clarification`
3. `message_export`
4. `dashboard`
5. `recurring_job`
6. `generic chat`

Что это значит:
- если запрос распознан как data collection, backend не должен параллельно пытаться строить dashboard;
- не должен одновременно создавать recurring job;
- не должен обрабатывать это как обычный chat reply;
- экспорт предыдущего ответа не должен перехватывать реальный collection request.

## Verified current backend state

По состоянию текущего кода подтверждено:
- `process_chat_task()` уже использует взаимоисключающий порядок route-веток;
- collection path имеет приоритет над dashboard и recurring job;
- explicit web URLs уже доводятся до реального artifact-файла;
- generic web query без явных URL больше не обязана требовать `список URL / сайтов` на уровне контракта.

## Current gaps against target algorithm

Ниже не «философия», а реальные недоделки до полного universal pipeline:

1. Attachment collection execution
- attachment-source уже известен системе,
- но полноценный collection executor для одного/нескольких файлов как отдельный downstream ещё нужно довести.

2. API collection execution
- нужен единый `api` source_kind и task-specific API config manifest;
- сейчас есть connector/policy contour, но не единый collection executor для arbitrary API.

3. Analog corpus
- нужен выделенный local corpus прошлых КП/смет/подач с нормализованными признаками;
- без этого analog stage будет частично эвристическим.

4. Cost/resource estimation layer
- нужна отдельная схема нормализации `roles / effort / rates / assumptions / uncertainty bands`.

5. Dual artifact generation for proposal work
- кроме dataset-файла нужен ещё человекочитаемый проект КП / explanation artifact.

## Minimal implementation sequence

### Phase 1
- generic web search executor;
- task-specific source manifest for search queries;
- fetch + normalize + structured artifact.

### Phase 2
- attachment bundle executor;
- extracted requirements / prior proposals parser;
- normalized analog candidates from local files.

### Phase 3
- API executor with local auth/session handoff;
- source manifest + raw response cache.

### Phase 4
- analog scoring engine;
- cost/resource estimation layer;
- proposal draft composer.

### Phase 5
- recurring operationalization:
  - Hermes schedule as control plane;
  - n8n execution only where user explicitly moves workflow there;
  - after move, Hermes version remains only dev/test and inactive.

## Acceptance criteria

Считать алгоритм внедрённым только если для каждого supported source class подтверждено:
1. request -> one selected route
2. source manifest materialized
3. raw ingest completed
4. normalized rows/entities available
5. analog stage either executed or honestly reported unavailable
6. artifact file generated
7. assistant message contains provenance and constraints

## Routing anti-patterns to forbid

- один запрос одновременно становится collection и dashboard;
- collection request превращается в recurring job без отдельного пользовательского intent;
- explicit source request игнорируется и заменяется generic answer;
- backend говорит «делаю», но не создаёт source manifest или artifact;
- аналогии подаются как точные совпадения;
- оценка стоимости выдаётся без separation на факт / аналог / гипотезу.
