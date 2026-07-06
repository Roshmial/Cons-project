# Core PPT Improvements Implementation Plan

> **For Hermes:** use this as the execution contract for the core-only PPTX stream. Do not pull `ppt-master` workflow or UI/product logic into this phase.

**Goal:** strengthen the existing core PPTX generation path so it stays fast and chat-first, but becomes more reliable, more template-aware, and easier to verify.

**Architecture:** keep the current export route in `services/backend/app.py` as the orchestration owner. Add a thin presentation-analysis layer for incoming `.pptx`, a normalized internal schema, pre-render capacity/quality checks, and post-render validation. Do not add project/workspace UX or advanced designer features in this plan.

**Tech stack:** Python, Flask backend, `python-pptx`, current Hermes Web backend tests in `services/backend/test_smoke.py`.

---

## Scope boundaries

Included in this plan:
- incoming `.pptx` intake and normalized analysis bundle;
- route signals for template/enhance/rebuild candidates;
- slot capacity checks before final PPTX build;
- read-back validation of generated `.pptx`;
- safer artifact publish pattern;
- selective export hardening only where it improves current core quality.

Explicitly excluded from this plan:
- separate designer mode UI;
- per-user/per-project presentation studio;
- `ppt-master as is` workflow orchestration;
- audio, narration, transitions, advanced beautify UX.

---

## Current codebase anchor points

Primary backend file:
- `services/backend/app.py`

Relevant existing functions already present:
- `extract_presentation_source_from_thread(...)` — `app.py:4820+`
- `choose_content_chunk_preferred(...)` — `app.py:4935+`
- `choose_pptx_body_font_size(...)` — `app.py:4958+`
- `build_presentation_plan(...)` — `app.py:4997+`
- `build_message_export_pptx(...)` — `app.py:5180+`
- `detect_message_export_format(...)` — `app.py:5984+`

Relevant existing tests:
- `services/backend/test_smoke.py:1631+` — presentation parsing/planning tests
- `services/backend/test_smoke.py:1528+` — PPTX export tests

Recommended new module group:
- `services/backend/ppt_core/`
  - `__init__.py`
  - `schema.py`
  - `intake.py`
  - `signals.py`
  - `capacity.py`
  - `validation.py`
  - `publish.py`

Recommended new tests:
- `services/backend/tests/test_ppt_core_intake.py`
- `services/backend/tests/test_ppt_core_signals.py`
- `services/backend/tests/test_ppt_core_capacity.py`
- `services/backend/tests/test_ppt_core_validation.py`

If the repo currently keeps everything in `test_smoke.py`, it is acceptable to start there for narrow regression coverage and extract later.

---

## Delivery strategy

Implement in 5 phases:
1. analysis and schema foundation;
2. route signals;
3. pre-render capacity checks;
4. post-render validation + safe publish;
5. selective hardening of the current export path.

Each phase must end with passing targeted tests.

---

## Phase 1 — Intake and normalized schema

### Task 1.1: Create internal schema for PPTX analysis bundle

**Objective:** define the canonical internal format for source PPTX analysis so core logic does not depend on `ppt-master` JSON shape.

**Files:**
- Create: `services/backend/ppt_core/schema.py`
- Modify: `services/backend/app.py`
- Test: `services/backend/tests/test_ppt_core_intake.py`

**Implementation notes:**
Create plain dict/dataclass helpers for:
- deck identity:
  - `title`
  - `subtitle`
  - `slide_count`
  - `aspect_ratio`
  - `theme_fonts`
  - `theme_colors`
- slide inventory:
  - `slide_index`
  - `page_type`
  - `text_summary`
  - `slots`
  - `tables`
  - `charts`
- slot:
  - `role`
  - `shape_name`
  - `geometry {x,y,width,height}`
  - `text`
  - `paragraph_count`
  - `text_metrics`

Do not over-generalize; keep only fields needed for core routing and checks.

**Verification:**
- normalized bundle can be constructed from a minimal fixture without optional fields;
- missing optional values do not crash the schema normalizer.

### Task 1.2: Add local PPTX intake helper

**Objective:** extract structural information from an incoming `.pptx` into the normalized schema.

**Files:**
- Create: `services/backend/ppt_core/intake.py`
- Modify: `services/backend/app.py`
- Test: `services/backend/tests/test_ppt_core_intake.py`

**Implementation notes:**
Use `python-pptx` first. Do not wait for `ppt-master` integration to start this layer.

Implement helper:
- `analyze_source_pptx(path: str) -> dict[str, Any]`

The first version should extract:
- deck title where available;
- slide count;
- slide size / aspect ratio;
- per-slide text boxes and their text;
- rough slot geometry;
- table presence;
- chart presence.

Store only what core needs right now. If later we replace/enrich this with `ppt-master` intake, the internal schema stays unchanged.

**Verification:**
- test with one existing fixture from `services/backend/data/message_exports/*.pptx`;
- returned bundle includes slide_count and at least one slide entry.

### Task 1.3: Wire intake into current backend as enrichment, not as mandatory route change

