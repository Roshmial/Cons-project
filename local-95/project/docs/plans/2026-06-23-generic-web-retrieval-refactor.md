# Generic Web Retrieval Refactor Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Убрать предметные special-case из web search / retrieval path и перевести pipeline на topic-agnostic, intent-aware query planning и candidate-set ranking.

**Architecture:** Вместо предметных BI-веток backend должен сначала извлекать общие сигналы запроса (subject, intent, optional facets), затем строить несколько generic query families, оценивать качество каждого candidate-set как набора, а после fetch подтверждать релевантность документов по тем же общим признакам. Никаких предметных hardcoded query и domain-specific boosts.

**Tech Stack:** Python backend в `services/backend/app.py`, smoke/regression tests в `services/backend/test_smoke.py`, docs plan в `docs/plans/`.

---

### Task 1: Зафиксировать текущие special-case и целевую форму pipeline

**Objective:** Явно перечислить, что считается предметным хардкодом и что заменяем на generic planner.

**Files:**
- Modify: `docs/plans/2026-06-23-generic-web-retrieval-refactor.md`

**Step 1: Inventory**
- Текущие special-case точки: `COLLECTION_SUBJECT_ACRONYM_EXPANSIONS`, `build_collection_relevance_terms(...)`, `build_web_search_queries(...)`, `historical_markers`, BI-focused query branch.
- Целевая форма: `parse_collection_search_request -> build_query_families -> score_query_result_set -> select_relevant_web_documents`.

**Step 2: Verification**
- Проверить, что планом явно запрещены ветки вида `if BI ...` и любые query, содержащие предметно-зашитые токены конкретной темы.

### Task 2: Написать failing tests для generic query planner

**Objective:** Зафиксировать ожидаемое поведение planner до рефакторинга.

**Files:**
- Modify: `services/backend/test_smoke.py`

**Step 1: Add tests**
- Проверка, что `build_web_search_queries(...)` больше не генерирует BI-specific query.
- Проверка, что history-intent для разных тем (`BI`, `машины`, `LegalAI`) строит generic history/overview queries без предметного словаря.
- Проверка, что planner сохраняет topic terms, но не зашивает чужие доменные токены.

**Step 2: Run test to verify failure**
Run: `python3 -m pytest services/backend/test_smoke.py -q -k 'generic_query_planner or result_set_ranking'`
Expected: FAIL на старой реализации.

### Task 3: Ввести generic request parser и query families

**Objective:** Заменить предметные ветки общим planner-слоем.

**Files:**
- Modify: `services/backend/app.py`
- Test: `services/backend/test_smoke.py`

**Step 1: Add parser helpers**
- `extract_collection_search_subject(...)`
- `infer_collection_search_intent(...)`
- `build_collection_search_profile(...)`

**Step 2: Add generic planner**
- `build_generic_search_queries(profile)`
- Query families: canonical, overview, history, comparison, reference/practical — только по intent, не по теме.

**Step 3: Remove subject-specific branch**
- Убрать BI-focused `history evolution OLAP DSS ...` query и предметные `historical_markers` ветки из planner-логики.

### Task 4: Ввести scoring candidate-set как набора, а не только отдельных URL

**Objective:** Выбирать лучший query result set по общим критериям качества, а не по первому непустому ответу и не по одному лучшему URL.

**Files:**
- Modify: `services/backend/app.py`
- Test: `services/backend/test_smoke.py`

**Step 1: Add helpers**
- `score_web_candidate_set(contract, urls)`
- учитывать: topical relevance, unique hosts/diversity, low-value penalties, homepage/service-page penalties.

**Step 2: Update resolve policy**
- `resolve_web_collection_sources(...)` должен выбирать лучший набор по score.
- Разрешить ранний выход только для действительно сильного набора.

### Task 5: Обобщить relevance terms без предметного search hardcode

**Objective:** Сохранить полезную нормализацию, не превращая её в предметный planner.

**Files:**
- Modify: `services/backend/app.py`
- Test: `services/backend/test_smoke.py`

**Step 1:** Оставить токенизацию, split по `-_/`, camelCase split, quoted phrases.
**Step 2:** Оставить acronym normalization только как нейтральную нормализацию subject terms, а не как условие для выбора специальных query families.
**Step 3:** Проверить, что термины помогают ranking/post-filter, но не управляют специальными тематическими ветками.

### Task 6: Прогнать targeted и broad regression tests

**Objective:** Подтвердить, что generic planner не ломает существующий collection path.

**Files:**
- Test: `services/backend/test_smoke.py`

**Step 1: Run targeted tests**
Run: `python3 -m pytest services/backend/test_smoke.py -q -k 'generic_query_planner or result_set_ranking or relevant_web_documents or web_collection_contract'`

**Step 2: Run broader smoke slice**
Run: `python3 -m pytest services/backend/test_smoke.py -q -k 'collection or web_search'`

**Step 3: Verify**
- Никаких предметных BI query в output planner.
- Тесты на BI, машины и LegalAI проходят одной и той же логикой.

### Task 7: Live verification на runtime

**Objective:** Проверить реальное поведение на live backend без смешения контуров.

**Files:**
- Modify: `services/backend/app.py`
- Optional helper probes in `/tmp` only

**Step 1:** Деплой `app.py` на live backend `178.104.207.89`.
**Step 2:** Restart backend.
**Step 3:** Probe для 3 тем:
- history of BI
- история автомобилей / cars
- LegalAI market overview

**Step 4:** Проверить:
- planner queries generic;
- selected candidate-set тематически релевантен;
- нет чужих предметных токенов в query.

### Task 8: Decision log finalization

**Objective:** Зафиксировать архитектурное решение после успешной проверки.

**Files:**
- Modify: `/home/hermes/workspace/decision-log.md`

**Step 1:** Добавить запись только после подтверждения implementation + verification.
**Step 2:** Отразить agreed / implemented / verified / open questions.
