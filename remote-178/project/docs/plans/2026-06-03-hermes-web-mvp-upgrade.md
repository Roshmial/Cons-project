# Hermes Web MVP Upgrade Plan

> For Hermes: use this as the execution baseline for the local-first multi-user web MVP upgrade.

Goal: turn the current technical MVP into a usable product-facing web app with a stronger backend model for profile-driven chat, help, and scheduled jobs.

Architecture: keep the current local-first split `frontend -> backend -> Hermes API Server`. Do not add external SaaS or new infrastructure. Extend the existing Flask backend into the app-layer owner of users, profile preferences, jobs, access, subscriptions, run history, and lightweight scheduling. Replace the raw frontend shell with a product-facing UI that uses the same backend.

Tech stack: vanilla HTML/CSS/JS frontend, Flask + SQLite backend, stdlib scheduler thread, Hermes API Server downstream.

---

## Task 1: Redesign the backend data model
Objective: add missing app-layer entities without breaking the current MVP shape.

Files:
- Modify: `services/backend/app.py`

Steps:
1. Add migration-safe schema helpers instead of one big static schema block.
2. Keep users/sessions/threads/messages/feedback.
3. Add app-layer fields for assistant preferences and onboarding state.
4. Add jobs, job_acl, job_recipients, job_subscriptions, job_runs tables.
5. Add indexes for session lookup, thread ordering, job due polling, and run history.

Verification:
- Backend starts on an existing DB.
- New tables are created automatically.
- Existing login/demo data still works.

## Task 2: Upgrade profile/personalization model
Objective: expose simple, user-facing style controls while preserving backend-owned personalization.

Files:
- Modify: `services/backend/app.py`

Steps:
1. Introduce structured assistant preferences: tone, answer_depth, interaction_mode, about_user.
2. Keep compatibility with the current `style` and other legacy fields.
3. Return both raw profile and human-readable profile summary from `/api/me`.
4. Provide profile preview data suitable for chips/cards instead of raw personalization text.

Verification:
- `/api/me` returns a stable structured payload.
- `/api/me` PATCH persists profile and style controls.

## Task 3: Add job product APIs
Objective: give the frontend a proper product layer for jobs.

Files:
- Modify: `services/backend/app.py`

Steps:
1. Add job list/detail/create/update endpoints.
2. Add visibility, ownership, status, recipients, subscribers, and access payloads.
3. Add subscribe/unsubscribe and run-now endpoints.
4. Add run history endpoint and next-runs preview.
5. Keep permissions simple but real: owner/admin/editor/viewer/subscriber.

Verification:
- A normal user can create and edit own jobs.
- A viewer can see shared/workspace jobs but cannot edit them.
- Run history is stored and returned.

## Task 4: Add lightweight backend scheduler
Objective: make scheduled jobs actually execute in the MVP without external services.

Files:
- Modify: `services/backend/app.py`

Steps:
1. Add a low-frequency polling scheduler thread.
2. Poll only active jobs whose next_run_at is due.
3. Execute jobs via the same Hermes API downstream or the mock mode.
4. Save run status, summaries, durations, and errors.
5. Recompute the next run after each execution.

Verification:
- `run now` creates a successful history item.
- Due jobs get executed automatically while backend is running.
- Paused jobs do not run.

## Task 5: Replace the frontend UX shell
Objective: turn the current technical mockup into a product-facing interface.

Files:
- Modify: `services/frontend/index.html`
- Modify: `services/frontend/app.js`
- Modify: `services/frontend/config.js` if needed

Steps:
1. Replace technical copy on login and main screens.
2. Add welcome/empty states, style chip, quick style editor, help panel.
3. Restructure navigation into Chat / Jobs / Profile / Help / Admin.
4. Hide technical runtime details from normal users.
5. Add a real Jobs section with list, detail panel, create/edit drawer, subscribe actions, and run history.

Verification:
- Login, chat, profile, help, jobs, and admin screens all render.
- New chat empty-state and jobs flows work without console errors.

## Task 6: Optimize runtime and code paths
Objective: keep the upgraded MVP fast and lightweight.

Files:
- Modify: `services/backend/app.py`
- Modify: `services/frontend/app.js`
- Modify: `services/frontend/index.html`

Steps:
1. Use WAL and sensible SQLite pragmas.
2. Add indexes for hot queries.
3. Avoid redundant frontend fetches and rerenders.
4. Avoid expensive DOM rebuilds where not needed.
5. Keep polling/scheduler intervals conservative.

Verification:
- No obvious N+1 fetch pattern in boot flow.
- Jobs polling does not busy-loop.
- UI actions remain responsive.

## Task 7: Verify end-to-end behavior
Objective: prove the upgraded MVP works.

Files:
- Create or modify lightweight test assets as needed.

Steps:
1. Add a backend smoke test script or unittest coverage for auth/profile/threads/jobs.
2. Run backend tests.
3. Start backend/frontend locally.
4. Validate key UX flows in the browser.
5. Fix any issues found during QA.

Verification:
- Tests pass.
- Browser smoke checks pass.
- No blocking console or API errors remain.