**Objective:** allow backend to analyze incoming `.pptx` when present, without breaking current generation flow.

**Files:**
- Modify: `services/backend/app.py`
- Test: `services/backend/test_smoke.py`

**Implementation notes:**
Add a helper like:
- `maybe_analyze_uploaded_pptx(file_meta: dict[str, Any]) -> dict[str, Any] | None`

Only call it when the file is a `.pptx` and is locally available.
Do not make PPTX analysis a hard dependency for all export requests.

**Verification:**
- non-PPTX attachments skip analysis cleanly;
- PPTX attachment yields normalized analysis bundle;
- generation path with no uploaded PPTX still behaves exactly as before.

---

## Phase 2 — Route signals for core behavior

### Task 2.1: Implement PPTX route signal inference

**Objective:** infer whether the uploaded/source PPTX looks like template input, enhance target, or source reference.

**Files:**
- Create: `services/backend/ppt_core/signals.py`
- Modify: `services/backend/app.py`
- Test: `services/backend/tests/test_ppt_core_signals.py`

**Implementation notes:**
Implement a narrow helper:
- `infer_pptx_route_signals(bundle: dict[str, Any], user_text: str) -> dict[str, Any]`

First signals:
- `template_candidate`
- `enhance_candidate`
- `source_reference_candidate`
- `rebuild_candidate`
- `dense_layout_risk`

Inference can be heuristic:
- many repeated slot structures across slides -> template candidate;
- existing populated text + user asks “дополни/улучши/добавь” -> enhance candidate;
- many text-heavy slides -> dense_layout_risk.

Do not yet add new user-visible routes. This phase only produces signals for internal planning.

**Verification:**
- tests cover at least 3 heuristic cases;
- absence of bundle returns safe defaults.

### Task 2.2: Thread route signals into `build_presentation_plan(...)`

**Objective:** let plan building react to structural hints without changing the user contract.

**Files:**
- Modify: `services/backend/app.py`
- Test: `services/backend/test_smoke.py`

**Implementation notes:**
Extend source payload passed into `build_presentation_plan(...)` with optional analysis hints:
- `source_pptx_analysis`
- `route_signals`

Use them only for:
- tighter packing for dense layouts;
- table-aware handling;
- preserving simpler slide count where possible.

Avoid major refactor in this step. Keep the current `build_message_export_pptx(...) -> extract_presentation_source_from_thread(...) -> build_presentation_plan(...)` chain intact.

**Verification:**
- old tests still pass;
- at least one new test shows route signals changing plan behavior in a controlled way.

---

## Phase 3 — Pre-render capacity checks

### Task 3.1: Add capacity estimator for planned slides

**Objective:** detect likely overflow before rendering PPTX.

**Files:**
- Create: `services/backend/ppt_core/capacity.py`
- Modify: `services/backend/app.py`
- Test: `services/backend/tests/test_ppt_core_capacity.py`

**Implementation notes:**
Implement:
- `estimate_slide_capacity(plan_item: dict[str, Any]) -> dict[str, Any]`
- `assess_presentation_plan_capacity(plan: list[dict[str, Any]]) -> list[dict[str, Any]]`

Use current logic as baseline:
- `estimate_presentation_item_text_length(...)`
- `choose_content_chunk_preferred(...)`
- `choose_pptx_body_font_size(...)`

Return levels such as:
- `ok`
- `tight`
- `overflow_risk`

The goal is not pixel-perfect prediction; it is early detection of obviously overloaded slides.

**Verification:**
- current medium slides score `ok` or `tight`;
- intentionally overloaded plan item scores `overflow_risk`.

### Task 3.2: Use capacity result to re-chunk before rendering

**Objective:** prefer one extra split over silently producing unreadable content.

**Files:**
- Modify: `services/backend/app.py`
- Test: `services/backend/test_smoke.py`

**Implementation notes:**
When a `content`/`roadmap`/`cards` slide is marked `overflow_risk`:
- first try reducing font within existing bounds already allowed by `choose_pptx_body_font_size(...)`;
- if still risky, split the slide earlier via current chunking helpers;
- preserve the current title/continuation conventions.

Do not invent new slide classes in this step.

**Verification:**
- add regression showing overloaded input no longer stays on one unreadable slide;
- existing compact-slide tests remain green.

---

## Phase 4 — Post-render validation and safe publish

### Task 4.1: Add read-back validator for generated PPTX

**Objective:** verify that generated `.pptx` really contains the expected text structure.

**Files:**
- Create: `services/backend/ppt_core/validation.py`
- Modify: `services/backend/app.py`
- Test: `services/backend/tests/test_ppt_core_validation.py`

**Implementation notes:**
Implement:
- `validate_generated_pptx(path_or_buffer, expected_plan) -> dict[str, Any]`

Minimum checks:
- slide count is at least expected non-empty plan count;
- title slide exists;
- expected section titles or representative texts are present in slide XML or via `python-pptx` read-back;
- generated file opens successfully.

This is not visual validation. It is semantic/structural validation.

**Verification:**
- healthy generated PPTX passes;
- intentionally broken/truncated PPTX fails with actionable status.

### Task 4.2: Introduce safe publish pattern for exported artifacts

**Objective:** never publish a PPTX artifact before successful generation and validation.

**Files:**
- Create: `services/backend/ppt_core/publish.py`
- Modify: `services/backend/app.py`
- Test: `services/backend/test_smoke.py`

**Implementation notes:**
Add helper:
- `publish_validated_artifact(temp_path, final_path, validator_result)`

Rules:
- write to temp path first;
- validate temp file;
- move to final destination only on success;
- keep prior successful artifact untouched on failure.

If current export path is buffer-only, introduce temp-file wrapping at the attachment creation stage, not in the slide rendering core.

**Verification:**
- failed validation does not overwrite final artifact;
- successful validation publishes exactly one final file.

---

## Phase 5 — Selective hardening of current export path

### Task 5.1: Remove duplicate parsing inside `build_message_export_pptx(...)`

**Objective:** stop maintaining two partial presentation parsing paths in the same function.

**Files:**
- Modify: `services/backend/app.py`
- Test: `services/backend/test_smoke.py`

**Current issue:**
`build_message_export_pptx(...)` already computes:
- `presentation_source = extract_presentation_source_from_thread(...)`
- `presentation_plan = build_presentation_plan(...)`

but also reparses `blocks`, `sections`, `title_labels`, `deck_title`, `content_sections` locally again.

**Implementation notes:**
Refactor the function to use `presentation_source` and `presentation_plan` as the only source of truth for slide rendering.

This will make later intake/route-signal/capacity work much safer.

**Verification:**
- no behavior regression in current export tests;
- less duplicated logic in `build_message_export_pptx(...)`.

### Task 5.2: Add render-time hooks for quality metadata

**Objective:** make renderer aware of validated sizing and route hints without bloating the rendering API.

**Files:**
- Modify: `services/backend/app.py`
- Test: `services/backend/test_smoke.py`

**Implementation notes:**
Pass precomputed metadata on each plan item, for example:
- `font_size_override`
- `capacity_status`
- `source_signal_flags`

Keep renderer dumb: it should consume metadata, not recompute planning heuristics.

**Verification:**
- renderer honors explicit font-size override;
- renderer remains backward-compatible if metadata is absent.

### Task 5.3: Add narrow regression for current typography contract

**Objective:** protect the already agreed PPTX typography defaults.

**Files:**
- Modify: `services/backend/test_smoke.py`

**Implementation notes:**
Add test coverage around:
- title size 20 pt;
- subtitle size 14 pt;
- body size default 12 pt with allowed downshift by planner;
- Arial font in generated runs where inspectable.

**Verification:**
- regression test fails if typography contract is changed accidentally.

---

## Suggested test matrix

Add or extend tests for these scenarios:

1. explicit slide-outline text input still builds correctly;
2. short adjacent sections still merge when safe;
3. overloaded content gets split before becoming unreadable;
4. incoming `.pptx` analysis returns normalized slide inventory;
5. route signals for template/enhance/source-reference are inferred sanely;
6. generated `.pptx` passes read-back validation;
7. failed validation prevents final artifact publish.

Targeted commands:
- `cd services/backend && python -m unittest test_smoke.HermesWebBackendSmokeTest.test_parse_presentation_slide_markers_as_headings_for_pptx_export`
- `cd services/backend && python -m unittest test_smoke.HermesWebBackendSmokeTest.test_build_presentation_plan_merges_adjacent_short_sections_when_previous_slide_has_space`
- `cd services/backend && python -m unittest test_smoke.HermesWebBackendSmokeTest.test_choose_pptx_body_font_size_shrinks_before_splitting`
- `cd services/backend && python -m unittest test_smoke.HermesWebBackendSmokeTest.test_message_export_pptx_includes_table_slide_for_table_result`

When new split tests are added, run them individually first, then the grouped PPTX subset.

---

## Recommended implementation order

### Iteration 1
- Task 1.1
- Task 1.2
- Task 1.3

### Iteration 2
- Task 2.1
- Task 2.2

### Iteration 3
- Task 3.1
- Task 3.2

### Iteration 4
- Task 4.1
- Task 4.2

### Iteration 5
- Task 5.1
- Task 5.2
- Task 5.3

---

## Acceptance criteria for the whole core stream

The stream is complete when all of the following are true:

1. The current chat-first PPTX export path still works end-to-end.
2. Incoming `.pptx` files can be structurally analyzed into a normalized internal bundle.
3. Core planning can use route signals without depending on `ppt-master` workflow.
4. Obvious overflow risks are detected before final render and handled by safe re-chunking.
5. Generated `.pptx` files are read-back validated before publish.
6. Failed validation cannot overwrite the last good artifact.
7. Current typography and core user-facing speed remain intact.

---

## Non-goals to defend during implementation

Do not let this core stream drift into:
- designer-mode project/workspace UX;
- advanced beautify controls;
- narration/audio/transitions;
- new frontend tab work;
- deep `ppt-master` runtime embedding.

If a task needs any of those, stop and move it to the separate designer-mode stream.
