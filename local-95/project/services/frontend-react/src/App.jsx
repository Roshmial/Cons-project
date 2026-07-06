import { useEffect, useMemo, useRef, useState } from 'react';
import { marked } from 'marked';
import { ApiError, api, getStoredToken, setStoredToken } from './api.js';

const EMPTY_LOGIN = { email: '', password: '' };
const EMPTY_SETUP = { name: '', email: '', password: '' };
const UI_STATE_STORAGE_KEY = 'hermes_web_mvp_ui_state';
const ADMIN_SECTIONS = ['overview', 'users', 'operations', 'references', 'data_policy'];
const SCREENS = ['chat', 'profile', 'jobs', 'admin'];
const PROFILE_SECTIONS = ['summary', 'identity', 'response', 'files'];
const SOURCE_MODE_LOCAL_ONLY = 'local_only';
const SOURCE_MODE_LOCAL_FIRST = 'local_first';
const SOURCE_MODE_GLOBAL_ONLY = 'global_only';
const MOSCOW_TIMEZONE = 'Europe/Moscow';
const WEEKDAYS = [
  { key: 'mon', label: 'Пн' },
  { key: 'tue', label: 'Вт' },
  { key: 'wed', label: 'Ср' },
  { key: 'thu', label: 'Чт' },
  { key: 'fri', label: 'Пт' },
  { key: 'sat', label: 'Сб' },
  { key: 'sun', label: 'Вс' },
];

function buildDashboardRefreshPrompt(message) {
  const artifact = message?.meta?.dashboard_artifact || {};
  const policy = message?.meta?.request_execution_policy || {};
  const lines = [
    'Обнови дашборд по ранее удачному запросу.',
    '',
    'Что нужно сделать:',
    '- повторно собрать дашборд по той же теме;',
    '- использовать этот chat как основной контекст;',
    '- сохранить результат в локальный markdown-артефакт;',
    '- если появляется новый артефакт, отдай ссылку/путь на него в ответе.',
    '',
    `Исходный запрос: ${messageDisplayText(message) || '—'}`,
    `Предыдущий артефакт: ${artifact.path || '—'}`,
    `Предпочтительный режим обработки: ${policy.search_mode_override || 'default'}`,
    `Разрешить внешние источники: ${policy.allow_external_for_this_request ? 'да' : 'нет'}`,
    `Игнорировать кэш: ${policy.force_refresh ? 'да' : 'нет'}`,
    `Разрешённые источники: ${(policy.selected_source_ids || []).join(', ') || 'не ограничены'}`,
  ];
  return lines.join('\n');
}

function buildDashboardJobDraft(message, timezone = MOSCOW_TIMEZONE) {
  const artifact = message?.meta?.dashboard_artifact || {};
  const titleBase = String(artifact.file_name || messageDisplayText(message) || 'дашборд').replace(/\.[a-z0-9]+$/i, '').trim();
  const draft = initialJobDraft(timezone);
  draft.name = `Обновление дашборда · ${titleBase}`.slice(0, 120);
  draft.description = 'Регулярное обновление понравившегося дашборда из текущего чата.';
  draft.job_type = 'research_watch';
  draft.prompt_template = buildDashboardRefreshPrompt(message);
  draft.parameters = { subject: titleBase || 'дашборд', angle: 'обновление предыдущего удачного дашборда', output: 'обновлённый markdown-дашборд' };
  draft.recipients = [{ recipient_type: 'owner', target_value: 'self', label: 'Только владелец' }];
  draft.deliver = 'origin';
  return draft;
}

function buildAssignedUserJobDraft(user, timezone = MOSCOW_TIMEZONE) {
  const draft = initialJobDraft(timezone);
  const userName = String(user?.name || user?.email || 'пользователь').trim();
  draft.name = `Задача для ${userName}`.slice(0, 120);
  draft.description = `Регулярная задача, назначенная пользователю ${userName}.`;
  draft.prompt_template = `Подготовь результат для пользователя ${userName}. Учитывай его рабочий контекст и верни готовый итог без служебного шума.`;
  if (user?.id != null) {
    draft.visibility = 'shared';
    draft.access = [{ user_id: Number(user.id), role: 'viewer' }];
    draft.recipients = [{ recipient_type: 'fixed_user', target_value: String(user.id), label: userName }];
  }
  return draft;
}

function buildHermesCronSchedule(draft) {
  const [hour = '09', minute = '00'] = String(draft?.time_of_day || '09:00').split(':');
  const prefix = `${Number(minute)} ${Number(hour)}`;
  if (draft?.schedule_kind === 'weekdays') return `${prefix} * * 1-5`;
  if (draft?.schedule_kind === 'weekly') {
    const map = { mon: '1', tue: '2', wed: '3', thu: '4', fri: '5', sat: '6', sun: '0' };
    const cronDays = (draft?.days_of_week || []).map((day) => map[day]).filter(Boolean).join(',') || '1';
    return `${prefix} * * ${cronDays}`;
  }
  if (draft?.schedule_kind === 'monthly') return `${prefix} 1 * *`;
  return `${prefix} * * *`;
}

function formatTs(value) {
  if (!value) return '—';
  try {
    return new Date(value).toLocaleString('ru-RU', { timeZone: MOSCOW_TIMEZONE });
  } catch {
    return value;
  }
}

function formatTsCompact(value) {
  if (!value) return '—';
  try {
    return new Date(value).toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit', timeZone: MOSCOW_TIMEZONE });
  } catch {
    return value;
  }
}

function formatDateTimeLocal(value) {
  if (!value) return '';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return '';
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function formatBytes(value) {
  if (!value && value !== 0) return '—';
  if (value < 1024) return `${value} Б`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} КБ`;
  return `${(value / (1024 * 1024)).toFixed(1)} МБ`;
}

function fileMime(file) {
  return String(file?.mime_type || file?.mime || '').toLowerCase();
}

function isImageFile(file) {
  const mime = fileMime(file);
  if (mime.startsWith('image/')) return true;
  const name = String(file?.original_name || file?.stored_name || file?.name || '').toLowerCase();
  return /\.(png|jpe?g|webp|gif|bmp|svg)$/i.test(name);
}

function isStructuredTextPreview(file) {
  const mime = fileMime(file);
  const name = String(file?.original_name || file?.stored_name || file?.name || '').toLowerCase();
  return mime.startsWith('text/') || /\.(txt|md|csv|tsv|json|xml|ya?ml|docx|xlsx|pdf)$/i.test(name) || mime.includes('sheet') || mime.includes('wordprocessingml') || mime.includes('pdf');
}

function filePreviewUrl(file, fallbackUrl = '') {
  return file?.download_url || fallbackUrl || (file?.id ? `/files/${encodeURIComponent(file.id)}/download` : '');
}

function humanizeJobStatus(status) {
  return ({ active: 'активна', paused: 'на паузе', disabled: 'отключена' })[status] || status || '—';
}

function humanizeRunStatus(status) {
  return ({
    ok: 'успешно',
    success: 'успешно',
    error: 'ошибка',
    failed: 'ошибка',
    running: 'выполняется',
    completed: 'выполнено',
    completed_with_limitations: 'выполнено с ограничениями',
    empty_result: 'без результата',
    needs_clarification: 'нужно уточнение',
    handed_off: 'передано дальше',
  })[status] || status || 'Без запусков';
}

function humanizeRunResultKind(value) {
  return ({
    in_progress: 'идёт выполнение',
    text: 'текстовый результат',
    file: 'файл',
    empty: 'пустой результат',
    error: 'ошибка',
  })[value] || value || '—';
}

function humanizeSurfaceStatus(status) {
  return ({
    running: 'в обработке',
    completed: 'готово',
    completed_with_limitations: 'готово с ограничениями',
    failed: 'ошибка',
    empty_result: 'без результата',
    needs_clarification: 'нужно уточнение',
    handed_off: 'передано дальше',
  })[status] || status || '—';
}

function humanizeAssistantResultKind(value) {
  return ({
    chat_answer: 'Ответ',
    clarification_needed: 'Нужно уточнение',
    file_result: 'Файл',
    artifact_result: 'Артефакт',
    job_result: 'Результат задачи',
    status_update: 'Статус',
    research_result: 'Исследование',
    table_result: 'Таблица',
    structured_result: 'Структурированный результат',
    user_input: 'Сообщение пользователя',
  })[value] || value || 'Ответ';
}

function humanizeAssistantAction(action) {
  return ({
    reply_in_chat: 'Продолжить в чате',
    export_result: 'Можно выгрузить',
    save_as_job: 'Можно сохранить как задачу',
    open_artifact: 'Можно открыть файл',
    clarify_request: 'Нужно уточнить запрос',
    handoff: 'Можно передать дальше',
  })[action] || action || '';
}

function renderAssistantContractStrip(message, canSaveDashboard, onSaveDashboard, onExportMessage) {
  if (message?.role !== 'assistant') return null;
  const surface = message?.surface || {};
  const resultKind = message?.assistant_result_kind || message?.meta?.assistant_result_kind || surface.assistant_result_kind || '';
  const nextActionsRaw = message?.next_actions || message?.meta?.next_actions || surface.next_actions || [];
  const nextActions = Array.isArray(nextActionsRaw) ? nextActionsRaw.filter(Boolean) : [];
  if (['file_result', 'artifact_result', 'job_result'].includes(resultKind)) return null;
  if (message?.meta?.recurring_summary) return null;
  const canExport = Boolean(onExportMessage && message?.id && String(message.id).startsWith('temp-') === false);
  const canExportCsv = canExport && resultKind === 'table_result';
  const canSave = Boolean(canSaveDashboard && nextActions.includes('save_as_job'));
  if (!(canSave || canExport)) return null;
  return (
    <div className="assistant-action-strip">
      {canExport ? <button className="ghost-btn ghost-btn-xs" type="button" onClick={() => onExportMessage(message, 'docx')}>Выгрузить DOCX</button> : null}
      {canExport ? <button className="ghost-btn ghost-btn-xs" type="button" onClick={() => onExportMessage(message, 'pptx')}>Выгрузить PPTX</button> : null}
      {canExportCsv ? <button className="ghost-btn ghost-btn-xs" type="button" onClick={() => onExportMessage(message, 'csv')}>Выгрузить CSV</button> : null}
      {canSave ? <button className="ghost-btn ghost-btn-xs" type="button" onClick={() => onSaveDashboard(message)}>Сохранить как задачу</button> : null}
    </div>
  );
}

function humanizeRunStatusReason(value) {
  return ({
    delivered: 'результат доставлен',
    not_delivered: 'результат есть, но не доставлен',
    no_signal: 'новых сигналов нет',
    error: 'выполнение завершилось ошибкой',
    in_progress: 'задача ещё выполняется',
    limitations: 'результат с ограничениями',
    result_ready: 'результат подготовлен',
    unknown: 'статус требует уточнения',
  })[value] || value || '—';
}

function runStatusChipClass(status) {
  if (status === 'completed') return 'ok';
  if (status === 'failed') return 'danger';
  if (status === 'completed_with_limitations' || status === 'empty_result' || status === 'running') return 'warn';
  return 'muted';
}

function formatDurationMs(value) {
  const ms = Number(value || 0);
  if (!Number.isFinite(ms) || ms <= 0) return '—';
  if (ms < 1000) return `${ms} мс`;
  const seconds = Math.round(ms / 100) / 10;
  if (seconds < 60) return `${seconds} сек`;
  const minutes = Math.floor(seconds / 60);
  const remSeconds = Math.round((seconds % 60) * 10) / 10;
  return remSeconds ? `${minutes} мин ${remSeconds} сек` : `${minutes} мин`;
}

function humanizeVisibility(value) {
  return ({ private: 'Приватно', shared: 'По доступу', workspace: 'Вся рабочая область' })[value] || value || '—';
}

function humanizeUserStatus(value) {
  return ({ active: 'Активен', inactive: 'Не активен', deleted: 'Удалён' })[value] || value || '—';
}

function initialJobDraft(timezone = MOSCOW_TIMEZONE) {
  return {
    name: '',
    version: null,
    description: '',
    prompt_template: '',
    job_type: 'daily_brief',
    visibility: 'private',
    status: 'active',
    source_of_truth: 'local_jobs',
    deliver: 'origin',
    self_subscribe_enabled: false,
    self_subscribe_scope: 'visible_users',
    schedule_kind: 'daily',
    time_of_day: '09:00',
    timezone,
    start_date: new Date().toISOString().slice(0, 10),
    days_of_week: ['mon'],
    parameters: {},
    access: [],
    recipients: [],
  };
}

function initialRequestExecutionPolicy(policy = null) {
  const runtimePolicy = policy || {};
  return {
    model_preference: runtimePolicy.model_preference || 'auto',
    search_mode_override: runtimePolicy.default_mode || SOURCE_MODE_LOCAL_FIRST,
    selected_source_ids: [],
    allow_external_for_this_request: null,
    force_refresh: false,
    save_results_locally: true,
  };
}

function dataPolicyModeOptions() {
  return [
    { value: SOURCE_MODE_LOCAL_ONLY, label: 'Только внутренние', description: 'Использовать только внутренние и локальные источники без выхода во внешний контур.' },
    { value: SOURCE_MODE_LOCAL_FIRST, label: 'Сначала внутренние, затем внешние', description: 'Сначала проверять внутренние источники, при нехватке данных подключать внешние.' },
    { value: SOURCE_MODE_GLOBAL_ONLY, label: 'Внешние источники', description: 'Сразу разрешать внешний поиск и внешние коннекторы.' },
  ];
}

function normalizeDataPolicyShape(dashboardPolicy = null, dataSources = []) {
  const policy = dashboardPolicy || {};
  const allowedSources = new Set(Array.isArray(policy.allowed_sources) ? policy.allowed_sources : []);
  const sourceItems = Array.isArray(dataSources) ? dataSources.map((item) => ({
    source_key: item.item_key,
    item_key: item.item_key,
    name: item.label || item.item_key,
    description: item.description || '',
    connector_kind: item.route || item.scope || 'source',
    usage_scope: item.scope || 'mixed',
    origin: item.scope === 'global' ? 'external' : 'internal',
    trust_level: item.scope === 'global' ? 'review_required' : 'trusted',
    registration_status: item.available === false ? 'unavailable' : 'registered',
    enabled: item.enabled === undefined ? allowedSources.has(item.item_key) : Boolean(item.enabled),
    available: item.available !== false,
    child_connectors: Array.isArray(item.child_connectors) ? item.child_connectors.map((child) => ({ ...child })) : [],
  })) : [];
  return {
    source_registry: {
      version: 1,
      items: sourceItems,
    },
    processing_policy: {
      default_mode: policy.source_mode || SOURCE_MODE_LOCAL_FIRST,
      allow_override: true,
      default_external_action: 'preserve_local_copy',
      source_selection_order: [SOURCE_MODE_LOCAL_ONLY, SOURCE_MODE_LOCAL_FIRST, SOURCE_MODE_GLOBAL_ONLY],
      mode_options: dataPolicyModeOptions(),
      default_global_source: policy.default_global_source || 'web_research',
      connector_targets: { ...(policy.connector_targets || {}) },
      notes: policy.notes || '',
    },
  };
}

function cloneDataPolicyForDraft(policy = null) {
  const runtime = policy || {};
  return {
    source_registry: {
      version: runtime.source_registry?.version || 1,
      items: Array.isArray(runtime.source_registry?.items)
        ? runtime.source_registry.items.map((item) => ({
          ...item,
          child_connectors: Array.isArray(item.child_connectors) ? item.child_connectors.map((child) => ({ ...child })) : [],
        }))
        : [],
    },
    processing_policy: {
      default_mode: runtime.processing_policy?.default_mode || SOURCE_MODE_LOCAL_FIRST,
      allow_override: Boolean(runtime.processing_policy?.allow_override),
      allowed_modes: Array.isArray(runtime.processing_policy?.allowed_modes) ? [...runtime.processing_policy.allowed_modes] : [],
      mode_labels: { ...(runtime.processing_policy?.mode_labels || {}) },
      mode_descriptions: { ...(runtime.processing_policy?.mode_descriptions || {}) },
      default_external_action: runtime.processing_policy?.default_external_action || 'preserve_local_copy',
      source_selection_order: Array.isArray(runtime.processing_policy?.source_selection_order) ? [...runtime.processing_policy.source_selection_order] : [],
      mode_options: Array.isArray(runtime.processing_policy?.mode_options) ? runtime.processing_policy.mode_options.map((item) => ({ ...item })) : [],
      default_global_source: runtime.processing_policy?.default_global_source || 'web_research',
      connector_targets: { ...(runtime.processing_policy?.connector_targets || {}) },
      notes: runtime.processing_policy?.notes || '',
    },
  };
}

function initialAppState() {
  return {
    authenticated: false,
    screen: 'chat',
    user: null,
    personalization: '',
    profileSummary: null,
    bootstrap: null,
    feedbackReasons: [],
    threads: [],
    activeThreadId: null,
    chatWelcomeDismissed: false,
    messages: [],
    userFiles: [],
    threadFiles: [],
    jobsMeta: null,
    jobs: [],
    activeJobId: null,
    activeJob: null,
    admin: {
      section: 'overview',
      health: null,
      users: [],
      threads: [],
      jobs: [],
      references: {},
      chatNotice: null,
      dataPolicy: null,
      events: [],
      eventsFilters: { date_from: '', date_to: '', limit: 100 },
      loaded: false,
    },
  };
}

function jobTemplateFieldClass(templateKey, field = null) {
  const key = String(field?.key || '');
  if (templateKey === 'research_watch') {
    if (key === 'angle') return 'job-template-field job-template-field-tall job-template-field-right';
    if (key === 'subject') return 'job-template-field job-template-field-left-top';
    if (key === 'output') return 'job-template-field job-template-field-left-bottom';
  }
  return 'job-template-field';
}

function jobTemplateFieldRows(field = null) {
  const rows = Number(field?.rows || 0);
  if (rows >= 2) return rows;
  return field?.type === 'textarea' ? 3 : undefined;
}

function readUiState() {
  try {
    const raw = window.localStorage.getItem(UI_STATE_STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch {
    return {};
  }
}

function writeUiState(nextState) {
  try {
    window.localStorage.setItem(UI_STATE_STORAGE_KEY, JSON.stringify(nextState));
  } catch {}
}

const HIDDEN_OBJECTS_STORAGE_KEY = 'hermes.web.hiddenObjects.v1';

function readHiddenObjects() {
  try {
    const raw = window.localStorage.getItem(HIDDEN_OBJECTS_STORAGE_KEY);
    if (!raw) return { threads: [], jobs: [], files: [] };
    const parsed = JSON.parse(raw);
    return {
      threads: Array.isArray(parsed?.threads) ? parsed.threads.map(String) : [],
      jobs: Array.isArray(parsed?.jobs) ? parsed.jobs.map(String) : [],
      files: Array.isArray(parsed?.files) ? parsed.files.map(String) : [],
    };
  } catch {
    return { threads: [], jobs: [], files: [] };
  }
}

function writeHiddenObjects(nextState) {
  try {
    window.localStorage.setItem(HIDDEN_OBJECTS_STORAGE_KEY, JSON.stringify({
      threads: Array.isArray(nextState?.threads) ? nextState.threads : [],
      jobs: Array.isArray(nextState?.jobs) ? nextState.jobs : [],
      files: Array.isArray(nextState?.files) ? nextState.files : [],
    }));
  } catch {}
}

function fileHideKey(file) {
  if (!file) return '';
  if (file.id !== null && file.id !== undefined) return `file:${file.id}`;
  return [
    file.original_name || file.stored_name || 'file',
    file.relative_path || '',
    file.source_message_id || '',
    file.thread_file_role || '',
    file.download_url || '',
  ].join('::');
}

function stripCitationArtifacts(text) {
  return String(text || '')
    .replace(/【[^】]*†L\d+(?:-L\d+)?】/g, '')
    .replace(/[\t\f\v\u00a0 ]{2,}/g, ' ')
    .replace(/ ?\n ?/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

function filterHiddenItems(items, hiddenIds, keyFn = (item) => item?.id) {
  const hidden = new Set((hiddenIds || []).map(String));
  return (items || []).filter((item) => !hidden.has(String(keyFn(item))));
}

function pickExistingId(items, preferredId, fallbackId = null) {
  if (preferredId !== null && preferredId !== undefined && items.some((item) => String(item.id) === String(preferredId))) return preferredId;
  if (fallbackId !== null && fallbackId !== undefined && items.some((item) => String(item.id) === String(fallbackId))) return fallbackId;
  return items[0]?.id || null;
}

function sanitizeScreen(screen, role = 'user') {
  if (screen === 'admin' && role !== 'admin') return 'chat';
  return SCREENS.includes(screen) ? screen : 'chat';
}

function sanitizeAdminSection(section) {
  return ADMIN_SECTIONS.includes(section) ? section : 'overview';
}

function profileFormFromUser(user) {
  return {
    name: user?.name || '',
    timezone: user?.timezone || 'UTC',
    language: user?.language || 'ru',
    team: user?.team || '',
    title: user?.title || '',
    goals: user?.goals || '',
    constraints: user?.constraints || '',
    pinned: Array.isArray(user?.pinned) ? user.pinned.join('\n') : '',
    tone: user?.assistant_profile?.tone || 'business',
    answer_depth: user?.assistant_profile?.answer_depth || 'balanced',
    interaction_mode: user?.assistant_profile?.interaction_mode || 'clarify_when_needed',
    about_user: user?.assistant_profile?.about_user || '',
  };
}

function adminUserFormFromUser(user = null) {
  return {
    id: user?.id || null,
    version: user?.version ?? null,
    email: user?.email || '',
    password: '',
    name: user?.name || '',
    role: user?.role || 'user',
    status: user?.status || 'active',
    timezone: user?.timezone || 'UTC',
    language: user?.language || 'ru',
    team: user?.team || '',
    title: user?.title || '',
    goals: user?.goals || '',
    style: user?.style || '',
    constraints: user?.constraints || '',
    pinned: Array.isArray(user?.pinned) ? user.pinned.join('\n') : '',
    tone: user?.assistant_profile?.tone || 'business',
    answer_depth: user?.assistant_profile?.answer_depth || 'balanced',
    interaction_mode: user?.assistant_profile?.interaction_mode || 'compare_options',
    about_user: user?.assistant_profile?.about_user || '',
  };
}

function buildAdminUserPayload(form) {
  return {
    ...(form.id ? { version: form.version ?? 1 } : {}),
    email: form.email.trim(),
    password: form.password,
    role: form.role,
    name: form.name.trim(),
    status: form.status,
    timezone: form.timezone.trim(),
    language: form.language.trim(),
    team: form.team.trim(),
    title: form.title.trim(),
    goals: form.goals.trim(),
    style: form.style.trim() || `${form.tone}, ${form.answer_depth}, ${form.interaction_mode}`,
    constraints: form.constraints.trim(),
    pinned: form.pinned.split('\n').map((item) => item.trim()).filter(Boolean),
    assistant_profile: {
      tone: form.tone,
      answer_depth: form.answer_depth,
      interaction_mode: form.interaction_mode,
      about_user: form.about_user.trim(),
    },
  };
}

function buildReferenceDraft(datasetKey, item = null) {
  const hiddenExtra = { ...(item || {}) };
  ['id', 'dataset_key', 'created_at', 'updated_at', 'item_key', 'label', 'sort_order', 'status', 'is_active', 'deleted_at', 'version'].forEach((key) => delete hiddenExtra[key]);
  return {
    datasetKey,
    item_key: item?.item_key || '',
    label: item?.label || '',
    sort_order: item?.sort_order ?? 0,
    status: item?.status || (item?.deleted_at ? 'deleted' : item?.is_active === false ? 'inactive' : 'active'),
    hiddenExtra,
  };
}

function parseReferenceDraftPayload(draft) {
  const extra = { ...(draft.hiddenExtra || {}) };
  return {
    ...extra,
    item_key: draft.item_key.trim(),
    label: draft.label.trim(),
    sort_order: Number(draft.sort_order || 0),
    status: draft.status,
    is_active: draft.status === 'active',
    deleted_at: draft.status === 'deleted' ? '1' : null,
  };
}

function usersAvailableForAccess(users, currentUserId) {
  return (users || []).filter((user) => Number(user.id) !== Number(currentUserId) && user.status !== 'deleted');
}

function threadsAvailableForRecipients(threads, currentThreadId) {
  return (threads || []).filter((thread) => Number(thread.id) !== Number(currentThreadId));
}

function filterAssignableUsers(users, { query = '', role = 'all', team = 'all' } = {}) {
  const needle = String(query || '').trim().toLowerCase();
  return (users || []).filter((user) => {
    if (role !== 'all' && String(user.role || '') !== String(role)) return false;
    if (team !== 'all' && String(user.team || '') !== String(team)) return false;
    if (!needle) return true;
    const haystack = [user.name, user.email, user.role, user.team, user.title].join(' ').toLowerCase();
    return haystack.includes(needle);
  });
}

function uniqueUserTeams(users) {
  return Array.from(new Set((users || []).map((user) => String(user.team || '').trim()).filter(Boolean))).sort((a, b) => a.localeCompare(b, 'ru'));
}

function recipientLabel(item) {
  if (!item) return '—';
  if (item.recipient_type === 'owner') return item.label || 'Владелец задачи';
  if (item.recipient_type === 'fixed_user') return item.label || `Пользователь ${item.target_value}`;
  if (item.recipient_type === 'fixed_thread') return item.label || `Чат ${item.target_value}`;
  return item.label || item.target_value || '—';
}

function accessLabel(row, users) {
  const user = (users || []).find((item) => Number(item.id) === Number(row.user_id));
  return user?.name || user?.email || `user:${row.user_id}`;
}

function messageDisplayText(message) {
  const preferred = typeof message?.display_text === 'string' && message.display_text.trim()
    ? message.display_text
    : (typeof message?.meta?.display_text === 'string' ? message.meta.display_text : '');
  const raw = stripCitationArtifacts(preferred || (typeof message?.content === 'string' ? message.content : ''));
  if (message?.role === 'user' && (message?.meta?.attachments || []).length) {
    if (message?.meta?.user_text !== undefined) return message.meta.user_text || '';
    return raw.replace(/\n\nВ сообщении приложены файлы:[\s\S]*$/, '').trim();
  }
  if (message?.role === 'assistant') {
    const recurring = message?.meta?.recurring_summary || null;
    if (recurring) {
      return '';
    }
    return stripFrontendReasoningPrelude(raw.replace(/^MEDIA:[^\n]+$/gm, '').replace(/\n{3,}/g, '\n\n').trim());
  }
  return raw;
}

function collectThreadFilesFromMessages(messages) {
  const result = [];
  const seen = new Set();
  for (const message of Array.isArray(messages) ? messages : []) {
    const attachments = Array.isArray(message?.meta?.attachments) ? message.meta.attachments : [];
    attachments.forEach((file, index) => {
      const key = [message?.id || 'm', file?.id || file?.stored_name || file?.original_name || index].join('::');
      if (seen.has(key)) return;
      seen.add(key);
      const assistantGenerated = Boolean(file?.assistant_generated || file?.kind === 'assistant_generated');
      result.push({
        ...file,
        source_message_id: message?.id || null,
        created_at: file?.created_at || message?.created_at || null,
        preview_summary: file?.preview_summary || file?.preview_excerpt || '',
        preview_lines: Array.isArray(file?.preview_lines) ? file.preview_lines : [],
        thread_file_role: assistantGenerated ? 'assistant_result' : 'message_attachment',
        file_origin: file?.file_origin || (assistantGenerated ? 'assistant_generated' : 'user_upload'),
        file_kind: file?.file_kind || (assistantGenerated ? 'generated_result' : 'input_file'),
        file_surface: {
          extraction_status: file?.text_extracted ? 'recognized' : 'not_recognized',
          preview_status: file?.preview_excerpt || file?.preview_summary || (Array.isArray(file?.preview_lines) && file.preview_lines.length) ? 'available' : 'unavailable',
          file_kind: file?.file_kind || (assistantGenerated ? 'generated_result' : 'input_file'),
          file_origin: file?.file_origin || (assistantGenerated ? 'assistant_generated' : 'user_upload'),
          used_in_response: assistantGenerated,
          generated_from_request: assistantGenerated,
        },
      });
    });
  }
  return result;
}

function resolveThreadFiles(threadPayload) {
  if (Array.isArray(threadPayload?.thread_files) && threadPayload.thread_files.length) return threadPayload.thread_files;
  if (Array.isArray(threadPayload?.thread?.thread_files) && threadPayload.thread.thread_files.length) return threadPayload.thread.thread_files;
  return collectThreadFilesFromMessages(threadPayload?.messages || []);
}

function stripAttachedFileNote(text) {
  return String(text || '').replace(/\s*Файл приложен к сообщению\.?\s*$/i, '').trim();
}

function stripFrontendReasoningPrelude(text) {
  const raw = String(text || '').trim();
  if (!raw) return '';
  const digestAnchor = raw.match(/(Дайджест\s+ИТ-консалтинга\s+за\s+\d{2}\.\d{2}\.\d{4}\s*\nОбработано\s+непустых\s+сообщений:[\s\S]*$)/i);
  if (digestAnchor?.[1]?.trim()) return digestAnchor[1].trim();
  const directNoticeStripped = raw.replace(/^Примечание:\s+(?:включён\s+глубокий\s+reasoning-режим|R1\s+временно\s+отключён|достигнут\s+ваш\s+суточный\s+лимит\s+R1|достигнут\s+суточный\s+глобальный\s+лимит\s+R1|достигнут\s+суточный\s+бюджет\s+R1|лимит\s+reasoning-модели\s+исчерпан)[^\n]*\n*/i, '').trim();
  if (directNoticeStripped !== raw) return directNoticeStripped;
  const lines = raw.split('\n');
  const markers = [
    'we have the payload data',
    'need to extract top_candidates',
    "let's parse them",
    "we'll need to parse",
    'now construct each line',
    "i'll copy each entry",
    "let's extract data manually",
    'хорошо, пользователь спрашивает',
    'нужно дать чёткий и структурированный ответ',
    'нужно дать четкий и структурированный ответ',
    'сначала вспомню',
    'из системного промпта',
    'но в данном вопросе',
  ];
  const suspiciousIndexes = [];
  for (let index = 0; index < Math.min(lines.length, 60); index += 1) {
    const line = String(lines[index] || '').trim().toLowerCase();
    if (!line) continue;
    if (markers.some((marker) => line.includes(marker))) suspiciousIndexes.push(index);
  }
  if (!suspiciousIndexes.length) return raw;
  const last = suspiciousIndexes[suspiciousIndexes.length - 1];
  for (let index = last + 1; index < lines.length; index += 1) {
    const candidate = String(lines[index] || '').trim();
    if (!candidate) continue;
    if (/^#+\s+/.test(candidate)) return lines.slice(index).join('\n').trim();
    if (/^дайджест\b/i.test(candidate)) return lines.slice(index).join('\n').trim();
    if (/^\*\*/.test(candidate)) return lines.slice(index).join('\n').trim();
    if (/^[А-ЯЁA-Z]/.test(candidate)) return lines.slice(index).join('\n').trim();
  }
  return raw;
}

function extractDigestBody(text) {
  const cleaned = stripFrontendReasoningPrelude(stripAttachedFileNote(text));
  const specific = [...cleaned.matchAll(/Дайджест ИТ-консалтинга за[\s\S]*?(?=(?:\n\n[A-ZА-ЯЁa-zа-яё].*?\b(?:Now|Let's|I'll)\b)|$)/gi)];
  if (specific.length) return specific[specific.length - 1][0].trim();
  const countersTail = [...cleaned.matchAll(/(?:обработано[^\n]*\n)?(?:в\s+)?дайджесте:\s*\d+[\s\S]*$/gi)];
  if (countersTail.length) return countersTail[countersTail.length - 1][0].trim();
  const generic = [...cleaned.matchAll(/Дайджест[\s\S]*$/gi)];
  return generic.length ? generic[generic.length - 1][0].trim() : cleaned;
}

function looksLikeDigestText(text) {
  const body = extractDigestBody(text);
  return /^Дайджест\b/i.test(body)
    || /(?:^|\n)(?:обработано[^\n]*\n)?(?:в\s+)?дайджесте:\s*\d+/i.test(body)
    || /^-\s+.+;.+;.+\[пост\]\(/m.test(body)
    || (/\*\*.+\*\*/s.test(body) && /(?:^|\n)Канал:/m.test(body) && /(?:^|\n)(?:Время|Дата):/m.test(body));
}

function looksLikeRichRecurringBody(text) {
  const body = String(text || '').trim();
  if (!body) return false;
  return looksLikeDigestText(body)
    || /\[[^\]]+\]\((https?:\/\/|mailto:).+?\)/.test(body)
    || /\*\*[^*]+\*\*/.test(body)
    || /^[-*]\s+/m.test(body)
    || /^#+\s+/m.test(body)
    || /^```[\s\S]*```$/m.test(body)
    || /^>\s+/m.test(body)
    || /\|.+\|\n\|?\s*:?-{3,}:?(\s*\|\s*:?-{3,}:?)+\s*\|?/m.test(body)
    || /(?:^|\n)Канал:/m.test(body)
    || /(?:^|\n)(?:Время|Дата):/m.test(body)
    || body.split('\n').filter((line) => line.trim()).length >= 3;
}

function reformatSemicolonDigest(text) {
  const body = extractDigestBody(text);
  const lines = body.split('\n');
  const header = [];
  const items = [];
  let inItems = false;
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) {
      if (!inItems && header.length && header[header.length - 1] !== '') header.push('');
      continue;
    }
    if (trimmed.startsWith('- ')) {
      inItems = true;
      items.push(trimmed);
    } else if (!inItems) {
      header.push(trimmed);
    }
  }
  if (!items.length) return body;
  const rendered = items.map((line) => {
    const parts = line.slice(2).split(';').map((part) => part.trim()).filter(Boolean);
    const [title, channel, date, postLink, summary, ...rest] = parts;
    const block = [];
    if (title) block.push(`**${title.replace(/\.+$/, '').trim()}**`);
    const metaParts = [];
    if (channel) metaParts.push(`Канал: ${channel}`);
    if (date) metaParts.push(date);
    if (postLink) metaParts.push(postLink);
    if (metaParts.length) block.push(metaParts.join(' | '));
    if (summary) block.push(`Краткое содержание: ${summary}`);
    if (rest.length) block.push(`Ссылки: ${rest.join(', ')}`);
    return block.join('\n');
  });
  const suffix = /Есть сообщения, которым может понадобиться уточнение классификации\.?/i.test(body)
    ? '\n\nЕсть сообщения, которым может понадобиться уточнение классификации.'
    : '';
  return `${header.join('\n').trim()}\n\n${rendered.join('\n\n')}${suffix}`.trim();
}

function buildDigestCardText(message, recurring) {
  const sources = [
    message?.display_text,
    message?.meta?.display_text,
    recurring?.summary,
    recurring?.status_detail,
  ];
  const source = sources.find((item) => typeof item === 'string' && item.trim()) || '';
  return reformatSemicolonDigest(source);
}

function buildRecurringBodyText(message, recurring) {
  const sources = [
    message?.display_text,
    message?.meta?.display_text,
    recurring?.summary,
    recurring?.status_detail,
  ];
  const source = sources.find((item) => typeof item === 'string' && item.trim()) || '';
  const cleaned = stripFrontendReasoningPrelude(stripAttachedFileNote(source));
  if (!cleaned) return '';
  return looksLikeDigestText(cleaned) ? reformatSemicolonDigest(cleaned) : cleaned;
}

function isSafeMarkdownHref(value) {
  const href = String(value || '').trim();
  return /^(https?:\/\/|mailto:)/i.test(href);
}

function looksLikeMarkdownMessage(text) {
  const body = String(text || '').trim();
  if (!body) return false;
  return /^```[\s\S]*```$/m.test(body)
    || /^(#{1,6})\s+.+$/m.test(body)
    || /^>\s+.+$/m.test(body)
    || /^[-*]\s+.+$/m.test(body)
    || /^\d+\.\s+.+$/m.test(body)
    || /\[[^\]]+\]\((https?:\/\/|mailto:).+?\)/.test(body)
    || /\*\*[^*]+\*\*/.test(body)
    || /(^|\n)[^\n|]+(?:\s*\|\s*[^\n|]+)+\s*\n\|?\s*:?-{3,}:?(\s*\|\s*:?-{3,}:?)+\s*\|?/m.test(body);
}

const MARKDOWN_BR_TOKEN = '__HERMES_MD_BR__';

function renderInlineMarkdown(text, keyPrefix = 'md-inline') {
  const source = String(text || '');
  if (!source) return [];
  const pushWithBreaks = (value) => {
    const parts = String(value || '').split(MARKDOWN_BR_TOKEN);
    parts.forEach((part, index) => {
      if (part) tokens.push(part);
      if (index < parts.length - 1) tokens.push(<br key={`${keyPrefix}-br-${tokens.length}-${index}`} />);
    });
  };
  const tokens = [];
  const pattern = /(\[[^\]]+\]\((https?:\/\/[^)\s]+|mailto:[^)\s]+)\)|`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*)/g;
  let cursor = 0;
  let match;
  while ((match = pattern.exec(source)) !== null) {
    if (match.index > cursor) pushWithBreaks(source.slice(cursor, match.index));
    const token = match[0];
    if (token.startsWith('`') && token.endsWith('`')) {
      tokens.push(<code key={`${keyPrefix}-${tokens.length}`} className="message-md-inline-code">{token.slice(1, -1)}</code>);
    } else if (token.startsWith('**') && token.endsWith('**')) {
      tokens.push(<strong key={`${keyPrefix}-${tokens.length}`}>{token.slice(2, -2)}</strong>);
    } else if (token.startsWith('*') && token.endsWith('*')) {
      tokens.push(<em key={`${keyPrefix}-${tokens.length}`}>{token.slice(1, -1)}</em>);
    } else {
      const linkMatch = token.match(/^\[([^\]]+)\]\((.+)\)$/);
      const href = linkMatch?.[2] || '';
      const label = linkMatch?.[1] || href;
      if (isSafeMarkdownHref(href)) tokens.push(<a key={`${keyPrefix}-${tokens.length}`} href={href} target="_blank" rel="noreferrer">{label}</a>);
      else pushWithBreaks(token);
    }
    cursor = match.index + token.length;
  }
  if (cursor < source.length) pushWithBreaks(source.slice(cursor));
  return tokens;
}

function normalizeMarkdownText(text) {
  return stripCitationArtifacts(String(text || ''))
    .replace(/<br\s*\/?>/gi, MARKDOWN_BR_TOKEN)
    .replace(/\$\\to\$/g, '→')
    .replace(/\$\\\\to\$/g, '→')
    .replace(/\$\\rightarrow\$/g, '→')
    .replace(/\$\\\\rightarrow\$/g, '→')
    .replace(/\$\\leftarrow\$/g, '←')
    .replace(/\$\\\\leftarrow\$/g, '←')
    .replace(/\$\\leftrightarrow\$/g, '↔')
    .replace(/\$\\\\leftrightarrow\$/g, '↔')
    .replace(/\$\\uparrow\$/g, '↑')
    .replace(/\$\\\\uparrow\$/g, '↑')
    .replace(/\$\\downarrow\$/g, '↓')
    .replace(/\$\\\\downarrow\$/g, '↓')
    .replace(/\$\\approx\$/g, '≈')
    .replace(/\$\\\\approx\$/g, '≈')
    .replace(/\$\\neq\$/g, '≠')
    .replace(/\$\\\\neq\$/g, '≠')
    .replace(/\$\\geq\$/g, '≥')
    .replace(/\$\\\\geq\$/g, '≥')
    .replace(/\$\\leq\$/g, '≤')
    .replace(/\$\\\\leq\$/g, '≤')
    .replace(/\$\\pm\$/g, '±')
    .replace(/\$\\\\pm\$/g, '±')
    .replace(/\$\\checkmark\$/g, '✓')
    .replace(/\$\\\\checkmark\$/g, '✓')
    .replace(/\$\\infty\$/g, '∞')
    .replace(/\$\\\\infty\$/g, '∞')
    .replace(/\$\\sim\$/g, '∼')
    .replace(/\$\\\\sim\$/g, '∼')
    .replace(/\$\\approx\$/g, '≈')
    .replace(/\$\\\\approx\$/g, '≈')
    .replace(/\$\\equiv\$/g, '≡')
    .replace(/\$\\\\equiv\$/g, '≡')
    .replace(/\$\\to\$/g, '→')
    .replace(/\$\\\\to\$/g, '→')
    .replace(/\$\\leftarrow\$/g, '←')
    .replace(/\$\\\\leftarrow\$/g, '←')
    .replace(/\$\\rightarrow\$/g, '→')
    .replace(/\$\\\\rightarrow\$/g, '→')
    .replace(/\$\\Rightarrow\$/g, '⇒')
    .replace(/\$\\\\Rightarrow\$/g, '⇒')
    .replace(/\$\\Leftarrow\$/g, '⇐')
    .replace(/\$\\\\Leftarrow\$/g, '⇐')
    .replace(/\$\\leftrightarrow\$/g, '↔')
    .replace(/\$\\\\leftrightarrow\$/g, '↔')
    .replace(/\$\\Rightleftharpoons\$/g, '⇌')
    .replace(/\$\\\\Rightleftharpoons\$/g, '⇌')
    .replace(/\$\\propto\$/g, '∝')
    .replace(/\$\\\\propto\$/g, '∝')
    .replace(/\$\\in\$/g, '∈')
    .replace(/\$\\\\in\$/g, '∈')
    .replace(/\$\\notin\$/g, '∉')
    .replace(/\$\\\\notin\$/g, '∉')
    .replace(/\$\\subseteq\$/g, '⊆')
    .replace(/\$\\\\subseteq\$/g, '⊆')
    .replace(/\$\\supseteq\$/g, '⊇')
    .replace(/\$\\\\supseteq\$/g, '⊇')
    .replace(/\$\\subset\$/g, '⊂')
    .replace(/\$\\\\subset\$/g, '⊂')
    .replace(/\$\\supset\$/g, '⊃')
    .replace(/\$\\\\supset\$/g, '⊃')
    .replace(/\$\\cup\$/g, '∪')
    .replace(/\$\\\\cup\$/g, '∪')
    .replace(/\$\\cap\$/g, '∩')
    .replace(/\$\\\\cap\$/g, '∩')
    .replace(/\$\\forall\$/g, '∀')
    .replace(/\$\\\\forall\$/g, '∀')
    .replace(/\$\\exists\$/g, '∃')
    .replace(/\$\\\\exists\$/g, '∃')
    .replace(/\$\\times\$/g, '×')
    .replace(/\$\\\\times\$/g, '×')
    .replace(/\$\\times\s*([^$]+)\$/g, '×$1')
    .replace(/\$\\\\times\s*([^$]+)\$/g, '×$1');
}

function renderMarkdownParagraph(text, keyPrefix) {
  const lines = normalizeMarkdownText(text).split('\n');
  return lines.map((line, index) => (
    <span key={`${keyPrefix}-line-${index}`}>
      {renderInlineMarkdown(line, `${keyPrefix}-${index}`)}
      {index < lines.length - 1 ? <br /> : null}
    </span>
  ));
}

function isMarkdownTableSeparator(line) {
  const cells = String(line || '').trim();
  if (!/^\|?\s*:?-{3,}:?(\s*\|\s*:?-{3,}:?)+\s*\|?$/.test(cells)) return false;
  return true;
}

function splitMarkdownTableRow(line) {
  return String(line || '').trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map((cell) => cell.trim());
}

function isMarkdownTableHeaderRow(line) {
  const cells = splitMarkdownTableRow(line);
  return cells.length >= 2 && cells.some((cell) => cell) && String(line || '').includes('|');
}

function renderMarkdownTable(headerLine, bodyLines, keyPrefix) {
  const headers = splitMarkdownTableRow(headerLine);
  const rows = bodyLines.map(splitMarkdownTableRow).filter((row) => row.length && row.some((cell) => cell));
  return (
    <div className="message-md-table-wrap" key={keyPrefix}>
      <table className="message-md-table">
        <thead>
          <tr>{headers.map((cell, index) => <th key={`${keyPrefix}-head-${index}`}>{renderInlineMarkdown(normalizeMarkdownText(cell), `${keyPrefix}-head-${index}`)}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((row, rowIndex) => <tr key={`${keyPrefix}-row-${rowIndex}`}>{headers.map((_, colIndex) => <td key={`${keyPrefix}-cell-${rowIndex}-${colIndex}`}>{renderInlineMarkdown(normalizeMarkdownText(row[colIndex] || ''), `${keyPrefix}-cell-${rowIndex}-${colIndex}`)}</td>)}</tr>)}
        </tbody>
      </table>
    </div>
  );
}

function renderAdaptiveMarkdownTable(headerLine, bodyLines, keyPrefix) {
  const headers = splitMarkdownTableRow(headerLine);
  const rows = bodyLines.map(splitMarkdownTableRow).filter((row) => row.length && row.some((cell) => cell));
  if (headers.length <= 4) return renderMarkdownTable(headerLine, bodyLines, keyPrefix);
  return (
    <div className="message-md-table-cards" key={keyPrefix}>
      {rows.map((row, rowIndex) => (
        <section className="message-md-table-card" key={`${keyPrefix}-card-${rowIndex}`}>
          {headers.map((header, colIndex) => {
            const rawCell = normalizeMarkdownText(row[colIndex] || '');
            if (!rawCell) return null;
            return (
              <div className="message-md-table-card-row" key={`${keyPrefix}-card-${rowIndex}-${colIndex}`}>
                <div className="message-md-table-card-label">{renderInlineMarkdown(normalizeMarkdownText(header), `${keyPrefix}-label-${rowIndex}-${colIndex}`)}</div>
                <div className="message-md-table-card-value">{renderInlineMarkdown(rawCell, `${keyPrefix}-value-${rowIndex}-${colIndex}`)}</div>
              </div>
            );
          })}
        </section>
      ))}
    </div>
  );
}

function renderMarkdownTokens(tokens, keyPrefix = 'md', options = {}) {
  if (!Array.isArray(tokens) || tokens.length === 0) return [];
  return tokens.flatMap((token, index) => {
    const key = `${keyPrefix}-${index}`;
    if (!token || token.type === 'space') return [];
    if (token.type === 'hr') return <hr key={key} className="message-md-divider" />;
    if (token.type === 'heading') {
      const level = Math.max(1, Math.min(6, Number(token.depth) || 1));
      const Tag = `h${level}`;
      return <Tag key={key} className={`message-md-heading message-md-heading-${level}`}>{renderInlineMarkdown(token.text || '', key)}</Tag>;
    }
    if (token.type === 'paragraph' || token.type === 'text') {
      const source = typeof token.raw === 'string' && token.raw.trim() ? token.raw.trimEnd() : (token.text || '');
      return <p key={key} className="message-md-paragraph">{renderMarkdownParagraph(source, key)}</p>;
    }
    if (token.type === 'blockquote') {
      return <blockquote key={key} className="message-md-quote">{renderMarkdownTokens(token.tokens || [], `${key}-quote`, options)}</blockquote>;
    }
    if (token.type === 'code') {
      return <pre key={key} className="message-md-code-block"><code data-language={token.lang || undefined}>{token.text || ''}</code></pre>;
    }
    if (token.type === 'list') {
      const ListTag = token.ordered ? 'ol' : 'ul';
      return <ListTag key={key} className="message-md-list">{(token.items || []).map((item, itemIndex) => {
        const itemKey = `${key}-item-${itemIndex}`;
        if (Array.isArray(item.tokens) && item.tokens.length) return <li key={itemKey}>{renderMarkdownTokens(item.tokens, itemKey, options)}</li>;
        return <li key={itemKey}>{renderInlineMarkdown((typeof item.raw === 'string' && item.raw.trim() ? item.raw.replace(/^[-*+\d.\s]+/, '').trimEnd() : item.text) || '', itemKey)}</li>;
      })}</ListTag>;
    }
    if (token.type === 'table') {
      const headerCells = Array.isArray(token.header) ? token.header.map((cell) => (typeof cell === 'string' ? cell : cell?.text || '')) : [];
      const rowCells = Array.isArray(token.rows)
        ? token.rows.map((row) => row.map((cell) => (typeof cell === 'string' ? cell : cell?.text || '')))
        : [];
      const headerLine = `| ${headerCells.join(' | ')} |`;
      const bodyLines = rowCells.map((row) => `| ${row.join(' | ')} |`);
      return options?.adaptiveWideTables
        ? renderAdaptiveMarkdownTable(headerLine, bodyLines, key)
        : renderMarkdownTable(headerLine, bodyLines, key);
    }
    return <p key={key} className="message-md-paragraph">{renderMarkdownParagraph(token.raw || token.text || '', key)}</p>;
  });
}

function renderMarkdownContent(text, options = {}) {
  const source = normalizeMarkdownText(text).replace(/\r\n/g, '\n');
  const tokens = marked.lexer(source, { gfm: true, breaks: false });
  const blocks = renderMarkdownTokens(tokens, 'md', options);
  if (!blocks || blocks.length === 0) return '…';
  return <div className="message-markdown">{blocks}</div>;
}

function compactThreadTitle(thread) {
  return thread?.title || 'Новый чат';
}

function threadLastActivity(thread) {
  return thread?.freshness_at || thread?.updated_at || thread?.created_at || null;
}

function threadHasUnread(thread) {
  return Boolean(thread?.has_unread);
}

function fileSummaryText(file) {
  const excerpt = String(file?.preview_summary || file?.preview_excerpt || file?.preview_text || '').replace(/\s+/g, ' ').trim();
  if (excerpt) return excerpt.length > 140 ? `${excerpt.slice(0, 137)}…` : excerpt;
  if (file?.extraction_summary) return String(file.extraction_summary);
  if (file?.extraction_note) return String(file.extraction_note);
  return file?.text_extracted ? 'Текст извлечён' : 'Файл загружен без текстового извлечения';
}

function humanizeExtractionStatus(file) {
  const status = file?.file_surface?.extraction_status || (file?.text_extracted ? 'recognized' : 'not_recognized');
  return ({
    recognized: 'Текст извлечён',
    partial: 'Извлечён частично',
    not_recognized: 'Текст не извлечён',
  })[status] || 'Статус извлечения не указан';
}

function humanizePreviewStatus(file) {
  const status = file?.file_surface?.preview_status || 'unavailable';
  return status === 'available' ? 'Preview доступен' : 'Preview недоступен';
}

function previewLines(file) {
  if (Array.isArray(file?.preview_lines) && file.preview_lines.length) return file.preview_lines;
  const raw = String(file?.preview_text || file?.extracted_text || '').trim();
  if (!raw) return [];
  return raw.split('\n').map((line) => line.trim()).filter(Boolean).slice(0, 8);
}

function fileStatusMeta(file) {
  return `${formatTs(file?.created_at)} · ${fileSummaryText(file)}`;
}

function humanizeFileKind(value) {
  return ({
    input_file: 'Входной файл',
    reused_file: 'Повторно использованный файл',
    generated_result: 'Сгенерированный результат',
    exported_answer: 'Экспорт предыдущего ответа',
  })[value] || value || 'Файл';
}

function humanizeFileOrigin(value) {
  return ({
    user_upload: 'Загружен пользователем',
    profile_reuse: 'Взят из профиля',
    generated_result: 'Сформирован по запросу',
    generated_file_response: 'Сформирован по запросу',
    assistant_generated: 'Подготовлен ассистентом',
    exported_answer: 'Собран из предыдущего ответа',
    message_export: 'Собран из предыдущего ответа',
  })[value] || value || 'Источник не указан';
}

function fileSurfaceMeta(file) {
  const surface = file?.file_surface || {};
  const bits = [humanizeFileKind(surface.file_kind || file?.file_kind), humanizeFileOrigin(surface.file_origin || file?.file_origin)];
  if (surface.used_in_response) bits.push('использован в этом ответе');
  if (surface.generated_from_request) bits.push('создан по текущему запросу');
  return bits.filter(Boolean).join(' · ');
}

function fileSurfaceBadges(file) {
  const surface = file?.file_surface || {};
  const items = [
    humanizeFileKind(surface.file_kind || file?.file_kind),
    humanizeFileOrigin(surface.file_origin || file?.file_origin),
    surface.extraction_status === 'recognized' ? 'текст распознан' : 'без распознавания текста',
  ].filter(Boolean);
  if (surface.used_in_response) items.push('использован');
  return items;
}

function fileQualityStatus(file) {
  const quality = file?.quality && typeof file.quality === 'object' ? file.quality : null;
  const status = String(quality?.status || '').trim().toLowerCase();
  if (!status) return null;
  return status;
}

function fileQualityChipClass(file) {
  const status = fileQualityStatus(file);
  if (status === 'ok') return 'ok';
  if (status === 'degraded') return 'warn';
  if (status === 'failed') return 'danger';
  return 'muted';
}

function fileQualityLabel(file) {
  const status = fileQualityStatus(file);
  if (status === 'ok') return 'Качество проверено';
  if (status === 'degraded') return 'Есть ограничения';
  if (status === 'failed') return 'Проверка не пройдена';
  return '';
}

function fileQualityDetail(file) {
  const quality = file?.quality && typeof file.quality === 'object' ? file.quality : null;
  const codes = Array.isArray(quality?.warning_codes) ? quality.warning_codes : [];
  const hints = [];
  if (codes.includes('slide_count_mismatch')) hints.push('число слайдов отличается от ожидаемого');
  if (codes.includes('missing_required_titles')) hints.push('часть обязательных секций не найдена');
  if (quality?.status === 'failed') hints.push('backend не подтвердил корректность структуры файла');
  return hints.join(' · ');
}

function starterPromptsFromBootstrap(bootstrap) {
  return Array.isArray(bootstrap?.starter_prompts) ? bootstrap.starter_prompts.filter((item) => String(item || '').trim()) : [];
}

function referenceOptions(bootstrap, datasetKey, currentValue = '') {
  const source = bootstrap?.references?.[datasetKey];
  const items = Array.isArray(source) ? source : Array.isArray(source?.items) ? source.items : [];
  const normalized = items.map((item) => ({
    value: String(item?.item_key || item?.value || ''),
    label: String(item?.label || item?.item_key || item?.value || ''),
    status: item?.status || (item?.deleted_at ? 'deleted' : item?.is_active === false ? 'inactive' : 'active'),
  })).filter((item) => item.value);
  const active = normalized.filter((item) => item.status === 'active');
  const current = String(currentValue || '').trim();
  if (current && !active.some((item) => item.value === current)) {
    const preserved = normalized.find((item) => item.value === current);
    if (preserved) return [...active, { ...preserved, label: `${preserved.label} (${preserved.status === 'deleted' ? 'удалено' : 'не активно'})` }];
    return [...active, { value: current, label: `${current} (текущее значение)` }];
  }
  return active;
}

function needsInteractionSetup(user) {
  if (!user) return false;
  const assistant = user.assistant_profile || {};
  const pinned = Array.isArray(user.pinned) ? user.pinned.filter((item) => String(item || '').trim()) : [];
  return !String(user.goals || '').trim()
    && !String(user.constraints || '').trim()
    && !String(assistant.about_user || '').trim()
    && pinned.length === 0;
}

function filteredUserFiles(userFiles, { query = '', type = 'all' } = {}) {
  const needle = String(query || '').trim().toLowerCase();
  return (userFiles || []).filter((file) => {
    if (type === 'text_ready' && !file.text_extracted) return false;
    if (type === 'stored_only' && file.text_extracted) return false;
    if (!needle) return true;
    const haystack = [file.original_name, file.mime_type, file.preview_text].filter(Boolean).join(' ').toLowerCase();
    return haystack.includes(needle);
  });
}

function sortUsers(users, sort) {
  const current = sort || { key: 'name', direction: 'asc' };
  const factor = current.direction === 'asc' ? 1 : -1;
  return [...(users || [])].sort((a, b) => {
    const valueA = String(current.key === 'threads' ? a.thread_count || 0 : current.key === 'jobs' ? a.job_count || 0 : a[current.key] || '').toLowerCase();
    const valueB = String(current.key === 'threads' ? b.thread_count || 0 : current.key === 'jobs' ? b.job_count || 0 : b[current.key] || '').toLowerCase();
    if (valueA < valueB) return -1 * factor;
    if (valueA > valueB) return 1 * factor;
    return 0;
  });
}

function humanizeProcessingMode(mode, bootstrap) {
  const options = bootstrap?.data_policy?.processing_policy?.mode_options || [];
  const found = options.find((item) => item.value === mode);
  return found?.label || mode || 'По умолчанию';
}

function requestPolicySummary(message) {
  const policy = message?.meta?.request_execution_policy || {};
  const parts = [];
  if (policy.search_mode_override) parts.push(`режим: ${policy.search_mode_override}`);
  if (policy.allow_external_for_this_request) parts.push('внешние источники разрешены');
  if (policy.force_refresh) parts.push('без кэша');
  if (policy.save_results_locally) parts.push('сохранение локально');
  if ((policy.selected_source_ids || []).length) parts.push(`источники: ${(policy.selected_source_ids || []).join(', ')}`);
  return parts.join(' · ');
}

function dashboardText(value, fallback = '—') {
  const text = typeof value === 'string' ? value.trim() : value == null ? '' : String(value).trim();
  return text || fallback;
}

function dashboardNumber(value, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function dashboardPercent(value, total) {
  const current = dashboardNumber(value, 0);
  const max = dashboardNumber(total, 0);
  if (max <= 0) return 0;
  return Math.max(0, Math.min(100, (current / max) * 100));
}

function dashboardColor(index) {
  const palette = ['#2f6df6', '#4f8dff', '#7e56da', '#00a6b7', '#2da56a', '#f59f00', '#cf4f66', '#8b5cf6'];
  return palette[index % palette.length];
}

function renderDashboardSummaryCards(cards) {
  if (!Array.isArray(cards) || cards.length === 0) return null;
  return (
    <div className="summary-grid dashboard-summary-grid">
      {cards.map((card, index) => (
        <div key={`dashboard-summary-${index}`} className="summary-box">
          <span>{dashboardText(card?.label)}</span>
          <strong>{dashboardText(card?.value)}</strong>
          {card?.note ? <div className="muted small">{dashboardText(card.note, '')}</div> : null}
        </div>
      ))}
    </div>
  );
}

function renderDashboardBarList(items) {
  if (!Array.isArray(items) || items.length === 0) return null;
  const maxValue = Math.max(...items.map((item) => dashboardNumber(item?.value, 0)), 1);
  return (
    <div className="dashboard-bar-list">
      {items.map((item, index) => {
        const value = dashboardNumber(item?.value, 0);
        const width = dashboardPercent(value, maxValue);
        return (
          <div key={`dashboard-bar-${index}`} className="dashboard-bar-row">
            <div className="dashboard-bar-row-head">
              <strong>{dashboardText(item?.label)}</strong>
              <span className="muted small">{dashboardText(item?.value)}</span>
            </div>
            <div className="dashboard-bar-track" aria-hidden="true"><div className="dashboard-bar-fill" style={{ width: `${width}%` }} /></div>
            {item?.note ? <div className="muted small">{dashboardText(item.note, '')}</div> : null}
          </div>
        );
      })}
    </div>
  );
}

function renderDashboardPieList(items) {
  if (!Array.isArray(items) || items.length === 0) return null;
  const total = items.reduce((sum, item) => sum + Math.max(0, dashboardNumber(item?.value, 0)), 0);
  if (total <= 0) return null;
  let cursor = 0;
  const segments = items.map((item, index) => {
    const value = Math.max(0, dashboardNumber(item?.value, 0));
    const size = (value / total) * 100;
    const color = dashboardColor(index);
    const start = cursor;
    cursor += size;
    return `${color} ${start}% ${cursor}%`;
  });
  return (
    <div className="dashboard-pie-layout">
      <div className="dashboard-pie-chart" style={{ background: `conic-gradient(${segments.join(', ')})` }} aria-label="Круговая диаграмма" />
      <div className="dashboard-pie-legend">
        {items.map((item, index) => {
          const value = Math.max(0, dashboardNumber(item?.value, 0));
          const percent = dashboardPercent(value, total);
          return (
            <div key={`dashboard-pie-${index}`} className="dashboard-pie-legend-row">
              <span className="dashboard-pie-swatch" style={{ background: dashboardColor(index) }} aria-hidden="true" />
              <div>
                <strong>{dashboardText(item?.label)}</strong>
                {item?.note ? <div className="muted small">{dashboardText(item.note, '')}</div> : null}
              </div>
              <span className="muted small">{dashboardText(item?.value)} · {percent.toFixed(percent >= 10 ? 0 : 1)}%</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function renderDashboardTimeline(items) {
  if (!Array.isArray(items) || items.length === 0) return null;
  return (
    <div className="dashboard-timeline">
      {items.map((item, index) => (
        <div key={`dashboard-timeline-${index}`} className="dashboard-timeline-row">
          <div className="dashboard-timeline-dot" aria-hidden="true" />
          <div className="dashboard-timeline-body">
            <div className="dashboard-timeline-head">
              <strong>{dashboardText(item?.title || item?.label)}</strong>
              {(item?.period || item?.value) ? <span className="muted small">{dashboardText(item.period || item.value)}</span> : null}
            </div>
            {item?.description ? <div>{renderMarkdownContent(item.description)}</div> : null}
          </div>
        </div>
      ))}
    </div>
  );
}

function renderDashboardBulletList(items) {
  if (!Array.isArray(items) || items.length === 0) return null;
  return (
    <div className="dashboard-bullet-list">
      {items.map((item, index) => (
        <div key={`dashboard-bullet-${index}`} className="dashboard-bullet-item">
          <div className="dashboard-bullet-dot" aria-hidden="true" />
          <div>
            <strong>{dashboardText(item?.label || item?.title)}</strong>
            {item?.value ? <div className="muted small">{dashboardText(item.value)}</div> : null}
            {item?.description ? <div>{renderMarkdownContent(item.description)}</div> : null}
          </div>
        </div>
      ))}
    </div>
  );
}

function renderDashboardMatrix(items) {
  if (!Array.isArray(items) || items.length === 0) return null;
  return (
    <div className="dashboard-matrix-grid">
      {items.map((item, index) => (
        <div key={`dashboard-matrix-${index}`} className="dashboard-matrix-card">
          <strong>{dashboardText(item?.label || item?.title)}</strong>
          <div className="dashboard-matrix-value">{dashboardText(item?.value)}</div>
          {item?.note ? <div className="muted small">{dashboardText(item.note, '')}</div> : null}
          {item?.description ? <div>{renderMarkdownContent(item.description)}</div> : null}
        </div>
      ))}
    </div>
  );
}

function renderDashboardBubbleList(items) {
  if (!Array.isArray(items) || items.length === 0) return null;
  return (
    <div className="dashboard-bubble-wrap">
      {items.map((item, index) => (
        <div key={`dashboard-bubble-${index}`} className="dashboard-bubble" style={{ width: `${Math.max(112, Math.min(180, 92 + dashboardNumber(item?.weight || item?.value, 0) * 8))}px`, minHeight: `${Math.max(112, Math.min(180, 92 + dashboardNumber(item?.weight || item?.value, 0) * 8))}px` }}>
          <strong>{dashboardText(item?.label || item?.title)}</strong>
          <span>{dashboardText(item?.value)}</span>
          {item?.note ? <small>{dashboardText(item.note, '')}</small> : null}
        </div>
      ))}
    </div>
  );
}

function normalizeDashboardMetricItems(items) {
  if (!Array.isArray(items)) return [];
  return items.map((item) => {
    if (typeof item === 'string') return { label: item, value: '', chartValue: 0 };
    if (!item || typeof item !== 'object') return { label: dashboardText(item, ''), value: '', chartValue: 0 };
    const chartValue = Number.isFinite(Number(item.ratio))
      ? Number(item.ratio)
      : Number.isFinite(Number(item.value))
        ? Number(item.value)
        : 0;
    return {
      ...item,
      label: item.label || item.title || item.text || item.name || '—',
      value: item.value ?? item.ratio ?? item.meta ?? '',
      chartValue,
      note: item.note || item.meta || item.description || '',
    };
  });
}

function renderDashboardTextList(items) {
  if (!Array.isArray(items) || items.length === 0) return null;
  const rows = items.map((item, index) => {
    const text = typeof item === 'string'
      ? item
      : item?.text || item?.label || item?.title || item?.value || item?.description || '';
    const meta = typeof item === 'object' && item ? (item.meta || item.note || '') : '';
    if (!String(text || '').trim() && !String(meta || '').trim()) return null;
    return (
      <div key={`dashboard-text-item-${index}`} className="dashboard-bullet-item">
        <div className="dashboard-bullet-dot" aria-hidden="true" />
        <div>
          {String(text || '').trim() ? <div>{renderMarkdownContent(String(text))}</div> : null}
          {String(meta || '').trim() ? <div className="muted small">{dashboardText(meta, '')}</div> : null}
        </div>
      </div>
    );
  }).filter(Boolean);
  if (rows.length === 0) return null;
  return <div className="dashboard-bullet-list">{rows}</div>;
}

function renderDashboardGenericItems(items) {
  if (!Array.isArray(items) || items.length === 0) return null;
  const rows = items.map((item, index) => {
    if (typeof item === 'string') {
      return (
        <div key={`dashboard-generic-${index}`} className="dashboard-bullet-item">
          <div className="dashboard-bullet-dot" aria-hidden="true" />
          <div>{renderMarkdownContent(item)}</div>
        </div>
      );
    }
    if (!item || typeof item !== 'object') {
      const text = dashboardText(item, '');
      if (!text) return null;
      return (
        <div key={`dashboard-generic-${index}`} className="dashboard-bullet-item">
          <div className="dashboard-bullet-dot" aria-hidden="true" />
          <div>{text}</div>
        </div>
      );
    }
    const title = item.label || item.title || item.name || item.text || item.value || '';
    const value = item.value && item.value !== title ? item.value : '';
    const meta = item.meta || item.note || item.description || '';
    if (!String(title || '').trim() && !String(value || '').trim() && !String(meta || '').trim()) return null;
    return (
      <div key={`dashboard-generic-${index}`} className="dashboard-bullet-item">
        <div className="dashboard-bullet-dot" aria-hidden="true" />
        <div>
          {String(title || '').trim() ? <strong>{dashboardText(title, '')}</strong> : null}
          {String(value || '').trim() ? <div className="muted small">{dashboardText(value, '')}</div> : null}
          {String(meta || '').trim() ? <div>{renderMarkdownContent(String(meta))}</div> : null}
        </div>
      </div>
    );
  }).filter(Boolean);
  if (rows.length === 0) return null;
  return <div className="dashboard-bullet-list">{rows}</div>;
}

function renderDashboardSectionBody(section) {
  const kind = String(section?.kind || '').trim();
  if (kind === 'text_list') {
    return renderDashboardTextList(section?.items) || renderDashboardGenericItems(section?.items);
  }
  if (kind === 'bar_list') {
    const metricItems = normalizeDashboardMetricItems(section?.items).map((item) => ({ ...item, value: item.chartValue }));
    return renderDashboardBarList(metricItems) || renderDashboardGenericItems(section?.items);
  }
  if (kind === 'pie_list') {
    const metricItems = normalizeDashboardMetricItems(section?.items).map((item) => ({ ...item, value: item.chartValue }));
    return renderDashboardPieList(metricItems) || renderDashboardGenericItems(section?.items);
  }
  const lists = [
    renderDashboardBarList(section?.bar_list),
    renderDashboardPieList(section?.pie_list),
    renderDashboardTimeline(section?.timeline),
    renderDashboardBulletList(section?.bullet_list || section?.items),
    renderDashboardMatrix(section?.matrix),
    renderDashboardBubbleList(section?.bubble_list),
    renderDashboardGenericItems(section?.items),
  ].filter(Boolean);
  if (lists.length > 0) return lists;
  if (section?.content) return <div>{renderMarkdownContent(section.content)}</div>;
  if (section?.description) return <div>{renderMarkdownContent(section.description)}</div>;
  return null;
}

function renderDashboardSections(sections) {
  if (!Array.isArray(sections) || sections.length === 0) return null;
  return (
    <div className="dashboard-section-list">
      {sections.map((section, index) => (
        <section key={`dashboard-section-${index}`} className="dashboard-section">
          <div className="dashboard-section-head">
            <div>
              <strong>{dashboardText(section?.title || section?.label || `Раздел ${index + 1}`)}</strong>
              {section?.subtitle ? <div className="muted small">{dashboardText(section.subtitle, '')}</div> : null}
            </div>
            {section?.value ? <span className="muted small">{dashboardText(section.value)}</span> : null}
          </div>
          {section?.description ? <div>{renderMarkdownContent(section.description)}</div> : null}
          {renderDashboardSectionBody(section)}
        </section>
      ))}
    </div>
  );
}

function renderDashboardSources(sources) {
  if (!Array.isArray(sources) || sources.length === 0) return null;
  return (
    <details className="details-box">
      <summary>Источники · {sources.length}</summary>
      <div className="stack" style={{ marginTop: 10 }}>
        {sources.map((source, index) => {
          const href = source?.url;
          const label = dashboardText(source?.label || source?.title || href || `Источник ${index + 1}`);
          return (
            <div key={`dashboard-source-${index}`} className="table-row dashboard-post-row">
              <div>
                <strong>{label}</strong>
                {source?.snippet ? <div className="muted small">{dashboardText(source.snippet, '')}</div> : null}
              </div>
              {isSafeMarkdownHref(href) ? <a href={href} target="_blank" rel="noreferrer">Открыть</a> : <span className="muted small">Без ссылки</span>}
            </div>
          );
        })}
      </div>
    </details>
  );
}

function renderMessageDashboard(message, canSaveDashboard, onSaveDashboard) {
  const dashboard = message?.meta?.dashboard || null;
  const dashboardArtifact = message?.meta?.dashboard_artifact || null;
  if (!dashboard && !dashboardArtifact?.path) return null;
  return (
    <div className="dashboard-artifact">
      <div className="dashboard-artifact-head">
        <div className="eyebrow">Дашборд</div>
        <h3>{dashboardText(dashboard?.title || dashboard?.topic || messageDisplayText(message) || 'Собранный дашборд')}</h3>
        {dashboard?.subtitle ? <div className="muted small">{dashboardText(dashboard.subtitle, '')}</div> : null}
      </div>
      {dashboard?.summary ? <div>{renderMarkdownContent(dashboard.summary)}</div> : null}
      {renderDashboardSummaryCards(dashboard?.summary_cards)}
      {renderDashboardSections(dashboard?.sections)}
      {renderDashboardSources(dashboard?.sources)}
      {dashboardArtifact?.path ? <div className="dashboard-export-actions"><a href={`/api/files/open-local?path=${encodeURIComponent(dashboardArtifact.path)}`} target="_blank" rel="noreferrer">Открыть markdown</a>{canSaveDashboard ? <button className="ghost-btn ghost-btn-xs" type="button" onClick={() => onSaveDashboard(message)}>Сохранить как задачу</button> : null}</div> : null}
    </div>
  );
}


function renderClarificationCard(message) {
  const meta = message?.meta || {};
  const kind = message?.assistant_result_kind || message?.surface?.assistant_result_kind || '';
  if (kind !== 'clarification_needed') return null;
  const title = meta.clarification_title || meta.approval_title || 'Нужно уточнение';
  const prompt = meta.clarification_prompt || meta.approval_prompt || messageDisplayText(message);
  const options = Array.isArray(meta.clarification_options) ? meta.clarification_options.filter(Boolean) : [];
  const contract = meta.collection_contract && typeof meta.collection_contract === 'object' ? meta.collection_contract : null;
  const missingFields = Array.isArray(contract?.missing_fields) ? contract.missing_fields.filter(Boolean) : [];
  return (
    <div className="assistant-special-card clarification-card">
      <div className="eyebrow">Уточнение</div>
      <h3>{title}</h3>
      {prompt ? <div>{renderMarkdownContent(String(prompt))}</div> : null}
      {missingFields.length ? <div className="assistant-special-meta"><strong>Не хватает:</strong> {missingFields.join(', ')}</div> : null}
      {options.length ? <div className="clarification-options">{options.map((item, index) => <span key={`clarify-option-${index}`} className="assistant-action-chip">{item}</span>)}</div> : null}
    </div>
  );
}

function renderFileResultCard(message, onOpenAttachment) {
  const kind = message?.assistant_result_kind || message?.surface?.assistant_result_kind || '';
  const attachments = Array.isArray(message?.meta?.attachments) ? message.meta.attachments : [];
  const usedFiles = Array.isArray(message?.meta?.used_files) ? message.meta.used_files : [];
  if (!['file_result', 'artifact_result'].includes(kind) || attachments.length === 0) return null;
  return (
    <div className="assistant-special-card file-result-card">
      <div className="eyebrow">Файлы результата</div>
      <div className="assistant-file-list">
        {attachments.map((file, index) => {
          const label = file?.original_name || file?.stored_name || `Файл ${index + 1}`;
          const href = message.id && String(message.id).startsWith('temp-') === false ? filePreviewUrl(file, `/messages/${message.id}/attachments/${index}`) : '';
          const shortStatus = file?.file_surface?.file_kind === 'exported_answer' ? 'Экспорт готов' : 'Файл готов';
          return (
            <div key={`assistant-file-${index}`} className="assistant-file-row">
              <div>
                <strong>{label}</strong>
                <div className="muted small">{file?.mime_type || 'тип не указан'}{file?.size_bytes ? ` · ${formatBytes(file.size_bytes)}` : ''}</div>
                <div className="muted small profile-file-summary">{shortStatus}</div>
                {fileQualityStatus(file) ? <div className="assistant-quality-row"><span className={`status-chip ${fileQualityChipClass(file)}`}>{fileQualityLabel(file)}</span>{fileQualityDetail(file) ? <span className="muted small">{fileQualityDetail(file)}</span> : null}</div> : null}
              </div>
              <div className="profile-file-actions">
                {href ? <button className="ghost-btn ghost-btn-xs" type="button" onClick={() => onOpenAttachment ? onOpenAttachment({ ...file, download_url: href }) : api.openFile({ ...file, download_url: href })}>Открыть</button> : null}
              </div>
            </div>
          );
        })}
      </div>
      {usedFiles.length ? <details className="details-box" style={{ marginTop: 10 }}><summary>Какие файлы использованы в ответе</summary><div className="assistant-file-list" style={{ marginTop: 8 }}>{usedFiles.map((file, index) => <div key={`used-file-${index}`} className="assistant-file-row"><div><strong>{file?.original_name || file?.stored_name || `Файл ${index + 1}`}</strong><div className="muted small profile-file-summary">{fileSummaryText(file)}</div></div></div>)}</div></details> : null}
    </div>
  );
}

function renderStructuredResultCard(message) {
  const kind = message?.assistant_result_kind || message?.surface?.assistant_result_kind || '';
  const structured = message?.meta?.structured_result && typeof message.meta.structured_result === 'object' ? message.meta.structured_result : null;
  const contract = message?.meta?.collection_contract && typeof message.meta.collection_contract === 'object' ? message.meta.collection_contract : null;
  const payload = structured || contract;
  if (!(kind === 'structured_result' && payload)) return null;
  const rows = [];
  const preferredOrder = ['subject', 'source_kind', 'output_format', 'scope', 'period', 'request_text'];
  preferredOrder.forEach((key) => {
    const value = payload?.[key];
    if (value === undefined || value === null || String(value).trim() === '') return;
    rows.push([key, Array.isArray(value) ? value.join(', ') : String(value)]);
  });
  Object.entries(payload || {}).forEach(([key, value]) => {
    if (preferredOrder.includes(key) || key === 'missing_fields') return;
    if (value === undefined || value === null) return;
    const normalized = Array.isArray(value) ? value.join(', ') : typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value);
    if (!String(normalized).trim()) return;
    rows.push([key, normalized]);
  });
  return (
    <div className="assistant-special-card structured-result-card">
      <div className="eyebrow">Структурированный результат</div>
      <h3>{contract ? 'Контракт сбора данных' : 'Структурированный ответ'}</h3>
      <div className="assistant-structured-grid">
        {rows.map(([key, value], index) => <div key={`structured-row-${index}`} className="assistant-structured-row"><span>{key}</span><strong>{value}</strong></div>)}
      </div>
    </div>
  );
}

function renderResearchResultCard(message) {
  const kind = message?.assistant_result_kind || message?.surface?.assistant_result_kind || '';
  const research = message?.meta?.research_result && typeof message.meta.research_result === 'object'
    ? message.meta.research_result
    : (message?.meta?.structured_result && typeof message.meta.structured_result === 'object' ? message.meta.structured_result : null);
  if (!(kind === 'research_result' && research)) return null;
  const findings = Array.isArray(research.findings) ? research.findings.filter(Boolean) : [];
  const evidence = Array.isArray(research.evidence) ? research.evidence.filter(Boolean) : [];
  const caveats = Array.isArray(research.caveats) ? research.caveats.filter(Boolean) : [];
  const summary = typeof research.summary === 'string' ? research.summary.trim() : '';
  return (
    <div className="assistant-special-card structured-result-card">
      <div className="eyebrow">Исследование</div>
      <h3>Результат исследования</h3>
      {summary ? <div>{renderMarkdownContent(summary)}</div> : null}
      {findings.length ? <div className="assistant-structured-row"><span>Что найдено</span><strong>{findings.join(' · ')}</strong></div> : null}
      {evidence.length ? <div className="assistant-structured-row"><span>Подтверждения</span><strong>{evidence.join(' · ')}</strong></div> : null}
      {caveats.length ? <div className="assistant-structured-row"><span>Ограничения</span><strong>{caveats.join(' · ')}</strong></div> : null}
    </div>
  );
}

function renderTableResultCard(message) {
  const kind = message?.assistant_result_kind || message?.surface?.assistant_result_kind || '';
  const table = message?.meta?.table_result && typeof message.meta.table_result === 'object'
    ? message.meta.table_result
    : (message?.meta?.structured_result && typeof message.meta.structured_result === 'object' ? message.meta.structured_result : null);
  if (!(kind === 'table_result' && table)) return null;
  const columns = Array.isArray(table.columns) ? table.columns : [];
  const rows = Array.isArray(table.rows) ? table.rows.slice(0, 5) : [];
  const summary = typeof table.summary === 'string' ? table.summary.trim() : '';
  return (
    <div className="assistant-special-card structured-result-card">
      <div className="eyebrow">Таблица</div>
      <h3>Табличный результат</h3>
      {summary ? <div>{renderMarkdownContent(summary)}</div> : null}
      {columns.length ? <div className="assistant-structured-grid">{columns.map((item, index) => <div key={`table-col-${index}`} className="assistant-structured-row"><span>Колонка</span><strong>{String(item)}</strong></div>)}</div> : null}
      {rows.length ? <details className="details-box" style={{ marginTop: 10 }}><summary>Показать первые строки</summary><div className="assistant-structured-grid" style={{ marginTop: 8 }}>{rows.map((row, index) => <div key={`table-row-${index}`} className="assistant-structured-row"><span>Строка {index + 1}</span><strong>{Array.isArray(row) ? row.join(' | ') : String(row)}</strong></div>)}</div></details> : null}
    </div>
  );
}

function renderRecurringSummary(message, onOpenAttachment) {
  const recurring = message?.meta?.recurring_summary || null;
  const surface = message?.surface || {};
  if (!recurring || message?.role !== 'assistant') return null;
  const attachments = Array.isArray(message?.meta?.attachments) ? message.meta.attachments : [];
  const status = recurring.status || surface.status || 'completed';
  const rawSummary = String(recurring.summary || '').trim();
  const detail = String(recurring.status_detail || '').trim();
  const deliverySummary = String(recurring.delivery_summary || '').trim();
  const resultKind = recurring.result_kind || 'text';
  const firstFile = attachments[0] || null;
  const hasFileResult = attachments.length > 0 || resultKind === 'file';
  if (!hasFileResult && status === 'running') return null;
  const bodyText = buildRecurringBodyText(message, recurring);
  const digestBody = looksLikeDigestText(bodyText) ? bodyText : buildDigestCardText(message, recurring);
  const isDigest = looksLikeDigestText(digestBody);
  const hasRichBody = looksLikeRichRecurringBody(bodyText);
  const compactSummary = isDigest
    ? 'Дайджест подготовлен'
    : (hasFileResult
      ? (stripAttachedFileNote(rawSummary) || (firstFile?.original_name || firstFile?.stored_name ? `Файл готов: ${firstFile.original_name || firstFile.stored_name}` : 'Файл готов'))
      : stripAttachedFileNote(rawSummary));
  const statusText = status === 'running' ? 'В обработке' : humanizeSurfaceStatus(status);
  const detailLabel = hasFileResult ? 'Показать текстовый preview' : 'Показать детали';
  if (isDigest) {
    return (
      <div className="assistant-special-card digest-result-card" style={{ marginTop: 12 }}>
        <div className="eyebrow">HERMES</div>
        <div style={{ marginTop: 4 }}>{renderMarkdownContent(digestBody)}</div>
        {attachments.length > 0 ? (
          <div className="assistant-file-block" style={{ marginTop: 14 }}>
            <div className="eyebrow">Файлы результата</div>
            <div className="assistant-file-list" style={{ marginTop: 10 }}>
              {attachments.map((file, index) => {
                const label = file?.original_name || file?.stored_name || `Файл ${index + 1}`;
                const href = message.id && String(message.id).startsWith('temp-') === false ? filePreviewUrl(file, `/messages/${message.id}/attachments/${index}`) : '';
                return (
                  <div key={`recurring-file-${index}`} className="assistant-file-row">
                    <div>
                      <strong>{label}</strong>
                      <div className="muted small">{[file?.mime_type || '', formatBytes(file?.size_bytes)].filter(Boolean).join(' · ')}</div>
                      <div className="muted small">Файл готов</div>
                      {fileQualityStatus(file) ? <div className="assistant-quality-row"><span className={`status-chip ${fileQualityChipClass(file)}`}>{fileQualityLabel(file)}</span>{fileQualityDetail(file) ? <span className="muted small">{fileQualityDetail(file)}</span> : null}</div> : null}
                    </div>
                    {href ? <button className="ghost-btn ghost-btn-xs" type="button" onClick={() => onOpenAttachment ? onOpenAttachment({ ...file, download_url: href }) : api.openFile({ ...file, download_url: href })}>Открыть</button> : null}
                  </div>
                );
})}
            </div>
          </div>
        ) : null}
      </div>
    );
  }
  if (hasRichBody) {
    return (
      <div className="assistant-special-card recurring-rich-card" style={{ marginTop: 12 }}>
        <div className="job-summary-head">
          <div>
            <div className="eyebrow">HERMES</div>
            <strong>{compactSummary || 'Результат подготовлен'}</strong>
          </div>
          <span className={`status-chip ${runStatusChipClass(status)}`}>{statusText}</span>
        </div>
        {deliverySummary ? <div className="muted small">{deliverySummary}</div> : null}
        <div>{renderMarkdownContent(bodyText)}</div>
        {attachments.length > 0 ? (
          <div className="assistant-file-block" style={{ marginTop: 14 }}>
            <div className="eyebrow">Файлы результата</div>
            <div className="assistant-file-list" style={{ marginTop: 10 }}>
              {attachments.map((file, index) => {
                const label = file?.original_name || file?.stored_name || `Файл ${index + 1}`;
                const href = message.id && String(message.id).startsWith('temp-') === false ? filePreviewUrl(file, `/messages/${message.id}/attachments/${index}`) : '';
                return (
                  <div key={`recurring-rich-file-${index}`} className="assistant-file-row">
                    <div>
                      <strong>{label}</strong>
                      <div className="muted small">{[file?.mime_type || '', formatBytes(file?.size_bytes)].filter(Boolean).join(' · ')}</div>
                      <div className="muted small">Файл готов</div>
                    </div>
                    {href ? <button className="ghost-btn ghost-btn-xs" type="button" onClick={() => onOpenAttachment ? onOpenAttachment({ ...file, download_url: href }) : api.openFile({ ...file, download_url: href })}>Открыть</button> : null}
                  </div>
                );
              })}
            </div>
          </div>
        ) : null}
      </div>
    );
  }
  return (
    <div className="job-summary-card" style={{ marginTop: 12 }}>
      <div className="job-summary-head">
        <div>
          <div className="eyebrow">Результат задачи</div>
          <strong>{compactSummary || 'Результат подготовлен'}</strong>
        </div>
        <span className={`status-chip ${runStatusChipClass(status)}`}>{statusText}</span>
      </div>
      {deliverySummary ? <div className="muted small" style={{ marginTop: 6 }}>{deliverySummary}</div> : null}
      {attachments.length > 0 ? (
        <div className="assistant-file-list" style={{ marginTop: 10 }}>
          {attachments.map((file, index) => {
            const label = file?.original_name || file?.stored_name || `Файл ${index + 1}`;
            const href = message.id && String(message.id).startsWith('temp-') === false ? filePreviewUrl(file, `/messages/${message.id}/attachments/${index}`) : '';
            return (
              <div key={`recurring-file-${index}`} className="assistant-file-row">
                <div>
                  <strong>{label}</strong>
                  <div className="muted small">{formatBytes(file?.size_bytes)}</div>
                </div>
                {href ? <button className="ghost-btn ghost-btn-xs" type="button" onClick={() => onOpenAttachment ? onOpenAttachment({ ...file, download_url: href }) : api.openFile({ ...file, download_url: href })}>Открыть</button> : null}
              </div>
            );
          })}
        </div>
      ) : null}
      {!isDigest && detail && stripAttachedFileNote(detail) !== compactSummary ? (
        <details className="details-box" style={{ marginTop: 10 }}>
          <summary>{detailLabel}</summary>
          <div style={{ marginTop: 8 }}>{renderMarkdownContent(stripAttachedFileNote(detail))}</div>
        </details>
      ) : null}
    </div>
  );
}


function MessageBubble({ message, bootstrap, onSaveDashboard, onOpenAttachment, onExportMessage }) {
  const side = message.role === 'user' ? 'user' : 'assistant';
  const attachments = message.meta?.attachments || [];
  const surface = message.surface || {};
  const isPending = Boolean(message.meta?.pending) || surface.status === 'running';
  const isError = Boolean(message.meta?.error) || surface.status === 'failed';
  const dashboardArtifact = message?.meta?.dashboard_artifact || null;
  const canSaveDashboard = Boolean(onSaveDashboard && dashboardArtifact?.path && message.role === 'assistant');
  const recurringSummary = renderRecurringSummary(message, onOpenAttachment);
  const assistantContractStrip = renderAssistantContractStrip(message, canSaveDashboard, onSaveDashboard, onExportMessage);
  const clarificationCard = renderClarificationCard(message);
  const fileResultCard = renderFileResultCard(message, onOpenAttachment);
  const structuredResultCard = renderStructuredResultCard(message);
  const researchResultCard = renderResearchResultCard(message);
  const tableResultCard = renderTableResultCard(message);
  const suppressPlainAttachments = Boolean(fileResultCard || recurringSummary);
  const hasRecurringSummary = Boolean(message?.meta?.recurring_summary);
  const contentText = hasRecurringSummary ? '' : messageDisplayText(message);
  const renderContentAsMarkdown = message.role === 'assistant' ? Boolean(contentText) : looksLikeMarkdownMessage(contentText);
  const isKpiThread = String(message?.meta?.thread_title || '').trim().toLowerCase() === 'kpi';
  return (
    <article className={`message-bubble ${side} ${isPending ? 'pending' : ''} ${isError ? 'error' : ''}`}>
      <div className="message-role">{message.role === 'user' ? 'Вы' : 'Hermes'}</div>
      {contentText ? <div className="message-content">{renderContentAsMarkdown ? renderMarkdownContent(contentText, { adaptiveWideTables: isKpiThread }) : renderMarkdownParagraph(contentText, `plain-${message.id || message.created_at || 'message'}`)}</div> : null}
      {assistantContractStrip}
      {clarificationCard}
      {fileResultCard}
      {researchResultCard}
      {tableResultCard}
      {structuredResultCard}
      {recurringSummary}
      {message.role === 'assistant' ? renderMessageDashboard(message, canSaveDashboard, onSaveDashboard) : null}
      {!suppressPlainAttachments && attachments.length > 0 && <ul className="attachment-list">{attachments.map((file, i) => <li key={`${file.original_name || file.stored_name || 'file'}-${i}`}>{message.id && String(message.id).startsWith('temp-') === false ? <button className="attachment-link-btn" type="button" onClick={() => onOpenAttachment ? onOpenAttachment({ ...file, download_url: filePreviewUrl(file, `/messages/${message.id}/attachments/${i}`) }) : api.openFile({ ...file, download_url: filePreviewUrl(file, `/messages/${message.id}/attachments/${i}`) })}>{file.original_name || file.stored_name || `Файл ${i + 1}`}</button> : <span>{file.original_name || file.stored_name || `Файл ${i + 1}`}</span>}</li>)}</ul>}
      <div className="message-meta">{isPending ? 'Hermes · обрабатываю' : isError ? 'Ошибка обработки' : formatTs(message.created_at)}</div>
    </article>
  );
}

function renderThreadFileRow(file, index, { onOpenUserFile, onToggleExistingFile, onDeleteFile, composerExistingFiles = [], compact = false } = {}) {
  const fileKey = file.id ? `thread-user-${file.id}` : `thread-msg-${file.source_message_id || 'x'}-${index}`;
  const reusable = Boolean(file.id);
  const checked = reusable && composerExistingFiles.some((item) => Number(item.id) === Number(file.id));
  return (
    <div className={`table-row profile-file-row thread-file-row ${compact ? 'compact' : ''}`} key={fileKey}>
      <div className="profile-file-main">
        <div className="file-card-head">
          <strong>{file.original_name || file.stored_name || `Файл ${index + 1}`}</strong>
          <span className="muted small">{file.thread_file_role === 'assistant_result' ? 'Результат' : file.thread_file_role === 'message_attachment' ? 'Вложение' : 'Файл'}</span>
        </div>
        <div className="muted small">{formatBytes(file.size_bytes)}{file.created_at ? ` · ${formatTs(file.created_at)}` : ''}</div>
        <div className="muted small profile-file-summary">{humanizeExtractionStatus(file)} · {humanizePreviewStatus(file)}</div>
        {fileQualityStatus(file) ? <div className="assistant-quality-row"><span className={`status-chip ${fileQualityChipClass(file)}`}>{fileQualityLabel(file)}</span>{fileQualityDetail(file) ? <span className="muted small">{fileQualityDetail(file)}</span> : null}</div> : null}
        <div className="muted small profile-file-summary">{file.preview_summary || fileSummaryText(file)}</div>
      </div>
      <div className="profile-file-actions thread-file-actions">
        <button className="ghost-btn ghost-btn-xs" onClick={() => onOpenUserFile(file)} type="button">Открыть</button>
        {reusable ? <button className={`ghost-btn ghost-btn-xs ${checked ? 'active' : ''}`} onClick={() => onToggleExistingFile(file)} type="button">{checked ? 'В контексте' : 'В контекст'}</button> : null}
        {onDeleteFile ? <button className="ghost-btn ghost-btn-xs" onClick={() => onDeleteFile(file)} type="button">Удалить</button> : null}
      </div>
    </div>
  );
}

function ThreadFilesPanel({ threadFiles, activeThreadTitle, onOpenUserFile, onToggleExistingFile, onDeleteFile, composerExistingFiles = [] }) {
  const files = Array.isArray(threadFiles) ? threadFiles : [];
  return (
    <section className="panel-card compact-card stack thread-files-panel">
      <div className="head-actions">
        <div>
          <h4>Файлы этого диалога</h4>
          <div className="muted small">{activeThreadTitle || 'Текущий чат'} · всего {files.length}</div>
        </div>
      </div>
      {files.length === 0 ? <div className="muted">В этом диалоге пока нет файлов и артефактов.</div> : <div className="table-list profile-files-list">{files.map((file, index) => renderThreadFileRow(file, index, { onOpenUserFile, onToggleExistingFile, onDeleteFile, composerExistingFiles, compact: true }))}</div>}
    </section>
  );
}

function LoginScreen({ serviceInfo, setupRequired, loginForm, setupForm, error, loading, onLoginChange, onSetupChange, onLogin, onSetup }) {
  return (
    <div className="auth-layout">
      <section className="auth-card hero-card auth-hero-card">
        <span className="eyebrow">Hermes Web</span>
        <h1>Единое рабочее пространство</h1>
        <p className="auth-hero-lead">Чаты, задачи, файлы и персональные настройки — в одном понятном локальном контуре.</p>
        <ul className="feature-list auth-feature-list">
          <li>Переписка и материалы собраны в одном рабочем окне.</li>
          <li>Профиль помогает настроить стиль и контекст ответов.</li>
          <li>Задачи и история работы остаются под рукой без лишних переходов.</li>
        </ul>
        <div className="service-note auth-service-note"><strong>Режим:</strong> {serviceInfo?.mode || '—'}</div>
      </section>
      <section className="auth-card auth-form-card">
        <div className="auth-card-head">
          <h2>{setupRequired ? 'Первичный запуск' : 'Вход'}</h2>
          <p className="muted auth-form-note">{setupRequired ? 'Создай первый аккаунт и задай доступ к рабочему контуру.' : 'Войди, чтобы продолжить работу с чатами, задачами и профилем.'}</p>
        </div>
        {error ? <div className="banner error">{error}</div> : null}
        {setupRequired ? (
          <form className="stack" onSubmit={onSetup}>
            <label>Имя администратора<input name="name" value={setupForm.name} onChange={onSetupChange} /></label>
            <label>Email<input name="email" type="email" value={setupForm.email} onChange={onSetupChange} /></label>
            <label>Пароль<input name="password" type="password" value={setupForm.password} onChange={onSetupChange} /></label>
            <button className="primary-btn" disabled={loading} type="submit">Создать первого администратора</button>
          </form>
        ) : (
          <form className="stack" onSubmit={onLogin}>
            <label>Email<input name="email" type="email" value={loginForm.email} onChange={onLoginChange} /></label>
            <label>Пароль<input name="password" type="password" value={loginForm.password} onChange={onLoginChange} /></label>
            <button className="primary-btn" disabled={loading} type="submit">Войти</button>
          </form>
        )}
      </section>
    </div>
  );
}

function Sidebar({ appState, onNavigate, onCreateThread, onSelectThread, onOpenThreadsModal, onLogout }) {
  const activeThreads = appState.threads.filter((thread) => !thread.archived);
  const visibleThreads = activeThreads.slice(0, 8);
  const visibleScreens = SCREENS.filter((screen) => !(screen === 'admin' && appState.user?.role !== 'admin'));
  return (
    <aside className="sidebar">
      <div>
        <div className="eyebrow">Hermes Web</div>
        <h2>{appState.user?.name || 'Пользователь'}</h2>
        <div className="muted">{appState.user?.email}</div>
      </div>
      <div className="sidebar-nav-toolbar">
        <nav className="nav-stack">
          {visibleScreens.map((screen) => <button key={screen} type="button" className={`nav-btn nav-btn-${screen} ${appState.screen === screen ? 'active' : ''}`} onClick={() => onNavigate(screen)}>{screen === 'chat' ? 'Чаты' : screen === 'profile' ? 'Профиль' : screen === 'jobs' ? 'Задачи' : 'Управление'}</button>)}
        </nav>
        <div className="sidebar-footer">
          <button className="ghost-btn sidebar-logout-btn" onClick={onLogout} type="button">Выйти</button>
        </div>
      </div>
      <div className="sidebar-actions" aria-label="Быстрые действия по чатам">
        <button className="primary-btn" onClick={onCreateThread} type="button">+ Новый чат</button>
        <button className="ghost-btn" onClick={onOpenThreadsModal} type="button">Все чаты</button>
      </div>
      <div className="thread-list">
        {visibleThreads.map((thread) => (
          <button key={thread.id} type="button" className={`thread-item ${String(thread.id) === String(appState.activeThreadId) ? 'active' : ''} ${threadHasUnread(thread) ? 'unread' : ''}`} onClick={() => onSelectThread(thread.id)}>
            <div className="thread-item-top"><div className="thread-title-stack"><strong>{thread.title || 'Без названия'}</strong>{thread.archived ? <span className="thread-state-chip">В архиве</span> : null}</div><span className="thread-date">{formatTsCompact(threadLastActivity(thread))}</span></div>
            <div className="thread-item-bottom"><span>{thread.preview || 'Без превью'}</span>{threadHasUnread(thread) ? <span className="thread-unread-dot" aria-label="Непрочитано" /> : null}</div>
          </button>
        ))}
        {activeThreads.length === 0 ? <div className="empty-box">Активных чатов пока нет</div> : null}
      </div>
    </aside>
  );
}

function ChatScreen({ appState, composerText, composerFiles, composerExistingFiles, requestPolicyDraft, sending, onComposerChange, onComposerKeyDown, onFileChange, onToggleExistingFile, onOpenUserFile, onDeleteFile, onApplyStarterPrompt, onRequestPolicyChange, onSend, onRenameThread, onArchiveThread, onDeleteThread, onDismissWelcome, onSaveDashboard, onOpenAttachment, onExportMessage }) {
  const activeThread = useMemo(() => appState.threads.find((thread) => String(thread.id) === String(appState.activeThreadId)) || null, [appState.activeThreadId, appState.threads]);
  const messagesRef = useRef(null);
  const composerTextareaRef = useRef(null);
  const shouldStickToBottomRef = useRef(true);
  const previousThreadIdRef = useRef(null);
  const previousMessageCountRef = useRef(0);
  const previousMessageTailRef = useRef('');
  const warningText = String(appState.bootstrap?.chat_notice?.text || '').trim();
  const warningVisible = Boolean(appState.bootstrap?.chat_notice?.enabled && warningText);
  const showWelcome = appState.messages.length === 0 && !appState.chatWelcomeDismissed;
  const starterPrompts = starterPromptsFromBootstrap(appState.bootstrap).slice(0, 4);
  const [paramsOpen, setParamsOpen] = useState(false);
  const [filesOpen, setFilesOpen] = useState(false);
  const [threadFilesOpen, setThreadFilesOpen] = useState(false);
  const selectedSourceCount = requestPolicyDraft.selected_source_ids?.length || 0;
  const selectedFileCount = composerFiles.length + composerExistingFiles.length;
  const selectedModeDescription = (appState.bootstrap?.data_policy?.processing_policy?.mode_options || []).find((item) => item.value === requestPolicyDraft.search_mode_override)?.description || 'Режим определяет, можно ли выходить во внешний контур и в каком порядке выбирать источники.';
  const modelSelector = appState.bootstrap?.llm_routing?.selector || { options: [] };

  function messageTailKey(messages) {
    const last = messages[messages.length - 1];
    if (!last) return 'empty';
    return [
      last.id ?? 'no-id',
      last.created_at ?? 'no-created',
      last.updated_at ?? 'no-updated',
      last.role ?? 'no-role',
      last.meta?.pending ? 'pending' : 'ready',
      String(last.content || '').slice(0, 120),
    ].join('::');
  }

  function isNearBottom(node, threshold = 48) {
    return node.scrollHeight - node.scrollTop - node.clientHeight <= threshold;
  }

  function scheduleScrollToBottom(node) {
    if (!node) return () => {};
    const rafIds = [];
    const timeoutIds = [];
    const apply = () => {
      node.scrollTop = node.scrollHeight;
      shouldStickToBottomRef.current = true;
    };
    apply();
    rafIds.push(window.requestAnimationFrame(apply));
    rafIds.push(window.requestAnimationFrame(() => {
      rafIds.push(window.requestAnimationFrame(apply));
    }));
    timeoutIds.push(window.setTimeout(apply, 0));
    timeoutIds.push(window.setTimeout(apply, 80));
    timeoutIds.push(window.setTimeout(apply, 220));
    return () => {
      rafIds.forEach((id) => window.cancelAnimationFrame(id));
      timeoutIds.forEach((id) => window.clearTimeout(id));
    };
  }

  useEffect(() => {
    const node = messagesRef.current;
    if (!node || showWelcome) return undefined;
    const currentThreadId = appState.activeThreadId == null ? null : String(appState.activeThreadId);
    const currentMessageCount = appState.messages.length;
    const currentMessageTail = messageTailKey(appState.messages);
    const threadChanged = currentThreadId !== previousThreadIdRef.current;
    const messagesChanged = currentMessageCount !== previousMessageCountRef.current || currentMessageTail !== previousMessageTailRef.current;
    let cleanup = () => {};
    if (threadChanged || (messagesChanged && shouldStickToBottomRef.current)) {
      cleanup = scheduleScrollToBottom(node);
    }
    previousThreadIdRef.current = currentThreadId;
    previousMessageCountRef.current = currentMessageCount;
    previousMessageTailRef.current = currentMessageTail;
    return cleanup;
  }, [appState.activeThreadId, appState.messages, showWelcome]);

  useEffect(() => {
    const node = messagesRef.current;
    if (!node) return undefined;
    const handleScroll = () => {
      shouldStickToBottomRef.current = isNearBottom(node);
    };
    handleScroll();
    node.addEventListener('scroll', handleScroll, { passive: true });
    return () => node.removeEventListener('scroll', handleScroll);
  }, [appState.activeThreadId, showWelcome]);

  useEffect(() => {
    if (!composerTextareaRef.current) return;
    composerTextareaRef.current.style.height = 'auto';
    composerTextareaRef.current.style.height = `${Math.min(composerTextareaRef.current.scrollHeight, 240)}px`;
  }, [composerText]);

  useEffect(() => {
    setThreadFilesOpen(false);
  }, [appState.activeThreadId]);

  return (
    <div className="screen-shell chat-screen">
      <header className="section-head">
        <div className="chat-header-main">
          <div className="chat-header-copy">
            <div className="eyebrow">Чаты</div>
            <p className="muted small chat-section-copy">Рабочий раздел для диалога, файлов и обсуждения.</p>
            <div className="chat-title-row">
              <h1>{compactThreadTitle(activeThread)}</h1>
            </div>
            <div className="head-actions chat-header-actions">
              {activeThread ? <button className={`ghost-btn ghost-btn-xs ${threadFilesOpen ? 'active' : ''}`} onClick={() => setThreadFilesOpen((prev) => !prev)} type="button">Файлы{appState.threadFiles.length ? ` · ${appState.threadFiles.length}` : ''}</button> : null}
              {activeThread ? <button className="ghost-btn ghost-btn-xs" onClick={onRenameThread} type="button">Переименовать</button> : null}
              {activeThread ? <button className="ghost-btn ghost-btn-xs" onClick={onArchiveThread} type="button">{activeThread.archived ? 'Вернуть из архива' : 'В архив'}</button> : null}
              {activeThread ? <button className="ghost-btn ghost-btn-xs" onClick={onDeleteThread} type="button">Удалить</button> : null}
            </div>
          </div>
          <div className="chat-header-meta">
            {activeThread?.archived ? <span className="status-chip">В архиве</span> : null}
            {sending ? <span className="status-chip warn">Hermes обрабатывает сообщение…</span> : null}
          </div>
        </div>
      </header>
      {warningVisible && !showWelcome ? <div className="chat-guide-banner compact"><strong>Внимание</strong><span className="inline-label-separator">—</span><span>{warningText}</span></div> : null}
      <div className="chat-workspace">
        <section className="chat-main-panel">
          <div className="chat-stage">
            <section className="messages-panel" ref={messagesRef}>
            {showWelcome ? (
              <div className="empty-box large chat-welcome-card">
                <div className="eyebrow">Новый чат</div>
                <h3>С чего начать</h3>
                <p>Напишите вопрос своими словами или выберите готовую стартовую формулировку. При необходимости можно сразу подключить уже загруженные материалы из профиля.</p>
                {starterPrompts.length ? <div className="starter-prompts-grid">{starterPrompts.map((prompt) => <button key={prompt} className="starter-prompt-btn" type="button" onClick={() => onApplyStarterPrompt(prompt)}>{prompt}</button>)}<button className="starter-prompt-btn starter-prompt-btn-accent" onClick={onDismissWelcome} type="button">Написать сообщение</button></div> : <div className="head-actions"><button className="primary-btn" onClick={onDismissWelcome} type="button">Написать сообщение</button></div>}
                {warningVisible ? <div className="chat-inline-warning"><strong>Внимание</strong><span className="inline-label-separator">—</span><span>{warningText}</span></div> : null}
              </div>
            ) : <>
              {appState.messages.map((message, index) => <MessageBubble key={message.id || `${message.created_at}-${index}`} message={message} bootstrap={appState.bootstrap} onSaveDashboard={onSaveDashboard} onOpenAttachment={onOpenAttachment} onExportMessage={onExportMessage} />)}
              {appState.messages.length <= 1 ? <div className="chat-low-activity-hint"><strong>Диалог только начинается.</strong><span>Сформулируйте следующий шаг ниже, чтобы собрать контекст и продолжить работу в этом чате.</span></div> : null}
            </>}
          </section>
            {threadFilesOpen ? <aside className="thread-files-drawer"><ThreadFilesPanel threadFiles={appState.threadFiles} activeThreadTitle={activeThread?.title} onOpenUserFile={onOpenUserFile} onToggleExistingFile={onToggleExistingFile} onDeleteFile={onDeleteFile} composerExistingFiles={composerExistingFiles} /></aside> : null}
          </div>
        </section>
        <aside className="chat-sidepanel">
          <form className="composer sticky-composer chat-composer-card" onSubmit={onSend}>
            <div className="composer-shell">
              <div className="composer-main">
                <label className="sr-only" htmlFor="chat-composer-textarea">Сообщение</label>
                <textarea id="chat-composer-textarea" ref={composerTextareaRef} className="composer-textarea" value={composerText} onChange={onComposerChange} onKeyDown={onComposerKeyDown} placeholder="Сообщение" rows={1} />
                {selectedFileCount ? <div className="composer-selection-summary muted small">Файлы: {composerFiles.length ? `новых ${composerFiles.length}` : ''}{composerFiles.length && composerExistingFiles.length ? ' · ' : ''}{composerExistingFiles.length ? `из профиля ${composerExistingFiles.length}` : ''}</div> : null}
              </div>
              <div className="composer-toolbar">
                <div className="composer-popover-anchor">
                  <button className={`ghost-btn composer-tool-btn ${filesOpen ? 'active' : ''}`} onClick={() => { setFilesOpen((prev) => !prev); setParamsOpen(false); }} type="button">Файлы{selectedFileCount ? ` · ${selectedFileCount}` : ''}</button>
                  {filesOpen ? <div className={`composer-popover composer-files-popover ${appState.userFiles.length ? 'with-profile-list' : ''}`}>
                    <div className="composer-popover-title">Файлы</div>
                    <label className="file-label file-label-inline"><input multiple onChange={onFileChange} type="file" />Новый файл</label>
                    {composerFiles.length > 0 ? <div className="muted small">Новые файлы: {composerFiles.map((file) => file.name).join(', ')}</div> : null}
                    <details className="details-box context-disclosure" open={composerExistingFiles.length > 0}>
                      <summary>Выбрать из профиля {composerExistingFiles.length > 0 ? `· выбрано ${composerExistingFiles.length}` : ''}</summary>
                      <div className="existing-files-block pinned-existing-files">
                        <div className="existing-file-grid existing-file-list-compact">
                          {appState.userFiles.map((file) => {
                            const checked = composerExistingFiles.some((item) => Number(item.id) === Number(file.id));
                            return <label className={`existing-file-card file-row ${checked ? 'selected' : ''}`} key={file.id}><input checked={checked} onChange={() => onToggleExistingFile(file)} type="checkbox" /><div><div className="file-card-head"><strong>{file.original_name}</strong><button className="ghost-btn ghost-btn-xs" onClick={(event) => { event.preventDefault(); event.stopPropagation(); onOpenUserFile(file); }} type="button">Открыть</button></div><div className="muted small">{formatBytes(file.size_bytes)}</div><div className="muted small">{fileStatusMeta(file)}</div></div></label>;
                          })}
                          {appState.userFiles.length === 0 ? <div className="muted small">В профиле пока нет файлов.</div> : null}
                        </div>
                      </div>
                    </details>
                  </div> : null}
                </div>
                <div className="composer-popover-anchor params-anchor">
                  <button className={`ghost-btn composer-tool-btn ${paramsOpen ? 'active' : ''}`} onClick={() => { setParamsOpen((prev) => !prev); setFilesOpen(false); }} type="button">Параметры{selectedSourceCount ? ` · ${selectedSourceCount}` : ''}</button>
                  {paramsOpen ? <div className="composer-popover composer-params-popover" role="dialog" aria-modal="false">
                    <div className="composer-popover-title">Параметры</div>
                    <div className="composer-params-stack">
                      <div className="composer-params-section">
                        <div className="composer-params-section-head"><span>Модель</span></div>
                        <label className="composer-compact-field">Модель<select value={requestPolicyDraft.model_preference === 'auto' ? 'owl_alpha' : (requestPolicyDraft.model_preference || 'owl_alpha')} onChange={(e) => onRequestPolicyChange('model_preference', e.target.value)}>{(modelSelector.options || []).filter((item) => item.value === 'owl_alpha' || item.value === 'deepseek_r1').map((item) => <option key={item.value} value={item.value} disabled={item.enabled === false}>{item.value === 'deepseek_r1' ? 'Глубокий анализ' : 'Обычная модель'}</option>)}</select></label>
                        <div className="muted small">Лимиты глубокого анализа: вам осталось {appState.bootstrap?.llm_routing?.usage_today?.user_remaining_requests ?? '—'} из {appState.bootstrap?.llm_routing?.limits?.per_user_requests_per_day ?? '—'}, глобально {appState.bootstrap?.llm_routing?.usage_today?.remaining_requests ?? '—'} из {appState.bootstrap?.llm_routing?.limits?.global_requests_per_day ?? '—'}.</div>
                      </div>
                      <div className="composer-params-section">
                        <div className="composer-params-section-head"><span>Политика источников</span></div>
                        <label className="composer-compact-field">Политика источников<select value={requestPolicyDraft.search_mode_override || ''} onChange={(e) => onRequestPolicyChange('search_mode_override', e.target.value)}>{(appState.bootstrap?.data_policy?.processing_policy?.mode_options || []).map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>
                        <div className="muted small">{selectedModeDescription}</div>
                      </div>
                    </div>
                  </div> : null}
                </div>
                <button className="primary-btn composer-send-btn" disabled={sending} type="submit">↑</button>
              </div>
            </div>
          </form>
        </aside>
      </div>
    </div>
  );
}

function ProfileScreen({ user, profileSummary, userFiles, threadFiles, activeThreadTitle, profileForm, passwordForm, profileSection, profileFileQuery, profileFileType, bootstrap, onSectionChange, onProfileFileFilterChange, onProfileChange, onPasswordChange, onSaveProfile, onChangePassword, onOpenUserFile, onDeleteFile, onToggleExistingFile, composerExistingFiles = [] }) {
  const files = useMemo(() => filteredUserFiles(userFiles, { query: profileFileQuery, type: profileFileType }), [userFiles, profileFileQuery, profileFileType]);
  const toneOptions = useMemo(() => referenceOptions(bootstrap, 'assistant_tones', profileForm.tone), [bootstrap, profileForm.tone]);
  const answerDepthOptions = useMemo(() => referenceOptions(bootstrap, 'assistant_answer_depths', profileForm.answer_depth), [bootstrap, profileForm.answer_depth]);
  const interactionModeOptions = useMemo(() => referenceOptions(bootstrap, 'assistant_interaction_modes', profileForm.interaction_mode), [bootstrap, profileForm.interaction_mode]);
  const totalFiles = userFiles.length;
  const filesReady = userFiles.filter((file) => file.text_extracted).length;
  return (
    <div className="screen-shell scrollable">
      <header className="section-head compact mobile-chatlike-head"><div><div className="eyebrow">Профиль</div><h1>Профиль пользователя</h1><p className="muted small screen-section-copy">Личные настройки, стиль ответов и пользовательские файлы.</p></div></header>
      <div className="head-actions profile-tabs mobile-chatlike-tabs">{PROFILE_SECTIONS.map((section) => <button key={section} className={`ghost-btn ${profileSection === section ? 'active' : ''}`} type="button" onClick={() => onSectionChange(section)}>{section === 'summary' ? 'Сводка' : section === 'identity' ? 'Личные данные' : section === 'response' ? 'Как отвечать' : 'Файлы'}</button>)}</div>
      {profileSection === 'summary' ? <div className="grid two-cols profile-summary-layout"><section className="panel-card stack profile-hero-card"><div className="profile-hero-top"><div><div className="eyebrow">Состояние профиля</div><h3>{user?.name || user?.email || 'Профиль пользователя'}</h3><div className="muted">{user?.title || (user?.role === 'admin' ? 'Администратор рабочей области' : 'Пользователь рабочей области')}</div></div><div className="profile-health-chip">{[user?.name, user?.timezone, user?.language, user?.goals, user?.assistant_profile?.about_user].filter((item) => String(item || '').trim()).length < 5 ? 'Нужно заполнить ещё 1 поле' : 'Профиль заполнен'}</div></div><div className="summary-grid summary-grid-tight"><div className="summary-box"><span>Заполненность</span><strong>{[user?.name, user?.timezone, user?.language, user?.goals, user?.assistant_profile?.about_user].filter((item) => String(item || '').trim()).length}/5</strong></div><div className="summary-box"><span>Файлы профиля</span><strong>{totalFiles}</strong></div><div className="summary-box"><span>Распознано</span><strong>{filesReady}</strong></div></div><div className="profile-next-step"><strong>Следующий шаг</strong><span>{[user?.name, user?.timezone, user?.language, user?.goals, user?.assistant_profile?.about_user].filter((item) => String(item || '').trim()).length < 5 ? 'Проверьте личные данные и дополните профиль, чтобы ответы Hermes были точнее.' : 'Профиль готов к работе. При необходимости обновите настройки ответов или набор файлов.'}</span></div></section><section className="panel-card stack"><h3>Сводка профиля</h3><div className="muted small">Email: {user?.email || '—'}</div><div className="muted small">Первичная настройка: {user?.onboarding_completed ? 'завершена' : 'не завершена'}</div>{profileSummary?.bullets?.length ? <ul className="bullet-list">{profileSummary.bullets.map((item, index) => <li key={index}>{item}</li>)}</ul> : <div className="muted">Добавьте личные данные и рабочий контекст, чтобы профиль стал полезнее для ответов.</div>}<div className="profile-quick-links"><button className="ghost-btn" type="button" onClick={() => onSectionChange('identity')}>Проверить личные данные</button><button className="ghost-btn" type="button" onClick={() => onSectionChange('files')}>Открыть файлы</button></div></section></div> : null}
      {profileSection === 'identity' ? <div className="grid two-cols"><section className="panel-card stack"><h3>Основные данные</h3><label>Имя<input name="name" value={profileForm.name} onChange={onProfileChange} /></label><label>Часовой пояс<input name="timezone" value={profileForm.timezone} onChange={onProfileChange} /></label><label>Язык<input name="language" value={profileForm.language} onChange={onProfileChange} /></label><label>Команда<input name="team" value={profileForm.team} onChange={onProfileChange} /></label><label>Роль / должность<input name="title" value={profileForm.title} onChange={onProfileChange} /></label><label>Цели<textarea name="goals" rows={3} value={profileForm.goals} onChange={onProfileChange} /></label><label>Ограничения<textarea name="constraints" rows={3} value={profileForm.constraints} onChange={onProfileChange} /></label><button className="primary-btn" onClick={onSaveProfile} type="button">Сохранить профиль</button></section><section className="panel-card stack"><h3>Смена пароля</h3><label>Текущий пароль<input name="currentPassword" type="password" value={passwordForm.currentPassword} onChange={onPasswordChange} /></label><label>Новый пароль<input name="newPassword" type="password" value={passwordForm.newPassword} onChange={onPasswordChange} /></label><button className="ghost-btn" onClick={onChangePassword} type="button">Обновить пароль</button></section></div> : null}
      {profileSection === 'response' ? <div className="grid two-cols"><section className="panel-card stack"><div className="head-actions"><div><h3>Как отвечать по умолчанию</h3><div className="muted small">Настройки берутся из runtime-справочников и сохраняются в профиль.</div></div></div><label>Ключевые рамки и приоритеты<textarea name="pinned" rows={4} value={profileForm.pinned} onChange={onProfileChange} placeholder="Ключевые рамки, приоритеты, запреты — по одной строке" /></label><label>Манера ответа<select name="tone" value={profileForm.tone} onChange={onProfileChange}>{toneOptions.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label><label>Глубина ответа<select name="answer_depth" value={profileForm.answer_depth} onChange={onProfileChange}>{answerDepthOptions.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label><label>Режим взаимодействия<select name="interaction_mode" value={profileForm.interaction_mode} onChange={onProfileChange}>{interactionModeOptions.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label><label>О пользователе<textarea name="about_user" rows={4} value={profileForm.about_user} onChange={onProfileChange} placeholder="Контекст о роли, зоне ответственности и типовых задачах" /></label><button className="primary-btn" onClick={onSaveProfile} type="button">Сохранить настройки ответов</button></section><section className="panel-card stack compact-card"><h3>Что влияет на ответы</h3><div className="muted">На качество ответа здесь сильнее всего влияют рабочий контекст, ключевые рамки и выбранный режим взаимодействия.</div><div className="profile-next-step"><strong>Сейчас в профиле</strong><span>{profileForm.about_user?.trim() || 'Дополнительный контекст пока не заполнен.'}</span></div></section></div> : null}
      {profileSection === 'files' ? <section className="panel-card stack"><div className="head-actions"><h3>Все файлы</h3><div className="muted small">Все сохранённые файлы из ваших диалогов: {totalFiles} · распознано: {filesReady}</div></div><div className="grid two-cols"><label>Поиск<input value={profileFileQuery} onChange={(e) => onProfileFileFilterChange('query', e.target.value)} placeholder="Имя файла, тип, фрагмент" /></label><label>Тип<select value={profileFileType} onChange={(e) => onProfileFileFilterChange('type', e.target.value)}><option value="all">Все</option><option value="text_ready">С распознанным текстом</option><option value="stored_only">Без распознанного текста</option></select></label></div>{files.length === 0 ? <div className="muted">Под выбранный фильтр файлы не найдены.</div> : <div className="table-list profile-files-list">{files.map((file, index) => { const checked = composerExistingFiles.some((item) => Number(item.id) === Number(file.id)); return <div className="table-row profile-file-row" key={file.id || index}><div className="profile-file-main"><div className="file-card-head"><strong>{file.original_name || file.stored_name || `Файл ${index + 1}`}</strong><span className="muted small">{file.file_kind === 'generated_result' || file.file_origin === 'assistant_generated' ? 'Результат' : 'Сохранённый файл'}</span></div><div className="muted small">{formatBytes(file.size_bytes)}{file.created_at ? ` · ${formatTs(file.created_at)}` : ''}</div><div className="muted small profile-file-summary">{humanizeExtractionStatus(file)} · {humanizePreviewStatus(file)}</div><div className="muted small profile-file-summary">{file.preview_summary || fileSummaryText(file)}</div></div><div className="profile-file-actions"><button className="ghost-btn ghost-btn-xs" onClick={() => onOpenUserFile(file)} type="button">Открыть</button><button className={`ghost-btn ghost-btn-xs ${checked ? 'active' : ''}`} onClick={() => onToggleExistingFile(file)} type="button">{checked ? 'В контексте' : 'В контекст'}</button><button className="ghost-btn ghost-btn-xs" onClick={() => onDeleteFile(file)} type="button">Удалить</button></div></div>; })}</div>}</section> : null}
    </div>
  );
}

function FilePreviewModal({ file, onClose }) {
  if (!file) return null;
  const previewUrl = filePreviewUrl(file);
  const image = isImageFile(file) && previewUrl;
  const textPreview = !image && isStructuredTextPreview(file);
  const lines = previewLines(file);
  return (
    <div className="modal-backdrop-react file-preview-backdrop" onClick={onClose}>
      <div className="modal-react file-preview-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header-react">
          <div>
            <h3>{file.original_name || file.stored_name || 'Файл'}</h3>
            <div className="muted small">{formatBytes(file.size_bytes)} · {file.mime_type || '—'}</div>
            <div className="muted small assistant-special-meta">{fileSurfaceMeta(file)}</div>
          </div>
          <div className="head-actions">
            {previewUrl ? <a className="ghost-btn" href={previewUrl} target="_blank" rel="noreferrer">Открыть отдельно</a> : null}
            <button className="ghost-btn" onClick={onClose} type="button">Закрыть</button>
          </div>
        </div>
        <div className="file-preview-summary-grid">
          <div className="panel-card compact-card stack">
            <div className="eyebrow">Извлечение</div>
            <strong>{humanizeExtractionStatus(file)}</strong>
            <div className="muted small">{file?.extraction_summary || file?.extraction_note || 'Дополнительных пояснений нет.'}</div>
          </div>
          <div className="panel-card compact-card stack">
            <div className="eyebrow">Preview</div>
            <strong>{humanizePreviewStatus(file)}</strong>
            <div className="muted small">{file?.preview_summary || fileSummaryText(file)}</div>
          </div>
          {fileQualityStatus(file) ? <div className="panel-card compact-card stack"><div className="eyebrow">Качество файла</div><strong>{fileQualityLabel(file)}</strong><div className="assistant-quality-row"><span className={`status-chip ${fileQualityChipClass(file)}`}>{fileQualityStatus(file)}</span>{fileQualityDetail(file) ? <span className="muted small">{fileQualityDetail(file)}</span> : null}</div></div> : null}
        </div>
        {image ? <div className="file-preview-stage"><img className="file-preview-image" src={previewUrl} alt={file.original_name || 'preview'} /></div> : textPreview ? <div className="panel-card stack compact-card"><div className="eyebrow">Что Hermes увидела внутри файла</div>{lines.length ? <pre className="file-preview-text-block">{lines.join('\n')}</pre> : <div className="muted">Для этого файла текстовый preview не собран.</div>}{previewUrl ? <div className="muted small">Если нужен исходный документ целиком, открой файл отдельно.</div> : null}</div> : <div className="panel-card stack compact-card"><div>Для этого типа файла встроенный preview не поддерживается.</div>{previewUrl ? <a href={previewUrl} target="_blank" rel="noreferrer">Открыть файл в новой вкладке</a> : null}</div>}
      </div>
    </div>
  );
}

function JobDraftModal({ open, draft, jobsMeta, currentUserId, currentThreadId, onClose, onChange, onSave, isEditing }) {
  const [recipientPickerOpen, setRecipientPickerOpen] = useState(false);
  const [recipientQuery, setRecipientQuery] = useState('');
  const [recipientRole, setRecipientRole] = useState('all');
  const [recipientTeam, setRecipientTeam] = useState('all');
  if (!open || !draft) return null;
  const jobsMetaReady = Boolean(jobsMeta?.templates && Object.keys(jobsMeta.templates || {}).length);
  const template = jobsMeta?.templates?.[draft.job_type] || { fields: [] };
  const accessUsers = usersAvailableForAccess(jobsMeta?.users || [], currentUserId);
  const recipientUsers = usersAvailableForAccess(jobsMeta?.users || [], currentUserId);
  const recipientThreads = threadsAvailableForRecipients(jobsMeta?.threads || [], currentThreadId);
  const filteredRecipientUsers = filterAssignableUsers(recipientUsers, { query: recipientQuery, role: recipientRole, team: recipientTeam });
  const recipientTeams = uniqueUserTeams(recipientUsers);
  const selectedRecipientUsers = (draft.recipients || []).filter((item) => item.recipient_type === 'fixed_user');
  const selectedRecipientThreads = (draft.recipients || []).filter((item) => item.recipient_type === 'fixed_thread');
  const scheduleKinds = [
    { value: 'daily', label: 'Каждый день' },
    { value: 'weekdays', label: 'По будням' },
    { value: 'weekly', label: 'Еженедельно' },
    { value: 'monthly', label: 'Ежемесячно' },
  ];
  return (
    <div className="modal-backdrop-react" onClick={onClose}>
      <div className="modal-react" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header-react">
          <div><h3>{isEditing ? 'Редактирование задачи' : 'Новая задача'}</h3><div className="muted">Основные настройки, доступ и создание отдельных чатов задач.</div></div>
          <button className="ghost-btn" onClick={onClose} type="button">Закрыть</button>
        </div>
        <div className="stack">
          <div className="grid two-cols">
            <label>Название<input value={draft.name} onChange={(e) => onChange('name', e.target.value)} /></label>
            <label>Контур выполнения<select value={draft.source_of_truth} onChange={(e) => onChange('source_of_truth', e.target.value)}><option value="local_jobs">Встроенная задача Hermes Web</option><option value="hermes_cron">Hermes cron</option></select></label>
          </div>
          <div className="grid two-cols">
            <label>Тип<select value={draft.job_type} onChange={(e) => onChange('job_type', e.target.value)} disabled={!jobsMetaReady}>{Object.entries(jobsMeta?.templates || {}).map(([key, value]) => <option key={key} value={key}>{value.label}</option>)}</select></label>
            {draft.source_of_truth === 'hermes_cron' ? <label>Доставка результата<select value={draft.deliver || 'origin'} onChange={(e) => onChange('deliver', e.target.value)}><option value="origin">В этот чат</option><option value="telegram">Telegram Home</option><option value="local">Только локально</option></select></label> : <label>Кто видит задачу<select value={draft.visibility} onChange={(e) => onChange('visibility', e.target.value)}><option value="private">Только владелец</option><option value="shared">Только по доступу</option><option value="workspace">Вся рабочая область</option></select></label>}
          </div>
          {!jobsMetaReady ? <div className="muted small">Загружаю параметры задач… окно откроется полностью, как только backend вернёт метаданные.</div> : null}
          <label>Описание<textarea rows={2} value={draft.description} onChange={(e) => onChange('description', e.target.value)} /></label>
          <label>Текст задачи<textarea rows={4} value={draft.prompt_template} onChange={(e) => onChange('prompt_template', e.target.value)} placeholder="Что именно делать по расписанию" /></label>
          <div className="grid two-cols">
            <label>Статус<select value={draft.status} onChange={(e) => onChange('status', e.target.value)}><option value="active">Активна</option><option value="paused">На паузе</option></select></label>
            <label>Дата старта<input type="date" value={draft.start_date} onChange={(e) => onChange('start_date', e.target.value)} /></label>
          </div>
          <section className="panel-card stack compact-card">
            <h4>Когда запускать</h4>
            <div className="grid two-cols">
              <label>Режим<select value={draft.schedule_kind} onChange={(e) => onChange('schedule_kind', e.target.value)}>{scheduleKinds.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>
              <label>Время<input type="time" value={draft.time_of_day} onChange={(e) => onChange('time_of_day', e.target.value)} /></label>
              <label>Таймзона<input value={draft.timezone} onChange={(e) => onChange('timezone', e.target.value)} /></label>
              <label>Дата старта<input type="date" value={draft.start_date} onChange={(e) => onChange('start_date', e.target.value)} /></label>
            </div>
            {draft.schedule_kind === 'weekly' ? <div className="weekdays-row">{WEEKDAYS.map((day) => <button key={day.key} type="button" className={`chip-btn ${draft.days_of_week.includes(day.key) ? 'active' : ''}`} onClick={() => onChange('toggle_weekday', day.key)}>{day.label}</button>)}</div> : null}
            <div className="muted small">{draft.schedule_kind === 'weekly' ? `Еженедельно (${draft.days_of_week.join(', ') || 'день не выбран'})` : draft.schedule_kind === 'weekdays' ? 'По будням' : draft.schedule_kind === 'monthly' ? 'Ежемесячно' : 'Каждый день'} в {draft.time_of_day} ({draft.timezone}), старт с {draft.start_date}.</div>
          </section>
          <section className="panel-card stack compact-card">
            <h4>Параметры шаблона</h4>
            <div className={`grid two-cols job-template-grid ${draft.job_type === 'research_watch' ? 'research-watch-grid' : ''}`}>
              {(template.fields || []).map((field) => (
                <label key={field.key} className={jobTemplateFieldClass(draft.job_type, field)}>
                  {field.label}
                  {field.type === 'textarea'
                    ? <textarea rows={jobTemplateFieldRows(field)} value={draft.parameters?.[field.key] || ''} onChange={(e) => onChange('parameter', { key: field.key, value: e.target.value })} placeholder={field.placeholder || ''} />
                    : field.type === 'select'
                      ? <select value={draft.parameters?.[field.key] || field.options?.[0] || ''} onChange={(e) => onChange('parameter', { key: field.key, value: e.target.value })}>{(field.options || []).map((option) => <option key={option} value={option}>{option}</option>)}</select>
                      : <input value={draft.parameters?.[field.key] || ''} onChange={(e) => onChange('parameter', { key: field.key, value: e.target.value })} placeholder={field.placeholder || ''} />}
                </label>
              ))}
            </div>
          </section>
          <section className="panel-card stack compact-card">
            <div className="head-actions"><div><h4>Кто видит задачу</h4><div className="muted small">Кто может подписаться на задачу и работать с ней.</div></div><button className="ghost-btn" type="button" onClick={() => onChange('access_add')}>+ Добавить доступ</button></div>
            {!draft.access.length ? <div className="muted">Дополнительный доступ пока не выдан.</div> : null}
            <div className="table-list">{draft.access.map((row, index) => <div className="table-row recipient-row" key={`${row.user_id}-${index}`}><div><strong>{accessLabel(row, accessUsers)}</strong><div className="muted small">{accessUsers.find((user) => Number(user.id) === Number(row.user_id))?.email || '—'}</div></div><div className="recipient-row-actions"><select value={row.user_id} onChange={(e) => onChange('access_user', { index, value: Number(e.target.value) })}>{accessUsers.map((user) => <option key={user.id} value={user.id}>{user.name || user.email} · {user.email}</option>)}</select><button className="ghost-btn" type="button" onClick={() => onChange('access_remove', index)}>Удалить</button></div></div>)}</div>
          </section>
          <section className="panel-card stack compact-card">
            <h4>Самоподписка пользователей</h4>
            <div className="grid two-cols">
              <label>Режим<select value={draft.self_subscribe_enabled ? 'enabled' : 'disabled'} onChange={(e) => onChange('self_subscribe_enabled', e.target.value === 'enabled')}><option value="disabled">Выключена</option><option value="enabled">Разрешена</option></select></label>
              <label>Кто может подписаться<select value={draft.self_subscribe_scope} disabled={!draft.self_subscribe_enabled} onChange={(e) => onChange('self_subscribe_scope', e.target.value)}><option value="visible_users">Тем, кто видит задачу</option><option value="workspace">Любому активному пользователю рабочей области</option></select></label>
            </div>
            <div className="muted small">{draft.self_subscribe_enabled ? draft.self_subscribe_scope === 'workspace' ? 'Любой активный пользователь рабочей области сможет сам подключить задачу.' : 'Самоподписка доступна только тем, кто уже видит задачу.' : 'Самоподписка выключена.'}</div>
          </section>
          <section className="panel-card stack compact-card">
            <div className="head-actions"><div><h4>Кто получает результат</h4><div className="muted small">Кому приходит рассылка с результатом задачи.</div></div><button className="ghost-btn" type="button" onClick={() => setRecipientPickerOpen((prev) => !prev)}>{recipientPickerOpen ? 'Скрыть подбор' : '+ Добавить получателей'}</button></div>
            {!draft.recipients.length ? <div className="muted">Получатели ещё не заданы.</div> : null}
            {(draft.recipients || []).length ? <div className="table-list">{(draft.recipients || []).map((item, index) => <div className="table-row recipient-row" key={`${item.recipient_type}-${item.target_value}-${index}`}><div><strong>{recipientLabel(item)}</strong><div className="muted small">{item.recipient_type === 'fixed_user' ? 'Пользователь' : item.recipient_type === 'fixed_thread' ? 'Чат-источник' : 'Получатель по умолчанию'}</div></div><div className="recipient-row-actions">{item.recipient_type === 'fixed_user' ? <button className="ghost-btn" type="button" onClick={() => onChange('toggle_recipient_user', recipientUsers.find((user) => String(user.id) === String(item.target_value)) || { id: item.target_value, name: item.label, email: item.label })}>Удалить</button> : item.recipient_type === 'fixed_thread' ? <button className="ghost-btn" type="button" onClick={() => onChange('toggle_recipient_thread', recipientThreads.find((thread) => String(thread.id) === String(item.target_value)) || { id: item.target_value, title: item.label })}>Удалить</button> : <span className="muted small">Всегда включён</span>}</div></div>)}</div> : null}
            {recipientPickerOpen ? <div className="recipient-picker-card stack"><div className="grid three-cols"><label>Имя или email<input value={recipientQuery} onChange={(e) => setRecipientQuery(e.target.value)} placeholder="Имя, email, роль" /></label><label>Роль<select value={recipientRole} onChange={(e) => setRecipientRole(e.target.value)}><option value="all">Все роли</option>{Array.from(new Set(recipientUsers.map((user) => user.role).filter(Boolean))).sort().map((role) => <option key={role} value={role}>{role}</option>)}</select></label><label>Подразделение<select value={recipientTeam} onChange={(e) => setRecipientTeam(e.target.value)}><option value="all">Все подразделения</option>{recipientTeams.map((team) => <option key={team} value={team}>{team}</option>)}</select></label></div><div className="table-list recipient-candidate-list">{filteredRecipientUsers.map((user) => { const checked = draft.recipients.some((item) => item.recipient_type === 'fixed_user' && String(item.target_value) === String(user.id)); return <label key={`user-${user.id}`} className={`checkbox-card recipient-choice-card ${checked ? 'selected' : ''}`}><input type="checkbox" checked={checked} onChange={() => onChange('toggle_recipient_user', user)} /><div><strong>{user.name || user.email}</strong><div className="muted small">{[user.email, user.role, user.team, user.title].filter(Boolean).join(' · ') || 'Без дополнительных признаков'}</div></div></label>; })}{!filteredRecipientUsers.length ? <div className="muted">По текущему фильтру пользователи не найдены.</div> : null}</div><details className="details-box"><summary>Чаты-источники для доставки</summary><div className="muted small">Используй только если нужно привязать доставку к конкретному chat-контексту; для обычной рассылки достаточно пользователей.</div><div className="table-list recipient-candidate-list">{recipientThreads.map((thread) => { const checked = draft.recipients.some((item) => item.recipient_type === 'fixed_thread' && String(item.target_value) === String(thread.id)); return <label key={`thread-${thread.id}`} className={`checkbox-card recipient-choice-card ${checked ? 'selected' : ''}`}><input type="checkbox" checked={checked} onChange={() => onChange('toggle_recipient_thread', thread)} /><div><strong>{thread.title}</strong><div className="muted small">{thread.email || 'без владельца'}</div></div></label>; })}</div></details></div> : null}
          </section>
          <div className="head-actions"><button className="primary-btn" onClick={onSave} type="button">Сохранить задачу</button></div>
        </div>
      </div>
    </div>
  );
}

function JobMembersModal({ open, mode, job, jobsMeta, currentUserId, currentThreadId, onClose, onSave }) {
  const [query, setQuery] = useState('');
  const [role, setRole] = useState('all');
  const [team, setTeam] = useState('all');
  const [draftRecipients, setDraftRecipients] = useState([]);
  const [draftAccess, setDraftAccess] = useState([]);
  useEffect(() => {
    if (!open || !job) return;
    setDraftRecipients((job.recipients || []).map((item) => ({ recipient_type: item.recipient_type, target_value: String(item.target_value), label: item.label || '' })));
    setDraftAccess((job.access || []).map((row) => ({ user_id: Number(row.user_id), role: row.role || 'viewer' })));
    setQuery('');
    setRole('all');
    setTeam('all');
  }, [open, job?.id, job?.version, mode]);
  if (!open || !job) return null;
  const jobsMetaReady = Boolean(jobsMeta && (Array.isArray(jobsMeta.users) || Array.isArray(jobsMeta.threads)));
  const recipientUsers = usersAvailableForAccess(jobsMeta?.users || [], currentUserId);
  const recipientThreads = threadsAvailableForRecipients(jobsMeta?.threads || [], currentThreadId);
  const filteredUsers = filterAssignableUsers(recipientUsers, { query, role, team });
  const teams = uniqueUserTeams(recipientUsers);
  const roleOptions = Array.from(new Set(recipientUsers.map((user) => user.role).filter(Boolean))).sort();
  const isRecipients = mode === 'recipients';
  const hasDraftChanges = isRecipients
    ? JSON.stringify(draftRecipients) !== JSON.stringify((job.recipients || []).map((item) => ({ recipient_type: item.recipient_type, target_value: String(item.target_value), label: item.label || '' })))
    : JSON.stringify(draftAccess) !== JSON.stringify((job.access || []).map((row) => ({ user_id: Number(row.user_id), role: row.role || 'viewer' })));
  const toggleDraftRecipientUser = (user) => {
    setDraftRecipients((prev) => {
      const exists = prev.some((item) => item.recipient_type === 'fixed_user' && String(item.target_value) === String(user.id));
      return exists
        ? prev.filter((item) => !(item.recipient_type === 'fixed_user' && String(item.target_value) === String(user.id)))
        : [...prev, { recipient_type: 'fixed_user', target_value: String(user.id), label: user.name || user.email || `user:${user.id}` }];
    });
  };
  const toggleDraftRecipientThread = (thread) => {
    setDraftRecipients((prev) => {
      const exists = prev.some((item) => item.recipient_type === 'fixed_thread' && String(item.target_value) === String(thread.id));
      return exists
        ? prev.filter((item) => !(item.recipient_type === 'fixed_thread' && String(item.target_value) === String(thread.id)))
        : [...prev, { recipient_type: 'fixed_thread', target_value: String(thread.id), label: thread.title || `chat:${thread.id}` }];
    });
  };
  const toggleDraftAccessUser = (user) => {
    setDraftAccess((prev) => prev.some((row) => Number(row.user_id) === Number(user.id)) ? prev.filter((row) => Number(row.user_id) !== Number(user.id)) : [...prev, { user_id: Number(user.id), role: 'viewer' }]);
  };
  const handleSaveClick = () => onSave(job.id, isRecipients ? draftRecipients : draftAccess, mode);
  return (
    <div className="modal-backdrop-react" onClick={onClose}>
      <div className="modal-react modal-react-narrow" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header-react">
          <div>
            <h3>{isRecipients ? 'Получатели задачи' : 'Доступ к задаче'}</h3>
            <div className="muted">{isRecipients ? 'Отметь пользователей и при необходимости чаты, затем сохрани изменения одним действием.' : 'Отметь пользователей, которым нужен доступ, и сохрани изменения одним действием.'}</div>
          </div>
          <button className="ghost-btn" onClick={onClose} type="button">Закрыть</button>
        </div>
        <div className="stack">
          {!jobsMetaReady ? <div className="panel-card compact-card surface-subtle muted">Загружаю список пользователей и чатов…</div> : <>
          <div className="grid three-cols">
            <label>Имя или email<input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Имя, email, роль" /></label>
            <label>Роль<select value={role} onChange={(e) => setRole(e.target.value)}><option value="all">Все роли</option>{roleOptions.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
            <label>Подразделение<select value={team} onChange={(e) => setTeam(e.target.value)}><option value="all">Все подразделения</option>{teams.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
          </div>
          {isRecipients ? <>
            <div className="table-list recipient-candidate-list">{filteredUsers.map((user) => { const checked = draftRecipients.some((item) => item.recipient_type === 'fixed_user' && String(item.target_value) === String(user.id)); return <label key={`picker-user-${user.id}`} className={`checkbox-card recipient-choice-card ${checked ? 'selected' : ''}`}><input type="checkbox" checked={checked} onChange={() => toggleDraftRecipientUser(user)} /><div><strong>{user.name || user.email}</strong><div className="muted small">{[user.email, user.role, user.team, user.title].filter(Boolean).join(' · ') || 'Без дополнительных признаков'}</div></div></label>; })}{!filteredUsers.length ? <div className="muted">По текущему фильтру пользователи не найдены.</div> : null}</div>
            <details className="details-box"><summary>Чаты-источники для доставки</summary><div className="muted small">Нужны только если рассылку надо привязать к конкретному chat-контексту.</div><div className="table-list recipient-candidate-list">{recipientThreads.map((thread) => { const checked = draftRecipients.some((item) => item.recipient_type === 'fixed_thread' && String(item.target_value) === String(thread.id)); return <label key={`picker-thread-${thread.id}`} className={`checkbox-card recipient-choice-card ${checked ? 'selected' : ''}`}><input type="checkbox" checked={checked} onChange={() => toggleDraftRecipientThread(thread)} /><div><strong>{thread.title}</strong><div className="muted small">{thread.email || 'без владельца'}</div></div></label>; })}</div></details>
          </> : <div className="table-list recipient-candidate-list">{filteredUsers.map((user) => { const exists = draftAccess.some((row) => Number(row.user_id) === Number(user.id)); return <div key={`access-user-${user.id}`} className={`table-row recipient-row recipient-inline-row ${exists ? 'selected' : ''}`}><div><strong>{user.name || user.email}</strong><div className="muted small">{[user.email, user.role, user.team, user.title].filter(Boolean).join(' · ') || 'Без дополнительных признаков'}</div></div><div className="recipient-row-actions"><button className="ghost-btn" type="button" onClick={() => toggleDraftAccessUser(user)}>{exists ? 'Убрать' : 'Добавить'}</button></div></div>; })}{!filteredUsers.length ? <div className="muted">По текущему фильтру пользователи не найдены.</div> : null}</div>}
          <div className="modal-footer-actions sticky-modal-actions">
            <div className="muted small">{hasDraftChanges ? 'Есть несохранённые изменения.' : 'Изменений пока нет.'}</div>
            <div className="recipient-row-actions">
              <button className="ghost-btn" onClick={onClose} type="button">Отменить</button>
              <button className="primary-btn" onClick={handleSaveClick} type="button" disabled={!hasDraftChanges}>Сохранить</button>
            </div>
          </div>
          </>}
        </div>
      </div>
    </div>
  );
}

function JobsScreen({ jobsMeta, jobs, activeJob, onSelectJob, onRunJob, onToggleSubscribe, onUpdateDisplayName, onOpenCreate, onOpenEdit, onOpenRecipients, onOpenAccess, onToggleStatus, onDeleteJob }) {
  const canEdit = activeJob && (activeJob.role === 'owner' || activeJob.role === 'admin') && (!activeJob.read_only || activeJob.source_of_truth === 'hermes_cron');
  const canRun = activeJob && (activeJob.role === 'owner' || activeJob.role === 'admin');
  const canPauseResume = canRun;
  const canSubscribe = activeJob && !activeJob.read_only && (Boolean(activeJob.can_self_subscribe) || Boolean(activeJob.subscription?.subscribed) || Boolean(activeJob.is_subscribed));
  const activeLastRunStatus = activeJob?.last_run_public_status || activeJob?.last_run_status || null;
  const activeLastRunReason = activeJob?.last_run_status_reason || null;
  const activeLastRunDetail = activeJob?.last_run_status_detail || activeJob?.last_run_summary || activeJob?.last_error || '';
  const activeLastRunDelivery = activeJob?.last_run_delivery_summary || null;
  const activeLastRunFinishedAt = activeJob?.last_run_finished_at || activeJob?.last_run_at || null;
  const isSubscribed = Boolean(activeJob?.subscription?.subscribed || activeJob?.is_subscribed);
  const subscriptionStatusLabel = isSubscribed ? 'Подписка включена' : 'Подписка не включена';
  const subscriptionStatusHint = isSubscribed
    ? 'Ты получаешь рассылку этой задачи как подписчик.'
    : activeJob?.can_self_subscribe
      ? 'Ты можешь сам подключить рассылку этой задачи.'
      : 'Самоподписка для тебя сейчас недоступна.';
  const subscriptionScopeHint = activeJob?.self_subscribe_enabled
    ? activeJob?.self_subscribe_scope === 'workspace'
      ? 'Подписаться может любой активный пользователь рабочей области.'
      : 'Подписаться могут те, кто уже видит эту задачу.'
    : 'Самоподписка в задаче выключена.';
  return (
    <div className="screen-shell scrollable">
      <header className="section-head compact mobile-chatlike-head"><div><div className="eyebrow">Задачи</div><h1>Задачи</h1><p className="muted small screen-section-copy">Плановые задачи, получатели результата и история запусков.</p></div><div className="head-actions mobile-chatlike-actions"><button className="primary-btn" onClick={onOpenCreate} type="button">+ Новая задача</button></div></header>
      <div className="grid jobs-cols">
        <section className="panel-card stack">
          <div className="head-actions"><h3>Список задач</h3><div className="muted small">{jobsMeta?.can_manage ? 'Можно создавать и редактировать задачи.' : 'Раздел открыт в режиме чтения.'}</div></div>
          <div className="table-list">{jobs.map((job) => <button className={`job-card ${String(activeJob?.id) === String(job.id) ? 'active' : ''}`} key={job.id} onClick={() => onSelectJob(job.id)} type="button"><strong>{job.display_name || job.name}</strong><span className="job-card-status">{humanizeJobStatus(job.status)}</span><span className="muted small">{job.last_run_public_status || job.last_run_status ? `Последний запуск: ${humanizeRunStatus(job.last_run_public_status || job.last_run_status)}` : 'Ещё не запускалась'}</span><span className="muted small">Следующий запуск: {formatTsCompact(job.next_run_at)}</span></button>)}</div>
        </section>
        <section className="panel-card stack jobs-detail-panel">
          <div className="head-actions"><div><h3>Детали задачи</h3><div className="muted small">Расписание, статус, доступ и история выбранной задачи.</div></div></div>
          {!activeJob ? <div className="muted">Выбери задачу слева.</div> : <>
            <section className="job-hero-card">
              <div className="job-hero-main">
                <div>
                  <div className="eyebrow">Выбранная задача</div>
                  <h2>{activeJob.display_name || activeJob.name}</h2>
                  <div className="muted">{activeJob.description || 'Описание не указано.'}</div>
                </div>
                <div className="job-status-stack">
                  <span className={`status-chip ${activeJob.status === 'active' ? 'ok' : 'muted'}`}>{humanizeJobStatus(activeJob.status)}</span>
                  <span className={`status-chip ${runStatusChipClass(activeLastRunStatus)}`}>{activeLastRunStatus ? `Последний запуск: ${humanizeRunStatus(activeLastRunStatus)}` : 'Ещё не запускалась'}</span>
                </div>
              </div>
              <div className="job-meta-grid job-meta-grid-compact">
                <div><span>Следующий запуск</span><strong>{formatTs(activeJob.next_run_at)}</strong></div>
                <div><span>Последний запуск</span><strong>{formatTs(activeLastRunFinishedAt)}</strong></div>
                <div><span>Владелец</span><strong>{activeJob.owner?.name || activeJob.owner?.email || '—'}</strong></div>
              </div>
              <div className="panel-card compact-card stack surface-subtle">
                <div className="head-actions job-section-actions"><div><h4>Итог последнего запуска</h4><div className="muted small">Что произошло, был ли результат и ушла ли доставка.</div></div><div className={`status-chip ${runStatusChipClass(activeLastRunStatus)}`}>{activeLastRunStatus ? humanizeRunStatus(activeLastRunStatus) : 'Нет запусков'}</div></div>
                {!activeLastRunStatus ? <div className="muted">Задача ещё не запускалась.</div> : <>
                  <div className="summary-grid summary-grid-tight">
                    <div className="summary-box"><span>Статус</span><strong>{humanizeRunStatus(activeLastRunStatus)}</strong></div>
                    <div className="summary-box"><span>Причина</span><strong>{humanizeRunStatusReason(activeLastRunReason)}</strong></div>
                    <div className="summary-box"><span>Доставка</span><strong>{activeLastRunDelivery || '—'}</strong></div>
                    <div className="summary-box"><span>Завершено</span><strong>{formatTs(activeLastRunFinishedAt)}</strong></div>
                  </div>
                  <div className="muted small">{activeLastRunDetail || 'Подробности последнего запуска не зафиксированы.'}</div>
                  {activeJob.last_run_summary && activeJob.last_run_summary !== activeLastRunDetail ? <div className="muted small">Итог: {activeJob.last_run_summary}</div> : null}
                </>}
              </div>
              <label>Публичное название задачи<input defaultValue={activeJob.display_name || ''} key={`job-alias-${activeJob.id}-${activeJob.version || 1}`} id="jobAliasInputReact" /></label>
              <div className="head-actions job-actions-row">
                {canPauseResume ? <button className="primary-btn" onClick={() => onToggleStatus(activeJob)} type="button">{activeJob.status === 'paused' ? 'Возобновить задачу' : 'Приостановить задачу'}</button> : null}
                {canRun ? <button className="ghost-btn" onClick={() => onRunJob(activeJob.id)} type="button">Запустить сейчас</button> : null}
                {canEdit ? <button className="ghost-btn" onClick={() => onOpenEdit(activeJob)} type="button">Открыть настройки</button> : null}
                {canEdit ? <button className="ghost-btn" onClick={() => onUpdateDisplayName(activeJob.id, document.getElementById('jobAliasInputReact')?.value || '')} type="button">Сохранить название</button> : null}
                {canRun ? <button className="ghost-btn" onClick={() => onDeleteJob(activeJob)} type="button">Удалить</button> : null}
              </div>
            </section>
            <div className="grid two-cols job-detail-support-grid">
              <section className="panel-card compact-card stack surface-subtle">
                <div className="head-actions job-section-actions"><div><h4>Куда отправляется результат</h4><div className="muted small">Маршрут доставки самой задачи: постоянные получатели результата.</div></div>{canEdit ? <button className="ghost-btn ghost-btn-xs job-inline-action" onClick={() => onOpenRecipients(activeJob)} type="button">Изменить маршрут</button> : null}</div>
                <div className="summary-grid summary-grid-tight">
                  <div className="summary-box"><span>Получателей</span><strong>{activeJob.recipients_count || (activeJob.recipients || []).length || 0}</strong></div>
                  <div className="summary-box"><span>Подписчиков</span><strong>{activeJob.subscriber_count || 0}</strong></div>
                </div>
                <div className="table-list">{(activeJob.recipients || []).map((item, index) => <div className="table-row recipient-row" key={`${item.recipient_type}-${item.target_value}-${index}`}><div><strong>{recipientLabel(item)}</strong><div className="muted small">{item.recipient_type === 'fixed_user' ? 'Пользователь получает результат напрямую' : item.recipient_type === 'fixed_thread' ? 'Результат уходит в конкретный чат' : item.recipient_type === 'subscribers' ? 'Результат уходит всем подписчикам задачи' : item.recipient_type === 'owner' ? 'Результат получает владелец задачи' : 'Получатель по умолчанию'}</div></div><div className="muted small">{item.recipient_type === 'fixed_thread' ? item.target_value : ''}</div></div>)}{!(activeJob.recipients || []).length ? <div className="muted">Постоянные получатели результата ещё не заданы.</div> : null}</div>
              </section>
              <section className="panel-card compact-card stack surface-subtle">
                <div className="head-actions job-section-actions"><div><h4>Моя подписка</h4><div className="muted small">Отдельно от маршрута доставки: получаешь ли ты рассылку этой задачи как подписчик.</div></div>{canSubscribe ? <button className="ghost-btn ghost-btn-xs job-inline-action" onClick={() => onToggleSubscribe(activeJob)} type="button">{isSubscribed ? 'Отключить подписку' : 'Подключить подписку'}</button> : null}</div>
                <div className="summary-grid summary-grid-tight">
                  <div className="summary-box"><span>Статус</span><strong>{subscriptionStatusLabel}</strong></div>
                  <div className="summary-box"><span>Правило</span><strong>{activeJob.self_subscribe_enabled ? 'Самоподписка разрешена' : 'Самоподписка выключена'}</strong></div>
                </div>
                <div className="muted small">{subscriptionStatusHint}</div>
                <div className="muted small">{subscriptionScopeHint}</div>
                {!canSubscribe && !isSubscribed ? <div className="muted small">Если рассылка нужна, её можно добавить через постоянных получателей задачи или открыть самоподписку в настройках.</div> : null}
              </section>
            </div>
            <div className="grid two-cols job-detail-support-grid">
              <section className="panel-card compact-card stack surface-subtle">
                <div className="head-actions job-section-actions"><div><h4>Кто видит задачу</h4><div className="muted small">Кто может подписаться на задачу и работать с ней.</div></div>{canEdit ? <button className="ghost-btn ghost-btn-xs job-inline-action" onClick={() => onOpenAccess(activeJob)} type="button">Добавить доступ</button> : null}</div>
                <div className="muted small">Режим: {humanizeVisibility(activeJob.visibility)}</div>
                <div className="table-list">{(activeJob.access || []).map((row, index) => <div className="table-row recipient-row" key={`${row.user_id}-${index}`}><div><strong>{accessLabel(row, jobsMeta?.users || [])}</strong><div className="muted small">читатель</div></div></div>)}{!(activeJob.access || []).length ? <div className="muted">Дополнительный доступ не выдан.</div> : null}</div>
              </section>
            </div>
            <details className="details-box" open><summary>История запусков</summary><div className="table-like-head"><span>Статус</span><span>Итог</span><span>Когда</span></div><div className="table-list">{(activeJob.runs || []).map((run, index) => { const publicStatus = run.public_status || run.status; const startedAt = run.started_at || run.created_at; const finishedAt = run.finished_at || run.completed_at || run.created_at; return <div className="table-row table-row-3cols" key={`${run.started_at || index}-${index}`}><div><strong>{humanizeRunStatus(publicStatus)}</strong><div className="muted small">{humanizeRunResultKind(run.result_kind)}</div><div className="muted small">{humanizeRunStatusReason(run.status_reason)}</div></div><div><div className="muted small">{run.status_detail || run.summary || (run.has_error ? 'Есть ошибка выполнения' : 'Итог не указан')}</div><div className="muted small">{run.delivery_summary || 'Доставка не зафиксирована'}{run.delivered_count ? ` · получателей: ${run.delivered_count}` : ''}</div>{run.summary && run.status_detail && run.summary !== run.status_detail ? <div className="muted small">Краткий итог: {run.summary}</div> : null}</div><div className="muted small"><div>Старт: {formatTs(startedAt)}</div><div>Финиш: {formatTs(finishedAt)}</div><div>Длительность: {formatDurationMs(run.duration_ms)}</div></div></div>; })}{!(activeJob.runs || []).length ? <div className="muted">История запусков пока пуста.</div> : null}</div></details>
          </>}
        </section>
      </div>
    </div>
  );
}


function AdminOverviewSection({ admin, onSaveNotice }) {
  const now = Date.now();
  const users = admin.users || [];
  const threads = admin.threads || [];
  const jobs = admin.jobs || [];
  const pausedJobs = jobs.filter((job) => job.status === 'paused').length;
  const failedJobs = jobs.filter((job) => job.last_run_status && job.last_run_status !== 'success').length;
  const chatsNeedingAttention = threads.filter((thread) => !thread.message_count || Number(thread.message_count) < 2).length;
  const recentThreads30 = threads.filter((thread) => thread.updated_at && (now - new Date(thread.updated_at).getTime()) <= 30 * 24 * 60 * 60 * 1000);
  const recentThreads7 = threads.filter((thread) => thread.updated_at && (now - new Date(thread.updated_at).getTime()) <= 7 * 24 * 60 * 60 * 1000);
  const recentThreads1 = threads.filter((thread) => thread.updated_at && (now - new Date(thread.updated_at).getTime()) <= 24 * 60 * 60 * 1000);
  const mau = new Set(recentThreads30.map((thread) => thread.email).filter(Boolean)).size;
  const wau = new Set(recentThreads7.map((thread) => thread.email).filter(Boolean)).size;
  const dau = new Set(recentThreads1.map((thread) => thread.email).filter(Boolean)).size;
  const healthyJobs = jobs.filter((job) => job.status === 'active' && (!job.last_run_status || job.last_run_status === 'success')).length;
  const bars = Array.from({ length: 7 }, (_, index) => {
    const dayStart = new Date();
    dayStart.setHours(0, 0, 0, 0);
    dayStart.setDate(dayStart.getDate() - (6 - index));
    const dayEnd = new Date(dayStart);
    dayEnd.setDate(dayEnd.getDate() + 1);
    const chats = threads.filter((thread) => thread.updated_at && new Date(thread.updated_at) >= dayStart && new Date(thread.updated_at) < dayEnd).length;
    const runs = jobs.filter((job) => job.last_run_at && new Date(job.last_run_at) >= dayStart && new Date(job.last_run_at) < dayEnd).length;
    return { label: `${dayStart.getDate()}.${String(dayStart.getMonth() + 1).padStart(2, '0')}`, chats, runs };
  });
  const maxBar = Math.max(1, ...bars.flatMap((item) => [item.chats, item.runs]));
  return <>
    <section className="panel-card stack admin-hero-card">
      <div className="admin-hero-top"><div><div className="eyebrow">Обзор рабочей области</div><h3>Что происходит в продукте сейчас</h3><div className="muted">Короткий управленческий срез по активности, качеству и зонам внимания.</div></div><div className={`status-chip ${failedJobs > 0 || pausedJobs > 0 ? 'warn' : 'ok'}`}>{failedJobs > 0 || pausedJobs > 0 ? 'Есть точки внимания' : 'Контур выглядит стабильно'}</div></div>
      <div className="summary-grid summary-grid-tight admin-kpi-grid">
        <div className="summary-box emphasis-box"><span>MAU</span><strong>{mau}</strong><div className="muted small">уникальных пользователей за 30 дней</div></div>
        <div className="summary-box"><span>WAU</span><strong>{wau}</strong><div className="muted small">активных за 7 дней</div></div>
        <div className="summary-box"><span>DAU</span><strong>{dau}</strong><div className="muted small">активных за 24 часа</div></div>
        <div className="summary-box"><span>Здоровые задачи</span><strong>{healthyJobs}</strong><div className="muted small">активные и без последней ошибки</div></div>
      </div>
      <div className="admin-attention-grid">
        <div className="attention-item"><strong>{failedJobs}</strong><span>задач с неуспешным последним запуском</span></div>
        <div className="attention-item"><strong>{chatsNeedingAttention}</strong><span>чатов с низкой активностью</span></div>
        <div className="attention-item"><strong>{users.length}</strong><span>пользователей в рабочем контуре</span></div>
      </div>
    </section>
    <section className="panel-card stack admin-chart-card"><div className="head-actions"><div><h3>Динамика за 7 дней</h3><div className="muted small">Чаты и последние запуски задач по дням.</div></div></div><div className="admin-mini-chart">{bars.map((item) => <div className="admin-mini-chart-col" key={item.label}><div className="admin-mini-chart-bars"><div className="admin-mini-chart-bar chats" style={{ height: `${Math.max(8, (item.chats / maxBar) * 100)}%` }} title={`Чаты: ${item.chats}`} /><div className="admin-mini-chart-bar runs" style={{ height: `${Math.max(8, (item.runs / maxBar) * 100)}%` }} title={`Запуски: ${item.runs}`} /></div><div className="muted small">{item.label}</div></div>)}</div><div className="admin-chart-legend"><span><i className="legend-dot chats" />Чаты</span><span><i className="legend-dot runs" />Запуски задач</span></div></section>
    <div className="grid two-cols">
      <section className="panel-card stack"><div className="head-actions"><h3>Чаты, за которыми стоит посмотреть</h3><div className="muted small">Живые диалоги и quiet-зоны без лишней технички.</div></div><div className="table-list">{threads.map((thread) => <div className="table-row" key={thread.id}><div><strong>{thread.title}</strong><div className="muted small">{thread.email || '—'} · сообщений: {thread.message_count || 0}</div></div><div className="muted small">{formatTs(thread.updated_at)}</div></div>)}</div></section>
      <section className="panel-card stack"><div className="head-actions"><h3>Состояние задач</h3><div className="muted small">Что запущено стабильно, а что просит внимания.</div></div><div className="table-list">{jobs.map((job) => <div className="table-row" key={job.id}><div><strong>{job.name}</strong><div className="muted small">{humanizeVisibility(job.visibility)} · {job.last_run_status ? humanizeRunStatus(job.last_run_status) : 'ещё не запускалась'}</div></div><div className="muted small">{formatTs(job.next_run_at)}</div></div>)}</div></section>
    </div>
    <section className="panel-card stack admin-notice-card"><div className="head-actions"><div><h3>Объявление в чате</h3><div className="muted small">Текущий статус: {admin.chatNotice?.enabled ? 'включено' : 'выключено'}</div></div><div className={`status-chip ${admin.chatNotice?.enabled ? 'ok' : 'muted'}`}>{admin.chatNotice?.enabled ? 'Показывается пользователям' : 'Сейчас скрыто'}</div></div><textarea id="adminChatNoticeReact" defaultValue={admin.chatNotice?.text || ''} rows={4} key={`notice-${admin.chatNotice?.enabled ? 1 : 0}-${admin.chatNotice?.text || ''}`} /><div className="head-actions"><button className="ghost-btn" onClick={() => onSaveNotice(true, document.getElementById('adminChatNoticeReact')?.value || '')} type="button">Сохранить и включить</button><button className="ghost-btn" onClick={() => onSaveNotice(false, document.getElementById('adminChatNoticeReact')?.value || '')} type="button">Сохранить и выключить</button></div></section>
  </>;
}

function AdminUsersSection({ users, selectedUserIds, onToggleUser, onSelectAll, onClearSelection, onBulkStatus, onOpenCreate, onEditUser, onAssignJob }) {
  const activeCount = users.filter((user) => (user.status || (user.deleted_at ? 'deleted' : user.is_active === false ? 'inactive' : 'active')) === 'active').length;
  return <section className="panel-card stack admin-users-fullwidth">
    <div className="head-actions"><div><h3>Пользователи</h3><div className="muted small">Управление доступом, ролями и рабочей нагрузкой.</div></div><div className="head-actions"><button className="ghost-btn" type="button" onClick={onSelectAll}>Выбрать всех</button><button className="ghost-btn" type="button" onClick={onClearSelection}>Снять выбор</button><button className="primary-btn" type="button" onClick={onOpenCreate}>Новый пользователь</button></div></div>
    <div className="summary-grid"><div className="summary-box"><span>Всего</span><strong>{users.length}</strong></div><div className="summary-box"><span>Активны</span><strong>{activeCount}</strong></div><div className="summary-box"><span>Выбрано</span><strong>{selectedUserIds.length}</strong></div></div>
    <div className="head-actions"><button className="ghost-btn" type="button" disabled={!selectedUserIds.length} onClick={() => onBulkStatus('inactive')}>Сделать неактивными</button><button className="ghost-btn" type="button" disabled={!selectedUserIds.length} onClick={() => onBulkStatus('deleted')}>Удалить из выбора</button></div>
    <div className="table-like-head table-like-head-users"><span>Пользователь</span><span>Статус</span><span>Чаты</span><span>Задачи</span><span>Действия</span></div>
    <div className="table-list">{users.map((user) => { const checked = selectedUserIds.includes(Number(user.id)); const status = humanizeUserStatus(user.status || (user.deleted_at ? 'deleted' : user.is_active === false ? 'inactive' : 'active')); return <div className="table-row table-row-users" key={user.id}><div className="user-cell"><label className="checkbox-inline"><input type="checkbox" checked={checked} onChange={(e) => onToggleUser(user.id, e.target.checked)} /><span /></label><div className="grow"><strong>{user.name || user.email}</strong><div className="muted small">{user.email}</div><div className="muted small">{user.role} · версия {user.version ?? '—'}</div></div></div><div className="muted small"><strong>{status}</strong></div><div className="metric-cell"><strong>{user.thread_count || 0}</strong><span className="muted small">чатов</span></div><div className="metric-cell"><strong>{user.job_count || 0}</strong><span className="muted small">задач</span></div><div className="head-actions"><button className="ghost-btn" type="button" onClick={() => onAssignJob(user)}>Назначить задачу</button><button className="ghost-btn" type="button" onClick={() => onEditUser(user.id)}>Редактировать</button></div></div>; })}</div>
  </section>;
}

function AdminDataPolicySection({ dataPolicy, onPolicyDraftChange, onSave }) {
  const registryItems = dataPolicy?.source_registry?.items || [];
  const policy = dataPolicy?.processing_policy || {};
  const connectorTargets = policy.connector_targets || {};
  const externalItems = registryItems.filter((item) => item.origin === 'external' && item.enabled);
  const defaultGlobalSource = externalItems.some((item) => item.source_key === policy.default_global_source)
    ? policy.default_global_source
    : (externalItems[0]?.source_key || '');
  const connectorGroupOptions = [
    { value: 'internal_connector', label: 'Внутренний коннектор' },
    { value: 'external_connector', label: 'Внешний коннектор' },
  ];
  const connectorGroupLabel = (groupKey) => {
    if (groupKey === 'internal_connector') return 'Внутренний коннектор';
    if (groupKey === 'external_connector') return 'Внешний коннектор';
    return 'Не назначено';
  };
  const childConnectorGroup = (connectorKey) => {
    if ((connectorTargets.internal_connector || []).includes(connectorKey)) return 'internal_connector';
    if ((connectorTargets.external_connector || []).includes(connectorKey)) return 'external_connector';
    return '';
  };
  return <div className="grid two-cols admin-split">
    <section className="panel-card stack">
      <div className="head-actions"><div><h3>Источники</h3><div className="muted small">Можно включать и выключать доступные источники для дашбордов и запросов из чата.</div></div></div>
      <div className="table-list">{registryItems.map((item, index) => <div className="table-row source-admin-row admin-source-card" key={item.source_key}><div className="grow admin-source-main"><strong>{item.name}</strong><div className="muted small">{item.source_key} · {item.origin === 'internal' ? 'внутренний' : 'внешний'} · {item.connector_kind}</div><div className="muted small">{item.description || (item.available === false ? 'Сейчас источник недоступен.' : 'Источник доступен для использования.')}</div>{Array.isArray(item.child_connectors) && item.child_connectors.length ? <div className="connector-children-list">{item.child_connectors.map((child) => { const assignedGroup = childConnectorGroup(child.connector_key); return <label className={`checkbox-card connector-choice-card ${child.available === false ? 'disabled-card' : ''}`} key={`${item.source_key}-${child.connector_key}`}><input type="checkbox" checked={Boolean(assignedGroup)} onChange={(e) => onPolicyDraftChange('connector_assignment', { connector_key: child.connector_key, value: e.target.checked ? item.source_key : '' })} disabled={child.available === false} /><div className="grow"><strong>{child.alias || child.connector_key}</strong><div className="muted small">{child.connector_key} · группа: {connectorGroupLabel(assignedGroup)}</div><div className="muted small">{child.purpose || child.target || 'Служебная интеграция группы.'}</div></div><select value={assignedGroup} onChange={(e) => onPolicyDraftChange('connector_assignment', { connector_key: child.connector_key, value: e.target.value })} disabled={child.available === false}><option value="">Не назначено</option>{connectorGroupOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>; })}</div> : null}</div><label className="checkbox-inline source-admin-toggle"><input type="checkbox" checked={Boolean(item.enabled)} onChange={(e) => onPolicyDraftChange('source_field', { index, field: 'enabled', value: e.target.checked })} /><span />{item.enabled ? 'Включён' : 'Выключен'}</label></div>)}</div>
    </section>
    <section className="panel-card stack admin-policy-panel">
      <div className="head-actions"><div><h3>Политика по умолчанию</h3><div className="muted small">Определяет, в каком порядке использовать внутренние и внешние источники по умолчанию.</div></div></div>
      <label>Политика источников<select value={policy.default_mode || SOURCE_MODE_LOCAL_FIRST} onChange={(e) => onPolicyDraftChange('policy_field', { field: 'default_mode', value: e.target.value })}>{(policy.mode_options || []).map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>
      <div className="muted small">{(policy.mode_options || []).find((item) => item.value === (policy.default_mode || SOURCE_MODE_LOCAL_FIRST))?.description || 'Сначала внутренние, затем внешние.'}</div>
      <label>Основной внешний источник<select value={defaultGlobalSource} onChange={(e) => onPolicyDraftChange('policy_field', { field: 'default_global_source', value: e.target.value })} disabled={!externalItems.length}>{externalItems.length ? externalItems.map((item) => <option key={item.source_key} value={item.source_key}>{item.name}</option>) : <option value="">Нет доступных внешних источников</option>}</select></label>
      <div className="table-list admin-policy-summary">{connectorGroupOptions.map((group) => <div className="table-row" key={group.value}><div><strong>{group.label}</strong><div className="muted small">Назначенные интеграции</div></div><div className="muted small admin-policy-group-value">{(connectorTargets[group.value] || []).length ? (connectorTargets[group.value] || []).join(', ') : 'не выбраны'}</div></div>)}</div>
      <div className="head-actions"><button className="primary-btn" type="button" onClick={onSave}>Сохранить policy</button></div>
    </section>
  </div>;
}

function AdminOperationsSection({ eventsFilters, events, onFiltersChange }) {
  const csvUrl = api.adminEventsExportUrl(eventsFilters, 'csv');
  const jsonUrl = api.adminEventsExportUrl(eventsFilters, 'json');
  const zipUrl = api.adminEventsExportUrl(eventsFilters, 'zip');
  const eventKindLabel = (eventType) => {
    const value = String(eventType || '');
    if (value === 'user') return 'Сообщение пользователя';
    if (value === 'assistant') return 'Ответ ассистента';
    if (value.startsWith('job:')) return 'Запуск задачи';
    if (value.includes('file')) return 'Файл';
    return 'Системное действие';
  };
  return <section className="panel-card stack admin-operations-panel"><div className="head-actions"><div><h3>Операции</h3><div className="muted small">Последние действия в интерфейсе: что произошло, к какому объекту относится и какого это типа.</div></div></div><div className="grid three-cols"><label>С<input type="datetime-local" value={eventsFilters.date_from} onChange={(e) => onFiltersChange('date_from', e.target.value)} /></label><label>По<input type="datetime-local" value={eventsFilters.date_to} onChange={(e) => onFiltersChange('date_to', e.target.value)} /></label><label>Лимит<input type="number" min="1" max="500" value={eventsFilters.limit} onChange={(e) => onFiltersChange('limit', Number(e.target.value) || 100)} /></label></div><div className="head-actions"><a className="ghost-btn link-btn" href={csvUrl} target="_blank" rel="noreferrer">Выгрузить CSV</a><a className="ghost-btn link-btn" href={jsonUrl} target="_blank" rel="noreferrer">Выгрузить JSON</a><a className="ghost-btn link-btn" href={zipUrl} target="_blank" rel="noreferrer">Выгрузить ZIP</a></div><div className="table-list admin-events-list">{events.map((event, index) => <div className="table-row admin-event-row" key={`${event.created_at}-${index}`}><div className="admin-event-main"><strong>{event.subject}</strong><div className="muted small">{event.email}</div><div className="muted small">{event.content_short}</div></div><div className="muted small admin-event-type"><strong>{eventKindLabel(event.event_type)}</strong><div>{event.event_type}</div></div><div className="muted small admin-event-time">{formatTs(event.created_at)}</div></div>)}{!events.length ? <div className="muted">События по выбранному диапазону не найдены.</div> : null}</div></section>;
}

function AdminReferencesSection({ references, activeDatasetKey, referenceDraft, referenceHistory, selectedReferenceItems, onOpenDataset, onEditItem, onCreateItem, onReferenceDraftChange, onSaveReference, onToggleReferenceItem, onBulkReferenceStatus }) {
  const datasets = Object.values(references || {});
  const activeDataset = activeDatasetKey ? references?.[activeDatasetKey] : null;
  const selectedKeys = selectedReferenceItems[activeDatasetKey] || [];
  return <div className="grid two-cols admin-split">
    <section className="panel-card stack"><h3>Справочники</h3><div className="table-list">{datasets.map((dataset) => <div className={`table-row clickable ${dataset.dataset_key === activeDatasetKey ? 'selected' : ''}`} key={dataset.dataset_key} onClick={() => onOpenDataset(dataset.dataset_key)}><div><strong>{dataset.label || dataset.dataset_key}</strong><div className="muted small">{dataset.description || 'Описание не задано.'}</div></div><div className="muted small">Элементов: {dataset.items?.length || 0}</div></div>)}</div></section>
    <section className="panel-card stack">{!activeDataset ? <div className="muted">Выбери справочник слева.</div> : <><div className="head-actions"><div><h3>{activeDataset.label || activeDataset.dataset_key}</h3><div className="muted small">Технический JSON скрыт: служебный payload собирается автоматически.</div></div><button className="ghost-btn" type="button" onClick={() => onCreateItem(activeDataset.dataset_key)}>+ Новый элемент</button><button className="ghost-btn" type="button" disabled={!selectedKeys.length} onClick={() => onBulkReferenceStatus(activeDataset.dataset_key, 'inactive')}>Сделать неактивными</button><button className="ghost-btn" type="button" disabled={!selectedKeys.length} onClick={() => onBulkReferenceStatus(activeDataset.dataset_key, 'deleted')}>Удалить из выбора</button></div><div className="table-list">{(activeDataset.items || []).map((item) => { const checked = selectedKeys.includes(item.item_key); return <div className="table-row" key={item.item_key}><label className="checkbox-inline"><input type="checkbox" checked={checked} onChange={(e) => onToggleReferenceItem(activeDataset.dataset_key, item.item_key, e.target.checked)} /><span /></label><div className="grow"><strong>{item.label}</strong><div className="muted small">{item.item_key} · {humanizeUserStatus(item.status || (item.deleted_at ? 'deleted' : item.is_active === false ? 'inactive' : 'active'))} · версия {item.version ?? '—'}</div></div><button className="ghost-btn" type="button" onClick={() => onEditItem(activeDataset.dataset_key, item)}>Редактировать</button></div>; })}</div>{referenceDraft ? <section className="panel-card compact-card stack"><h4>{referenceDraft.item_key ? 'Редактирование элемента' : 'Новый элемент'}</h4><div className="grid two-cols"><label>Ключ<input value={referenceDraft.item_key} onChange={(e) => onReferenceDraftChange('item_key', e.target.value)} /></label><label>Название<input value={referenceDraft.label} onChange={(e) => onReferenceDraftChange('label', e.target.value)} /></label><label>Порядок<input type="number" value={referenceDraft.sort_order} onChange={(e) => onReferenceDraftChange('sort_order', e.target.value)} /></label><label>Статус<select value={referenceDraft.status} onChange={(e) => onReferenceDraftChange('status', e.target.value)}><option value="active">Активен</option><option value="inactive">Неактивен</option><option value="deleted">Удалён</option></select></label></div><div className="info-inline">Дополнительные технические поля будут сохранены автоматически. Ручное заполнение JSON не требуется.</div><div className="head-actions"><button className="primary-btn" type="button" onClick={onSaveReference}>Сохранить элемент</button></div><label>История изменений<textarea rows={8} readOnly value={(referenceHistory || []).map((entry) => `${entry.created_at} · ${entry.change_type}`).join('\n')} /></label></section> : null}</>}</section>
  </div>;
}

function AdminScreen(props) {
  const { admin, onSectionChange } = props;
  return <div className="screen-shell scrollable"><header className="section-head compact mobile-chatlike-head"><div><div className="eyebrow">Управление</div><h1>Административный обзор</h1><p className="muted small screen-section-copy">Рабочие метрики, пользователи, операции и системные настройки.</p></div></header><div className="head-actions admin-tabs mobile-chatlike-tabs">{ADMIN_SECTIONS.map((section) => <button key={section} className={`ghost-btn ${admin.section === section ? 'active' : ''}`} type="button" onClick={() => onSectionChange(section)}>{section === 'overview' ? 'Обзор' : section === 'users' ? 'Пользователи' : section === 'operations' ? 'Операции' : section === 'references' ? 'Справочники' : 'Источники и policy'}</button>)}</div>{admin.section === 'overview' ? <AdminOverviewSection admin={admin} onSaveNotice={props.onSaveNotice} /> : null}{admin.section === 'users' ? <AdminUsersSection users={admin.users} selectedUserIds={props.selectedUserIds} onToggleUser={props.onToggleUser} onSelectAll={props.onSelectAllUsers} onClearSelection={props.onClearSelection} onBulkStatus={props.onBulkUserStatus} onOpenCreate={props.onOpenCreateUser} onEditUser={props.onEditUser} onAssignJob={props.onAssignJob} /> : null}{admin.section === 'operations' ? <AdminOperationsSection eventsFilters={admin.eventsFilters} events={admin.events} onFiltersChange={props.onEventsFilterChange} /> : null}{admin.section === 'references' ? <AdminReferencesSection references={admin.references} activeDatasetKey={props.activeDatasetKey} referenceDraft={props.referenceDraft} referenceHistory={props.referenceHistory} selectedReferenceItems={props.selectedReferenceItems} onOpenDataset={props.onOpenDataset} onEditItem={props.onEditReferenceItem} onCreateItem={props.onCreateReferenceItem} onReferenceDraftChange={props.onReferenceDraftChange} onSaveReference={props.onSaveReference} onToggleReferenceItem={props.onToggleReferenceItem} onBulkReferenceStatus={props.onBulkReferenceStatus} /> : null}{admin.section === 'data_policy' ? <AdminDataPolicySection dataPolicy={props.dataPolicyDraft || admin.dataPolicy} onPolicyDraftChange={props.onDataPolicyDraftChange} onSave={props.onSaveDataPolicy} /> : null}</div>;
}

function AdminUserModal({ open, userForm, userHistory, importCsv, onChange, onSave, onClose, onImportCsvChange, onImportCsv }) {
  if (!open) return null;
  return (
    <div className="modal-backdrop-react" onClick={onClose}>
      <div className="modal-react" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header-react">
          <div>
            <h3>{userForm.id ? 'Редактирование пользователя' : 'Новый пользователь'}</h3>
            <div className="muted">Email, пароль и имя обязательны при создании. Остальное можно заполнить позже.</div>
          </div>
          <button className="ghost-btn" onClick={onClose} type="button">Закрыть</button>
        </div>
        <div className="stack">
          <div className="grid two-cols">
            <label>Email<input value={userForm.email} onChange={(e) => onChange('email', e.target.value)} /></label>
            <label>Пароль<input type="password" value={userForm.password} onChange={(e) => onChange('password', e.target.value)} placeholder={userForm.id ? 'Оставь пустым, если не меняешь' : ''} /></label>
            <label>Имя<input value={userForm.name} onChange={(e) => onChange('name', e.target.value)} /></label>
            <label>Роль<select value={userForm.role} onChange={(e) => onChange('role', e.target.value)}><option value="user">Пользователь</option><option value="admin">Администратор</option></select></label>
            <label>Статус<select value={userForm.status} onChange={(e) => onChange('status', e.target.value)}><option value="active">Активен</option><option value="inactive">Неактивен</option><option value="deleted">Удалён</option></select></label>
            <label>Таймзона<input value={userForm.timezone} onChange={(e) => onChange('timezone', e.target.value)} /></label>
            <label>Язык<input value={userForm.language} onChange={(e) => onChange('language', e.target.value)} /></label>
            <label>Команда<input value={userForm.team} onChange={(e) => onChange('team', e.target.value)} /></label>
            <label>Должность<input value={userForm.title} onChange={(e) => onChange('title', e.target.value)} /></label>
            <label>Стиль ответов<input value={userForm.style} onChange={(e) => onChange('style', e.target.value)} /></label>
          </div>
          <label>Цели<textarea rows={2} value={userForm.goals} onChange={(e) => onChange('goals', e.target.value)} /></label>
          <label>Ограничения<textarea rows={2} value={userForm.constraints} onChange={(e) => onChange('constraints', e.target.value)} /></label>
          <label>Важные акценты<textarea rows={2} value={userForm.pinned} onChange={(e) => onChange('pinned', e.target.value)} /></label>
          <div className="grid two-cols">
            <label>Тон<select value={userForm.tone} onChange={(e) => onChange('tone', e.target.value)}><option value="business">Деловой</option><option value="friendly">Дружелюбный</option><option value="critical">Критичный</option></select></label>
            <label>Глубина<select value={userForm.answer_depth} onChange={(e) => onChange('answer_depth', e.target.value)}><option value="balanced">Сбалансированно</option><option value="concise">Коротко</option><option value="deep">Глубоко</option></select></label>
            <label>Манера<select value={userForm.interaction_mode} onChange={(e) => onChange('interaction_mode', e.target.value)}><option value="compare_options">Сравнивать варианты</option><option value="clarify_when_needed">Уточнять по необходимости</option><option value="direct">Прямо к делу</option></select></label>
            <label>О пользователе<textarea rows={2} value={userForm.about_user} onChange={(e) => onChange('about_user', e.target.value)} /></label>
          </div>
          <div className="head-actions"><button className="primary-btn" type="button" onClick={onSave}>{userForm.id ? 'Сохранить пользователя' : 'Создать пользователя'}</button></div>
          <details className="details-box"><summary>Импорт CSV</summary><label>CSV<textarea rows={6} value={importCsv} onChange={(e) => onImportCsvChange(e.target.value)} /></label><button className="ghost-btn" type="button" onClick={onImportCsv}>Импортировать CSV</button></details>
          <details className="details-box"><summary>История изменений</summary><div className="table-list">{userHistory.map((entry, index) => <div className="table-row" key={`${entry.created_at || index}-${index}`}><div><strong>{entry.event_type || 'update'}</strong><div className="muted small">{entry.changed_by_email || 'system'}</div></div><div className="muted small">{formatTs(entry.created_at)}</div></div>)}{!userHistory.length ? <div className="muted">История изменений пока пуста.</div> : null}</div></details>
        </div>
      </div>
    </div>
  );
}

function ThreadsModal({ open, threads, activeThreadId, onSelectThread, onToggleArchiveThread, onClose }) {
  if (!open) return null;
  return (
    <div className="modal-backdrop-react" onClick={onClose}>
      <div className="modal-react modal-react-narrow" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header-react">
          <div>
            <h3>Все чаты</h3>
            <div className="muted">Полный список чатов рабочего контура.</div>
          </div>
          <button className="ghost-btn" onClick={onClose} type="button">Закрыть</button>
        </div>
        <div className="table-list">{threads.map((thread) => <div className={`thread-item thread-item-modal ${String(thread.id) === String(activeThreadId) ? 'active' : ''}`} key={thread.id}><button className="thread-item thread-item-button-reset" type="button" onClick={() => onSelectThread(thread.id)}><div className="thread-item-top"><div className="thread-title-stack"><strong>{thread.title || 'Без названия'}</strong>{thread.archived ? <span className="thread-state-chip">В архиве</span> : null}</div><span className="thread-date">{formatTsCompact(threadLastActivity(thread))}</span></div><div className="thread-item-bottom"><span>{thread.preview || 'Без превью'}</span></div><div className="muted small">Последнее взаимодействие: {formatTs(threadLastActivity(thread))}</div></button><button className="ghost-btn ghost-btn-xs" onClick={() => onToggleArchiveThread(thread.id)} type="button">{thread.archived ? 'Из архива' : 'В архив'}</button></div>)}{threads.length === 0 ? <div className="empty-box">Чатов пока нет.</div> : null}</div>
      </div>
    </div>
  );
}

function InteractionSetupModal({ open, user, bootstrap, onOpenProfile, onDismiss }) {
  if (!open) return null;
  const toneOptions = referenceOptions(bootstrap, 'assistant_tones', user?.assistant_profile?.tone || 'business');
  const answerDepthOptions = referenceOptions(bootstrap, 'assistant_answer_depths', user?.assistant_profile?.answer_depth || 'balanced');
  const interactionModeOptions = referenceOptions(bootstrap, 'assistant_interaction_modes', user?.assistant_profile?.interaction_mode || 'clarify_when_needed');
  return (
    <div className="modal-backdrop-react interaction-setup-backdrop" onClick={onDismiss}>
      <div className="modal-react modal-react-narrow interaction-setup-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header-react">
          <div>
            <h3>Давай настроим, как с тобой взаимодействовать</h3>
            <div className="muted">Это помогает сделать ответы точнее и ближе к твоему рабочему контексту.</div>
          </div>
        </div>
        <div className="stack">
          <div className="chat-onboarding-points interaction-setup-points">
            <div><strong>1</strong><span>Укажи рабочий контекст: команда, роль, цели и ограничения.</span></div>
            <div><strong>2</strong><span>Выбери, как отвечать по умолчанию: деловой стиль, глубина и режим взаимодействия.</span></div>
            <div><strong>3</strong><span>После этого чат будет лучше держать рамку обсуждения и меньше требовать повторных пояснений.</span></div>
          </div>
          <div className="profile-next-step">
            <strong>{user?.name || user?.email || 'Новый пользователь'}</strong>
            <div className="muted small">Можешь настроить профиль сейчас или вернуться к этому позже — по умолчанию оставлю тебя в чатах.</div>
            <div className="summary-grid summary-grid-tight onboarding-reference-grid">
              <div className="summary-box"><span>Тон по умолчанию</span><strong>{toneOptions[0]?.label || 'Деловой'}</strong></div>
              <div className="summary-box"><span>Глубина</span><strong>{answerDepthOptions[0]?.label || 'Сбалансированная'}</strong></div>
              <div className="summary-box"><span>Манера</span><strong>{interactionModeOptions[0]?.label || 'Уточнять по необходимости'}</strong></div>
            </div>
          </div>
          <div className="head-actions onboarding-actions">
            <button className="primary-btn" onClick={onOpenProfile} type="button">Настроить сейчас</button>
            <button className="ghost-btn" onClick={onDismiss} type="button">Позже, остаться в чатах</button>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function App() {
  const [serviceInfo, setServiceInfo] = useState(null);
  const [setupRequired, setSetupRequired] = useState(false);
  const [booting, setBooting] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [loginForm, setLoginForm] = useState(EMPTY_LOGIN);
  const [setupForm, setSetupForm] = useState(EMPTY_SETUP);
  const [composerText, setComposerText] = useState('');
  const [composerFiles, setComposerFiles] = useState([]);
  const [composerExistingFiles, setComposerExistingFiles] = useState([]);
  const [requestPolicyDraft, setRequestPolicyDraft] = useState(initialRequestExecutionPolicy());
  const [profileForm, setProfileForm] = useState(profileFormFromUser(null));
  const [passwordForm, setPasswordForm] = useState({ currentPassword: '', newPassword: '' });
  const [appState, setAppState] = useState(initialAppState());
  const [profileSection, setProfileSection] = useState('summary');
  const [profileFileQuery, setProfileFileQuery] = useState('');
  const [profileFileType, setProfileFileType] = useState('all');
  const [threadsModalOpen, setThreadsModalOpen] = useState(false);
  const [jobModalOpen, setJobModalOpen] = useState(false);
  const [jobMembersModal, setJobMembersModal] = useState({ open: false, mode: 'recipients', job: null });
  const [jobDraft, setJobDraft] = useState(initialJobDraft(MOSCOW_TIMEZONE));
  const [editingJobId, setEditingJobId] = useState(null);
  const [adminUserForm, setAdminUserForm] = useState(adminUserFormFromUser());
  const [adminUserHistory, setAdminUserHistory] = useState([]);
  const [adminUserModalOpen, setAdminUserModalOpen] = useState(false);
  const [selectedUserIds, setSelectedUserIds] = useState([]);
  const [importCsv, setImportCsv] = useState('');
  const [activeDatasetKey, setActiveDatasetKey] = useState('');
  const [referenceDraft, setReferenceDraft] = useState(null);
  const [referenceHistory, setReferenceHistory] = useState([]);
  const [selectedReferenceItems, setSelectedReferenceItems] = useState({});
  const [dataPolicyDraft, setDataPolicyDraft] = useState(cloneDataPolicyForDraft());
  const [interactionSetupOpen, setInteractionSetupOpen] = useState(false);
  const [previewFile, setPreviewFile] = useState(null);
  const [hiddenObjects, setHiddenObjects] = useState(readHiddenObjects());
  const uiStateRef = useRef(readUiState());

  useEffect(() => {
    if (!appState.authenticated) {
      if (!booting) {
        const nextUiState = {
          screen: 'chat',
          activeThreadId: null,
          activeJobId: null,
          adminSection: sanitizeAdminSection(appState.admin?.section),
        };
        uiStateRef.current = nextUiState;
        writeUiState(nextUiState);
      }
      return;
    }
    const nextUiState = {
      screen: sanitizeScreen(appState.screen, appState.user?.role),
      activeThreadId: appState.activeThreadId ?? null,
      activeJobId: appState.activeJobId ?? null,
      adminSection: sanitizeAdminSection(appState.admin?.section),
    };
    uiStateRef.current = nextUiState;
    writeUiState(nextUiState);
  }, [booting, appState.authenticated, appState.screen, appState.activeThreadId, appState.activeJobId, appState.admin?.section, appState.user?.role]);

  useEffect(() => {
    writeHiddenObjects(hiddenObjects);
  }, [hiddenObjects]);

  useEffect(() => {
    if (typeof window === 'undefined' || typeof document === 'undefined') return undefined;
    const ua = window.navigator?.userAgent || '';
    const isIPhone = /iPhone/i.test(ua);
    if (!isIPhone) return undefined;
    const viewportMeta = document.querySelector('meta[name=\"viewport\"]');
    if (!viewportMeta) return undefined;
    const originalViewport = viewportMeta.getAttribute('content') || 'width=device-width, initial-scale=1.0, viewport-fit=cover';
    const focusedViewport = 'width=device-width, initial-scale=1.0, maximum-scale=1.0, viewport-fit=cover';
    const restoreViewport = () => viewportMeta.setAttribute('content', originalViewport);
    const handleFocusIn = (event) => {
      const target = event.target;
      if (!(target instanceof HTMLElement)) return;
      if (!target.matches('textarea, input[type=\"text\"], input[type=\"search\"], input[type=\"email\"], input[type=\"url\"], input[type=\"tel\"], input[type=\"password\"]')) return;
      viewportMeta.setAttribute('content', focusedViewport);
      window.setTimeout(() => {
        try { target.scrollIntoView({ block: 'center', inline: 'nearest' }); } catch {}
      }, 120);
    };
    const handleFocusOut = () => {
      window.setTimeout(() => {
        restoreViewport();
        try { window.scrollTo(0, 0); } catch {}
      }, 180);
    };
    document.addEventListener('focusin', handleFocusIn);
    document.addEventListener('focusout', handleFocusOut);
    return () => {
      document.removeEventListener('focusin', handleFocusIn);
      document.removeEventListener('focusout', handleFocusOut);
      restoreViewport();
    };
  }, []);

  function clearMessages() { setError(''); setNotice(''); }
  function updateBusy(value) { setBusy(value); }

  async function loadPublicState() {
    const [info, setup] = await Promise.all([api.getServiceInfo(), api.getSetupStatus()]);
    setServiceInfo(info);
    setSetupRequired(Boolean(setup.needs_setup));
  }

  async function loadCoreState({ keepScreen = null } = {}) {
    const [me, bootstrap, threadResult, reasons, files, jobsMeta] = await Promise.allSettled([api.getMe(), api.getBootstrap(), api.getThreads(), api.getFeedbackReasons(), api.getFiles(), api.getJobsMeta()]);
    if (me.status !== 'fulfilled') throw me.reason;
    if (bootstrap.status !== 'fulfilled') throw bootstrap.reason;
    if (threadResult.status !== 'fulfilled') throw threadResult.reason;
    if (files.status !== 'fulfilled') throw files.reason;
    if (jobsMeta.status !== 'fulfilled') throw jobsMeta.reason;
    const savedHidden = readHiddenObjects();
    const threads = filterHiddenItems(threadResult.value.threads || [], savedHidden.threads);
    const activeThreads = threads.filter((thread) => !thread.archived);
    const feedbackReasons = reasons.status === 'fulfilled' ? (reasons.value.reasons || []) : [];
    const userFiles = filterHiddenItems(files.value.files || [], savedHidden.files, fileHideKey);
    const jobsMetaValue = jobsMeta.value;
    const savedUiState = uiStateRef.current || readUiState();
    const role = me.value.user?.role || 'user';
    const activeThreadId = pickExistingId(activeThreads, null, null) || pickExistingId(threads, null, null);
    let messages = [];
    let threadFiles = [];
    if (activeThreadId) {
      const threadPayload = await api.getThread(activeThreadId);
      messages = threadPayload.messages || [];
      threadFiles = resolveThreadFiles(threadPayload);
    }
    setProfileForm(profileFormFromUser(me.value.user));
    const shouldOpenInteractionSetup = needsInteractionSetup(me.value.user);
    setInteractionSetupOpen(shouldOpenInteractionSetup);
    setProfileSection(shouldOpenInteractionSetup ? 'response' : 'summary');
    const normalizedDataPolicy = normalizeDataPolicyShape(bootstrap.value?.dashboard_policy, bootstrap.value?.data_sources || []);
    const normalizedBootstrap = { ...bootstrap.value, data_policy: normalizedDataPolicy };
    setRequestPolicyDraft(initialRequestExecutionPolicy({ ...normalizedDataPolicy.processing_policy, model_preference: bootstrap.value?.llm_routing?.selector?.default || 'auto' }));
    setDataPolicyDraft(cloneDataPolicyForDraft(normalizedDataPolicy));
    const nextScreen = sanitizeScreen(keepScreen || savedUiState.screen || appState.screen || 'chat', role);
    const visibleActiveThreadId = pickExistingId(activeThreads, activeThreadId, null);
    const visibleMessages = visibleActiveThreadId && String(visibleActiveThreadId) === String(activeThreadId) ? messages : [];
    const visibleThreadFiles = filterHiddenItems(threadFiles, savedHidden.files, fileHideKey);
    setAppState((prev) => ({ ...prev, authenticated: true, screen: nextScreen, user: me.value.user, personalization: me.value.personalization || '', profileSummary: me.value.profile_summary || null, bootstrap: normalizedBootstrap, feedbackReasons, threads, activeThreadId: visibleActiveThreadId, chatWelcomeDismissed: visibleMessages.length > 0 ? true : prev.chatWelcomeDismissed, messages: visibleMessages, userFiles, threadFiles: visibleThreadFiles, jobsMeta: jobsMetaValue, jobs: prev.jobs || [], activeJobId: prev.activeJobId || savedUiState.activeJobId || null, activeJob: prev.activeJob || null, admin: { ...(prev.admin || initialAppState().admin), section: sanitizeAdminSection(savedUiState.adminSection || prev.admin?.section) } }));
  }

  async function loadJobs(selectFirst = false) {
    const jobsResult = await api.getJobs('all');
    const savedHidden = readHiddenObjects();
    const jobs = filterHiddenItems(jobsResult.jobs || [], savedHidden.jobs);
    const savedUiState = uiStateRef.current || readUiState();
    let activeJobId = selectFirst ? null : pickExistingId(jobs, appState.activeJobId, savedUiState.activeJobId);
    if (!activeJobId && jobs.length > 0) activeJobId = jobs[0]?.id || null;
    let activeJob = null;
    if (activeJobId) {
      try {
        activeJob = (await api.getJob(activeJobId)).job || null;
      } catch (error) {
        if (!(error instanceof ApiError) || ![403, 404].includes(error.status || 0)) throw error;
        activeJobId = jobs[0]?.id || null;
        activeJob = null;
        if (activeJobId) {
          activeJob = (await api.getJob(activeJobId)).job || null;
        }
      }
    }
    setAppState((prev) => ({ ...prev, jobs, activeJobId, activeJob }));
  }

  async function loadJob(jobId) {
    const detail = await api.getJob(jobId);
    setAppState((prev) => ({ ...prev, activeJobId: jobId, activeJob: detail.job || null, jobs: prev.jobs.map((job) => (String(job.id) === String(jobId) ? { ...job, ...(detail.job || {}) } : job)) }));
  }

  async function loadAdmin(force = false, nextSection = null) {
    if (appState.user?.role !== 'admin') return;
    const savedUiState = uiStateRef.current || readUiState();
    const requestedSection = sanitizeAdminSection(nextSection || savedUiState.adminSection || appState.admin.section || 'overview');
    const tasks = [api.getAdminHealth(), api.getAdminUsers(), api.getAdminThreads(), api.getAdminJobs(), api.getAdminReferenceData(), api.getAdminChatNotice()];
    if (force || requestedSection === 'operations') tasks.push(api.getAdminEvents(appState.admin.eventsFilters));
    else tasks.push(Promise.resolve(null));
    if (force || requestedSection === 'data_policy') tasks.push(api.getAdminDashboardPolicy());
    else tasks.push(Promise.resolve(null));
    const [health, users, threads, jobs, references, chatNotice, eventsData, dataPolicyData] = await Promise.all(tasks);
    const resolvedDataPolicy = dataPolicyData ? normalizeDataPolicyShape(dataPolicyData.dashboard_policy, dataPolicyData.data_sources || []) : null;
    setAppState((prev) => ({
      ...prev,
      admin: {
        ...prev.admin,
        section: requestedSection,
        health,
        users: users.users || [],
        threads: threads.threads || [],
        jobs: jobs.jobs || [],
        references: references.references || {},
        chatNotice: chatNotice.chat_notice || null,
        dataPolicy: resolvedDataPolicy || prev.admin.dataPolicy,
        events: eventsData?.events || prev.admin.events,
        loaded: true,
      }
    }));
    if (resolvedDataPolicy) setDataPolicyDraft(cloneDataPolicyForDraft(resolvedDataPolicy));
    if (!activeDatasetKey) setActiveDatasetKey(Object.keys(references.references || {})[0] || '');
  }

  useEffect(() => {
    async function bootstrapApp() {
      try {
        await loadPublicState();
        if (getStoredToken()) {
          await api.restoreSession();
          const savedUiState = uiStateRef.current || readUiState();
          await loadCoreState({ keepScreen: savedUiState.screen || null });
        }
      } catch (err) {
        setStoredToken('');
        setError(err instanceof ApiError ? err.message : 'Не удалось инициализировать React-frontend.');
      } finally { setBooting(false); }
    }
    bootstrapApp();
  }, []);

  useEffect(() => {
    if (!appState.authenticated || appState.screen !== 'chat' || !appState.activeThreadId) return undefined;
    let cancelled = false;
    let inFlight = false;
    const activeThreadId = appState.activeThreadId;

    const refreshChatState = async () => {
      if (inFlight) return;
      inFlight = true;
      try {
        const hasPendingAssistant = (appState.messages || []).some((message) => message?.role === 'assistant' && message?.meta?.pending);
        const [threadsResult, threadPayload, filesResult] = await Promise.all([
          api.getThreads(),
          api.getThread(activeThreadId),
          hasPendingAssistant ? api.getFiles() : Promise.resolve(null),
        ]);
        if (cancelled) return;
        setAppState((prev) => {
          if (String(prev.activeThreadId) !== String(activeThreadId)) return prev;
          return {
            ...prev,
            threads: filterHiddenItems(threadsResult.threads || prev.threads, readHiddenObjects().threads),
            messages: threadPayload.messages || prev.messages,
            threadFiles: filterHiddenItems(resolveThreadFiles(threadPayload) || prev.threadFiles, readHiddenObjects().files, fileHideKey),
            userFiles: filterHiddenItems(filesResult?.files || prev.userFiles, readHiddenObjects().files, fileHideKey),
            chatWelcomeDismissed: (threadPayload.messages || []).length > 0 ? true : prev.chatWelcomeDismissed,
          };
        });
      } catch {
      } finally {
        inFlight = false;
      }
    };

    const hasPendingAssistant = (appState.messages || []).some((message) => message?.role === 'assistant' && message?.meta?.pending);
    const intervalMs = hasPendingAssistant ? 2500 : 8000;
    refreshChatState();
    const timer = window.setInterval(refreshChatState, intervalMs);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [appState.authenticated, appState.screen, appState.activeThreadId, appState.messages]);

  function withAsync(handler) {
    return async (...args) => {
      clearMessages();
      updateBusy(true);
      try { await handler(...args); }
      catch (err) { setError(err instanceof Error ? err.message : 'Неизвестная ошибка'); }
      finally { updateBusy(false); }
    };
  }

  const handleLogin = withAsync(async (event) => { event.preventDefault(); const result = await api.login(loginForm.email.trim(), loginForm.password); setStoredToken(result.token); await loadCoreState(); });
  const handleSetup = withAsync(async (event) => { event.preventDefault(); await api.bootstrapAdmin({ name: setupForm.name.trim() || 'Administrator', email: setupForm.email.trim(), password: setupForm.password }); await loadPublicState(); setSetupRequired(false); setLoginForm({ email: setupForm.email.trim(), password: setupForm.password }); setSetupForm(EMPTY_SETUP); setNotice('Администратор создан. Теперь можно войти.'); });
  const handleLogout = withAsync(async () => { try { await api.logout(); } catch {} setStoredToken(''); uiStateRef.current = { screen: 'chat', activeThreadId: null, activeJobId: null, adminSection: 'overview' }; writeUiState(uiStateRef.current); setComposerText(''); setComposerFiles([]); setComposerExistingFiles([]); setRequestPolicyDraft(initialRequestExecutionPolicy()); setDataPolicyDraft(cloneDataPolicyForDraft()); setProfileForm(profileFormFromUser(null)); setPasswordForm({ currentPassword: '', newPassword: '' }); setProfileSection('summary'); setProfileFileQuery(''); setProfileFileType('all'); setThreadsModalOpen(false); setAppState(initialAppState()); await loadPublicState(); });
  const handleCreateThread = withAsync(async () => { const result = await api.createThread(); const threads = (await api.getThreads()).threads || []; const threadPayload = await api.getThread(result.thread.id); setAppState((prev) => ({ ...prev, screen: 'chat', threads, activeThreadId: result.thread.id, chatWelcomeDismissed: false, messages: threadPayload.messages || [], threadFiles: resolveThreadFiles(threadPayload) })); setThreadsModalOpen(false); setNotice('Новый чат создан.'); });
  const handleSelectThread = withAsync(async (threadId) => { const payload = await api.getThread(threadId); setAppState((prev) => ({ ...prev, screen: 'chat', activeThreadId: payload.thread.id, chatWelcomeDismissed: false, messages: payload.messages || [], threadFiles: resolveThreadFiles(payload), threads: prev.threads.map((thread) => String(thread.id) === String(payload.thread.id) ? payload.thread : thread) })); setThreadsModalOpen(false); });
  const handleRenameThread = withAsync(async () => { const thread = appState.threads.find((item) => String(item.id) === String(appState.activeThreadId)); if (!thread) return; const title = window.prompt('Новое название чата', thread.title || ''); if (!title || title.trim() === thread.title) return; await api.updateThread(thread.id, { title: title.trim(), version: thread.version ?? 1 }); const [threads, payload] = await Promise.all([api.getThreads(), api.getThread(thread.id)]); setAppState((prev) => ({ ...prev, threads: threads.threads || prev.threads, messages: payload.messages || prev.messages })); setNotice('Название чата обновлено.'); });
  const handleToggleArchiveThread = withAsync(async (threadId = null) => {
    const targetThreadId = threadId ?? appState.activeThreadId;
    const thread = appState.threads.find((item) => String(item.id) === String(targetThreadId));
    if (!thread) return;
    const nextArchived = !thread.archived;
    await api.updateThread(thread.id, { archived: nextArchived, version: thread.version ?? 1 });
    const threads = (await api.getThreads()).threads || [];
    const isActiveThreadTarget = String(appState.activeThreadId) === String(thread.id);
    const restoredThread = threads.find((item) => String(item.id) === String(thread.id)) || null;
    const nextActiveThread = threads.find((item) => !item.archived && String(item.id) !== String(thread.id)) || null;
    const activeThreadId = isActiveThreadTarget
      ? (nextArchived ? (nextActiveThread?.id || null) : (restoredThread?.id || appState.activeThreadId))
      : appState.activeThreadId;
    let messages = appState.messages;
    let threadFiles = appState.threadFiles;
    if (activeThreadId && String(activeThreadId) !== String(appState.activeThreadId)) {
      const threadPayload = await api.getThread(activeThreadId);
      messages = threadPayload.messages || [];
      threadFiles = resolveThreadFiles(threadPayload);
    }
    if (!activeThreadId) {
      messages = [];
      threadFiles = [];
    }
    setAppState((prev) => ({ ...prev, screen: 'chat', threads, activeThreadId, messages, threadFiles, chatWelcomeDismissed: activeThreadId ? prev.chatWelcomeDismissed : false }));
    setNotice(nextArchived ? 'Чат перенесён в архив и скрыт с основной страницы.' : 'Чат возвращён из архива в активные.');
  });
  const handleArchiveThread = withAsync(async () => { await handleToggleArchiveThread(appState.activeThreadId); });
  const handleAdminOpenThread = withAsync(async (threadId) => { if (!threadId) return; await handleSelectThread(threadId); setAppState((prev) => ({ ...prev, screen: 'chat' })); setNotice('Чат открыт из управления.'); });
  const handleOpenUserFile = withAsync(async (file) => {
    if (!file) return;
    if (isImageFile(file)) {
      setPreviewFile({ ...file, download_url: filePreviewUrl(file) });
      return;
    }
    await api.openFile(file);
  });
  const handleDeleteFile = withAsync(async (file) => {
    if (!file) return;
    const key = fileHideKey(file);
    if (!key) return;
    setHiddenObjects((prev) => ({ ...prev, files: Array.from(new Set([...(prev.files || []), String(key)])) }));
    setComposerExistingFiles((prev) => prev.filter((item) => String(fileHideKey(item)) !== String(key)));
    setAppState((prev) => ({ ...prev, userFiles: filterHiddenItems(prev.userFiles, [key], fileHideKey), threadFiles: filterHiddenItems(prev.threadFiles, [key], fileHideKey) }));
    setNotice('Файл скрыт с фронта.');
  });
  const handleDeleteThread = withAsync(async () => {
    const threadId = appState.activeThreadId;
    if (!threadId) return;
    setHiddenObjects((prev) => ({ ...prev, threads: Array.from(new Set([...(prev.threads || []), String(threadId)])) }));
    const visibleThreads = appState.threads.filter((thread) => String(thread.id) !== String(threadId));
    const nextActiveThreadId = visibleThreads.find((thread) => !thread.archived)?.id || visibleThreads[0]?.id || null;
    let nextMessages = [];
    let nextThreadFiles = [];
    if (nextActiveThreadId) {
      const payload = await api.getThread(nextActiveThreadId);
      nextMessages = payload.messages || [];
      nextThreadFiles = filterHiddenItems(resolveThreadFiles(payload), hiddenObjects.files, fileHideKey);
    }
    setAppState((prev) => ({ ...prev, threads: visibleThreads, activeThreadId: nextActiveThreadId, messages: nextMessages, threadFiles: nextThreadFiles }));
    setNotice('Чат скрыт с фронта.');
  });
  const handleDeleteJob = withAsync(async (job) => {
    if (!job) return;
    if (job.status !== 'paused') await api.updateJob(job.id, { status: 'paused', version: job.version ?? 1 });
    setHiddenObjects((prev) => ({ ...prev, jobs: Array.from(new Set([...(prev.jobs || []), String(job.id)])) }));
    const visibleJobs = appState.jobs.filter((item) => String(item.id) !== String(job.id));
    const nextActiveJobId = visibleJobs[0]?.id || null;
    setAppState((prev) => ({ ...prev, jobs: visibleJobs, activeJobId: nextActiveJobId, activeJob: nextActiveJobId && prev.activeJob && String(prev.activeJob.id) !== String(job.id) ? prev.activeJob : null }));
    if (nextActiveJobId) await loadJob(nextActiveJobId);
    if (appState.user?.role === 'admin') await loadAdmin(true);
    setNotice('Задача поставлена на паузу и скрыта с фронта.');
  });
  const handleOpenAttachment = withAsync(async (file) => {
    if (!file) return;
    if (isImageFile(file)) {
      setPreviewFile({ ...file, download_url: filePreviewUrl(file) });
      return;
    }
    await api.openFile(file);
  });
  const handleExportMessage = withAsync(async (message, format = 'docx') => {
    if (!message?.id) return;
    const result = await api.exportMessage(message.id, format);
    setNotice(result?.name ? `Файл ${result.name} подготовлен к скачиванию.` : `Экспорт ${String(format).toUpperCase()} запущен.`);
  });
  const handleSend = withAsync(async (event) => {
    event.preventDefault();
    const textValue = composerText.trim();
    if (!textValue && composerFiles.length === 0 && composerExistingFiles.length === 0) return;
    const pendingFiles = [...composerFiles];
    const reusedFiles = [...composerExistingFiles];
    const requestPolicyPayload = {
      ...requestPolicyDraft,
      source_mode: requestPolicyDraft.search_mode_override || null,
      model_preference: requestPolicyDraft.model_preference || null,
      explicit_source_ids: Array.isArray(requestPolicyDraft.selected_source_ids) ? requestPolicyDraft.selected_source_ids : [],
      search_mode_override: requestPolicyDraft.search_mode_override || null,
      selected_source_ids: Array.isArray(requestPolicyDraft.selected_source_ids) ? requestPolicyDraft.selected_source_ids : [],
      allow_external_for_this_request: requestPolicyDraft.allow_external_for_this_request ?? null,
    };
    let threadId = appState.activeThreadId;
    if (!threadId) {
      const created = await api.createThread();
      threadId = created.thread.id;
    }
    const optimisticAttachments = [
      ...pendingFiles.map((file) => ({
        original_name: file.name,
        mime_type: file.type || 'application/octet-stream',
        size_bytes: file.size,
        text_extracted: false,
        preview_text: '',
      })),
      ...reusedFiles.map((file) => ({
        original_name: file.original_name,
        mime_type: file.mime_type || 'application/octet-stream',
        size_bytes: file.size_bytes || 0,
        text_extracted: Boolean(file.text_extracted),
        preview_text: file.preview_text || '',
      })),
    ];
    const optimisticContent = optimisticAttachments.length > 0
      ? `${textValue}${textValue ? '\n\n' : ''}Файлы прикреплены. Отправка в обработке…`
      : textValue;
    const optimisticMessageId = `temp-user-${Date.now()}`;
    const pendingAssistantId = `temp-assistant-${Date.now()}`;
    const optimisticMessage = {
      id: optimisticMessageId,
      role: 'user',
      content: optimisticContent,
      created_at: new Date().toISOString(),
      meta: {
        user_text: textValue,
        attachments: optimisticAttachments,
        request_execution_policy: requestPolicyPayload,
      },
    };
    const pendingAssistantMessage = {
      id: pendingAssistantId,
      role: 'assistant',
      content: 'Готовлю ответ…',
      created_at: new Date().toISOString(),
      meta: {
        pending: true,
        attachments: [],
      },
    };
    setAppState((prev) => ({
      ...prev,
      screen: 'chat',
      activeThreadId: threadId,
      chatWelcomeDismissed: true,
      messages: [...(prev.messages || []), optimisticMessage, pendingAssistantMessage],
    }));
    setComposerText('');
    setComposerFiles([]);
    setComposerExistingFiles([]);
    try {
      if (pendingFiles.length > 0 || reusedFiles.length > 0) {
        const form = new FormData();
        form.append('content', textValue);
        form.append('request_execution_policy', JSON.stringify(requestPolicyPayload));
        pendingFiles.forEach((file) => form.append('files', file));
        reusedFiles.forEach((file) => form.append('existing_file_ids', String(file.id)));
        await api.sendMessage(threadId, form);
      } else {
        await api.sendMessage(threadId, { content: textValue, request_execution_policy: requestPolicyPayload });
      }
      const [threadResult, threadPayload, files] = await Promise.all([api.getThreads(), api.getThread(threadId), api.getFiles()]);
      setAppState((prev) => ({
        ...prev,
        threads: threadResult.threads || prev.threads,
        activeThreadId: threadId,
        chatWelcomeDismissed: true,
        messages: threadPayload.messages || [],
        threadFiles: resolveThreadFiles(threadPayload) || prev.threadFiles,
        userFiles: files.files || prev.userFiles,
      }));
    } catch (err) {
      setAppState((prev) => ({
        ...prev,
        messages: (prev.messages || []).map((message) => String(message.id) === pendingAssistantId ? { ...message, content: 'Не удалось получить ответ. Проверьте отправку сообщения или файлов и повторите попытку.', meta: { ...(message.meta || {}), pending: false, error: true } } : message),
      }));
      throw err;
    }
  });
  const handleProfileChange = (event) => setProfileForm((prev) => ({ ...prev, [event.target.name]: event.target.value }));
  const handlePasswordChange = (event) => setPasswordForm((prev) => ({ ...prev, [event.target.name]: event.target.value }));
  const handleDismissChatWelcome = () => setAppState((prev) => ({ ...prev, chatWelcomeDismissed: true }));
  const handleApplyStarterPrompt = (prompt) => {
    setComposerText(String(prompt || '').trim());
    setAppState((prev) => ({ ...prev, chatWelcomeDismissed: true }));
  };
  const handleComposerKeyDown = (event) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      event.currentTarget.form?.requestSubmit();
    }
  };
  const handleProfileFileFilterChange = (field, value) => {
    if (field === 'query') setProfileFileQuery(value);
    if (field === 'type') setProfileFileType(value);
  };
  const handleSaveProfile = withAsync(async () => { const payload = { version: appState.user?.version ?? 1, name: profileForm.name.trim(), timezone: profileForm.timezone.trim(), language: profileForm.language.trim(), team: profileForm.team.trim(), title: profileForm.title.trim(), goals: profileForm.goals.trim(), style: `${profileForm.tone}, ${profileForm.answer_depth}, ${profileForm.interaction_mode}`, constraints: profileForm.constraints.trim(), pinned: profileForm.pinned.split('\n').map((item) => item.trim()).filter(Boolean), assistant_profile: { tone: profileForm.tone, answer_depth: profileForm.answer_depth, interaction_mode: profileForm.interaction_mode, about_user: profileForm.about_user.trim() } }; const data = await api.saveMe(payload); setProfileForm(profileFormFromUser(data.user)); setInteractionSetupOpen(false); setAppState((prev) => ({ ...prev, user: data.user, profileSummary: data.profile_summary || prev.profileSummary, personalization: data.personalization || prev.personalization })); setNotice('Профиль сохранён.'); });
  const handleChangePassword = withAsync(async () => { await api.changePassword(passwordForm.currentPassword, passwordForm.newPassword); setPasswordForm({ currentPassword: '', newPassword: '' }); setNotice('Пароль обновлён. Остальные сессии пользователя отозваны.'); });
  const handleNavigate = withAsync(async (screen) => {
    setInteractionSetupOpen(false);
    setAppState((prev) => ({ ...prev, screen }));
    if (screen === 'profile') setProfileSection((prev) => prev || 'summary');
    if (screen === 'jobs') await loadJobs(appState.jobs.length === 0);
    if (screen === 'admin' && appState.user?.role === 'admin') await loadAdmin(!appState.admin.loaded);
  });
  const handleSelectJob = withAsync(async (jobId) => { if (appState.jobs.length === 0) await loadJobs(); await loadJob(jobId); });
  const handleRunJob = withAsync(async (jobId) => { await api.runJob(jobId); await loadJobs(false); await loadJob(jobId); if (appState.user?.role === 'admin') await loadAdmin(true); setNotice('Запуск задачи отправлен.'); });
  const handleToggleSubscribe = withAsync(async (job) => { if (job.subscription?.subscribed || job.is_subscribed) await api.unsubscribeJob(job.id); else await api.subscribeJob(job.id); await loadJob(job.id); const jobsResult = await api.getJobs('all'); setAppState((prev) => ({ ...prev, jobs: jobsResult.jobs || prev.jobs })); setNotice(job.subscription?.subscribed || job.is_subscribed ? 'Подписка отключена.' : 'Подписка включена.'); });
  const handleToggleJobStatus = withAsync(async (job) => { await api.updateJob(job.id, { status: job.status === 'paused' ? 'active' : 'paused', version: job.version ?? 1 }); await loadJobs(false); await loadJob(job.id); if (appState.user?.role === 'admin') await loadAdmin(true); setNotice(job.status === 'paused' ? 'Задача возобновлена.' : 'Задача поставлена на паузу.'); });
  const handleUpdateDisplayName = withAsync(async (jobId, displayName) => { const current = appState.activeJob; if (!current) return; await api.updateJob(jobId, { display_name: displayName.trim(), version: current.version ?? 1 }); await loadJobs(false); await loadJob(jobId); setNotice(displayName.trim() ? 'Общее название сохранено.' : 'Общее название очищено.'); });
  const handleSaveNotice = withAsync(async (enabled, text) => { const result = await api.saveAdminChatNotice({ enabled, text: text.trim() }); setAppState((prev) => ({ ...prev, bootstrap: { ...(prev.bootstrap || {}), chat_notice: result.chat_notice }, admin: { ...prev.admin, chatNotice: result.chat_notice } })); setNotice('Объявление обновлено.'); });
  const handleOpenInteractionSetup = () => { setInteractionSetupOpen(false); setProfileSection('response'); setAppState((prev) => ({ ...prev, screen: 'profile' })); setNotice('Открыла профиль на настройках взаимодействия.'); };
  const handleRequestPolicyChange = (field, value) => setRequestPolicyDraft((prev) => ({ ...prev, [field]: value }));
  const handleToggleRequestSource = (sourceKey) => setRequestPolicyDraft((prev) => {
    const current = new Set(prev.selected_source_ids || []);
    current.has(sourceKey) ? current.delete(sourceKey) : current.add(sourceKey);
    return { ...prev, selected_source_ids: Array.from(current) };
  });
  const handleDataPolicyDraftChange = (scope, payload) => setDataPolicyDraft((prev) => {
    if (scope === 'source_field') {
      const items = [...(prev.source_registry?.items || [])];
      if (!items[payload.index]) return prev;
      items[payload.index] = { ...items[payload.index], [payload.field]: payload.value };
      return { ...prev, source_registry: { ...(prev.source_registry || {}), items } };
    }
    if (scope === 'connector_assignment') {
      const connectorKey = String(payload.connector_key || '').trim();
      const targetGroup = String(payload.value || '').trim();
      if (!connectorKey) return prev;
      const currentTargets = prev.processing_policy?.connector_targets || {};
      const nextTargets = {
        internal_connector: Array.isArray(currentTargets.internal_connector) ? [...currentTargets.internal_connector] : [],
        external_connector: Array.isArray(currentTargets.external_connector) ? [...currentTargets.external_connector] : [],
      };
      nextTargets.internal_connector = nextTargets.internal_connector.filter((item) => item !== connectorKey);
      nextTargets.external_connector = nextTargets.external_connector.filter((item) => item !== connectorKey);
      if (targetGroup === 'internal_connector' || targetGroup === 'external_connector') {
        nextTargets[targetGroup].push(connectorKey);
      }
      return { ...prev, processing_policy: { ...(prev.processing_policy || {}), connector_targets: nextTargets } };
    }
    if (scope === 'policy_field') {
      const nextValue = payload.field === 'source_selection_order'
        ? String(payload.value || '').split(',').map((item) => item.trim()).filter(Boolean)
        : payload.value;
      return { ...prev, processing_policy: { ...(prev.processing_policy || {}), [payload.field]: nextValue } };
    }
    return prev;
  });
  const handleSaveDataPolicy = withAsync(async () => {
    const enabledSources = (dataPolicyDraft.source_registry?.items || []).filter((item) => item.enabled).map((item) => item.source_key || item.item_key);
    const fallbackExternalSource = (dataPolicyDraft.source_registry?.items || []).find((item) => item.enabled && item.origin === 'external')?.source_key || 'web_research';
    const connectorTargets = dataPolicyDraft.processing_policy?.connector_targets || {};
    const connectorGroupOverrides = {};
    Object.entries(connectorTargets).forEach(([groupKey, keys]) => {
      if (!Array.isArray(keys)) return;
      keys.forEach((connectorKey) => {
        if (connectorKey) connectorGroupOverrides[connectorKey] = groupKey;
      });
    });
    const policyPayload = {
      source_mode: dataPolicyDraft.processing_policy?.default_mode || SOURCE_MODE_LOCAL_FIRST,
      allowed_sources: enabledSources,
      default_global_source: dataPolicyDraft.processing_policy?.default_global_source || fallbackExternalSource,
      connector_targets: connectorTargets,
      connector_group_overrides: connectorGroupOverrides,
      notes: dataPolicyDraft.processing_policy?.notes || '',
    };
    const policyResult = await api.saveAdminDashboardPolicy(policyPayload);
    const mergedPolicy = normalizeDataPolicyShape(policyResult.dashboard_policy, policyResult.data_sources || []);
    setDataPolicyDraft(cloneDataPolicyForDraft(mergedPolicy));
    setRequestPolicyDraft((prev) => ({ ...initialRequestExecutionPolicy({ ...mergedPolicy.processing_policy, model_preference: prev.model_preference || 'auto' }), model_preference: prev.model_preference || 'auto' }));
    setAppState((prev) => ({
      ...prev,
      bootstrap: { ...(prev.bootstrap || {}), data_policy: mergedPolicy, dashboard_policy: policyResult.dashboard_policy, data_sources: policyResult.data_sources || [] },
      admin: { ...prev.admin, dataPolicy: mergedPolicy },
    }));
    setNotice('Policy источников обновлена.');
  });
  const toggleExistingFile = (file) => setComposerExistingFiles((prev) => prev.some((item) => Number(item.id) === Number(file.id)) ? prev.filter((item) => Number(item.id) !== Number(file.id)) : [...prev, file]);

  const ensureJobsContextLoaded = async ({ refreshMeta = false } = {}) => {
    let jobsMetaValue = appState.jobsMeta;
    if (refreshMeta || !jobsMetaValue) {
      jobsMetaValue = await api.getJobsMeta();
      setAppState((prev) => ({ ...prev, jobsMeta: jobsMetaValue }));
    }
    if (!appState.jobs.length) await loadJobs(true);
    return jobsMetaValue;
  };

  const openCreateJob = withAsync(async () => {
    await ensureJobsContextLoaded();
    setEditingJobId(null);
    setAppState((prev) => ({ ...prev, screen: 'jobs' }));
    setJobDraft(initialJobDraft(appState.user?.timezone || MOSCOW_TIMEZONE));
    setJobModalOpen(true);
  });
  const openCreateJobForUser = withAsync(async (user) => {
    await ensureJobsContextLoaded();
    setEditingJobId(null);
    setAppState((prev) => ({ ...prev, screen: 'jobs' }));
    setJobDraft(buildAssignedUserJobDraft(user, appState.user?.timezone || MOSCOW_TIMEZONE));
    setJobModalOpen(true);
  });
  const openCreateDashboardRefreshJob = (message) => { setEditingJobId(null); setAppState((prev) => ({ ...prev, screen: 'jobs' })); setJobDraft(buildDashboardJobDraft(message, appState.user?.timezone || MOSCOW_TIMEZONE)); setJobModalOpen(true); };
  const openEditJob = (job) => { setEditingJobId(job.id); setJobDraft({ name: job.name || '', version: job.version ?? 1, description: job.description || '', prompt_template: job.prompt_template || '', job_type: job.job_type || appState.jobsMeta?.templates_order?.[0] || 'daily_brief', visibility: job.visibility || 'private', status: job.status || 'active', source_of_truth: job.source_of_truth || 'local_jobs', deliver: job.deliver || job.parameters?.deliver || 'origin', self_subscribe_enabled: Boolean(job.self_subscribe_enabled), self_subscribe_scope: job.self_subscribe_scope || 'visible_users', schedule_kind: job.schedule_kind || 'daily', time_of_day: job.time_of_day || '09:00', timezone: job.timezone || appState.user?.timezone || MOSCOW_TIMEZONE, start_date: job.start_date || new Date().toISOString().slice(0, 10), days_of_week: [...(job.days_of_week || ['mon'])], parameters: { ...(job.parameters || {}) }, access: [...(job.access || []).map((item) => ({ user_id: Number(item.user_id), role: item.role || 'viewer' }))], recipients: [...(job.recipients || []).map((item) => ({ recipient_type: item.recipient_type, target_value: String(item.target_value), label: item.label }))] }); setJobModalOpen(true); };
  const openRecipientsPicker = withAsync(async (job) => {
    await ensureJobsContextLoaded({ refreshMeta: true });
    const detail = await api.getJob(job.id);
    setAppState((prev) => ({ ...prev, screen: 'jobs', activeJobId: job.id, activeJob: detail.job || job, jobs: prev.jobs.map((item) => String(item.id) === String(job.id) ? { ...item, ...(detail.job || job) } : item) }));
    setJobMembersModal({ open: true, mode: 'recipients', job: detail.job || job });
  });
  const openAccessPicker = withAsync(async (job) => {
    await ensureJobsContextLoaded({ refreshMeta: true });
    const detail = await api.getJob(job.id);
    setAppState((prev) => ({ ...prev, screen: 'jobs', activeJobId: job.id, activeJob: detail.job || job, jobs: prev.jobs.map((item) => String(item.id) === String(job.id) ? { ...item, ...(detail.job || job) } : item) }));
    setJobMembersModal({ open: true, mode: 'access', job: detail.job || job });
  });
  const closeJobMembersModal = () => setJobMembersModal({ open: false, mode: 'recipients', job: null });
  const handleCloseJobModal = () => {
    setJobModalOpen(false);
    setEditingJobId(null);
    setJobDraft(initialJobDraft(appState.user?.timezone || MOSCOW_TIMEZONE));
  };
  const handleJobDraftChange = (field, value) => setJobDraft((prev) => {
    if (field === 'parameter') return { ...prev, parameters: { ...(prev.parameters || {}), [value.key]: value.value } };
    if (field === 'toggle_weekday') { const current = new Set(prev.days_of_week || []); current.has(value) ? current.delete(value) : current.add(value); return { ...prev, days_of_week: Array.from(current) }; }
    if (field === 'access_add') { const user = usersAvailableForAccess(appState.jobsMeta?.users || [], appState.user?.id)[0]; if (!user) return prev; return { ...prev, access: [...prev.access, { user_id: Number(user.id), role: 'viewer' }] }; }
    if (field === 'access_user') return { ...prev, access: prev.access.map((row, index) => index === value.index ? { ...row, user_id: Number(value.value) } : row) };
    if (field === 'access_remove') return { ...prev, access: prev.access.filter((_, index) => index !== value) };
    if (field === 'toggle_recipient_user') { const user = value; const exists = prev.recipients.some((item) => item.recipient_type === 'fixed_user' && String(item.target_value) === String(user.id)); return { ...prev, recipients: exists ? prev.recipients.filter((item) => !(item.recipient_type === 'fixed_user' && String(item.target_value) === String(user.id))) : [...prev.recipients, { recipient_type: 'fixed_user', target_value: String(user.id), label: user.name || user.email || `user:${user.id}` }] }; }
    if (field === 'toggle_recipient_thread') { const thread = value; const exists = prev.recipients.some((item) => item.recipient_type === 'fixed_thread' && String(item.target_value) === String(thread.id)); return { ...prev, recipients: exists ? prev.recipients.filter((item) => !(item.recipient_type === 'fixed_thread' && String(item.target_value) === String(thread.id))) : [...prev.recipients, { recipient_type: 'fixed_thread', target_value: String(thread.id), label: thread.title || `chat:${thread.id}` }] }; }
    return { ...prev, [field]: value };
  });
  const handleSaveJob = withAsync(async () => {
    if (!jobDraft.name.trim()) throw new Error('Нужно указать название задачи.');
    if (!jobDraft.prompt_template.trim()) throw new Error('Нужно указать текст задачи.');
    const payload = {
      source_of_truth: jobDraft.source_of_truth || 'local_jobs',
      name: jobDraft.name.trim(),
      version: jobDraft.version,
      description: jobDraft.description.trim(),
      prompt_template: jobDraft.prompt_template.trim(),
      job_type: jobDraft.job_type,
      visibility: jobDraft.visibility,
      status: jobDraft.status,
      self_subscribe_enabled: jobDraft.self_subscribe_enabled,
      self_subscribe_scope: jobDraft.self_subscribe_enabled ? jobDraft.self_subscribe_scope : 'disabled',
      schedule_kind: jobDraft.schedule_kind,
      time_of_day: jobDraft.time_of_day,
      timezone: jobDraft.timezone.trim(),
      start_date: jobDraft.start_date,
      days_of_week: jobDraft.days_of_week,
      parameters: jobDraft.parameters || {},
      access: jobDraft.access || [],
      recipients: jobDraft.recipients || [],
    };
    let result;
    if (jobDraft.source_of_truth === 'hermes_cron') {
      const cronPayload = {
        source_of_truth: 'hermes_cron',
        name: jobDraft.name.trim(),
        status: jobDraft.status,
        prompt_template: jobDraft.prompt_template.trim(),
        prompt: jobDraft.prompt_template.trim(),
        deliver: jobDraft.deliver || 'origin',
        schedule_kind: jobDraft.schedule_kind,
        time_of_day: jobDraft.time_of_day,
        days_of_week: jobDraft.days_of_week,
        schedule: buildHermesCronSchedule(jobDraft),
      };
      result = editingJobId ? await api.updateJob(editingJobId, cronPayload) : await api.createJob(cronPayload);
    } else {
      result = editingJobId ? await api.updateJob(editingJobId, payload) : await api.createJob(payload);
    }
    setJobModalOpen(false);
    await loadJobs(false);
    if (result.job?.id) await loadJob(result.job.id);
    if (appState.user?.role === 'admin') await loadAdmin(true);
    setNotice(editingJobId ? 'Задача обновлена.' : 'Задача создана.');
  });
  async function handleUpdateJobRecipients(jobId, recipients) { const current = await api.getJob(jobId); const job = current.job; if (!job) return; const payload = { version: job.version ?? 1, recipients };
    await api.updateJob(jobId, payload);
    await loadJobs(false);
    await loadJob(jobId);
    setJobMembersModal((prev) => prev.open ? { ...prev, job: { ...(prev.job || {}), recipients } } : prev);
  }
  async function handleUpdateJobAccess(jobId, access) { const current = await api.getJob(jobId); const job = current.job; if (!job) return; const payload = { version: job.version ?? 1, access };
    await api.updateJob(jobId, payload);
    await loadJobs(false);
    await loadJob(jobId);
    setJobMembersModal((prev) => prev.open ? { ...prev, job: { ...(prev.job || {}), access } } : prev);
  }
  const handleSaveJobMembers = withAsync(async (jobId, items, mode) => {
    if (mode === 'recipients') {
      await handleUpdateJobRecipients(jobId, items);
      setNotice('Список рассылки обновлён.');
    } else {
      await handleUpdateJobAccess(jobId, items);
      setNotice('Доступ обновлён.');
    }
    closeJobMembersModal();
  });

  const handleAdminSectionChange = withAsync(async (section) => { setAppState((prev) => ({ ...prev, admin: { ...prev.admin, section } })); if (section === 'operations' || section === 'data_policy') { const needsReload = !appState.admin.loaded || (section === 'operations' ? (appState.admin.events || []).length === 0 : !appState.admin.dataPolicy); await loadAdmin(needsReload, section); } });
  const handleToggleUserSelection = (userId, checked) => setSelectedUserIds((prev) => checked ? Array.from(new Set([...prev, Number(userId)])) : prev.filter((id) => Number(id) !== Number(userId)));
  const handleSelectAllUsers = () => setSelectedUserIds((appState.admin.users || []).map((user) => Number(user.id)));
  const handleClearSelection = () => setSelectedUserIds([]);
  const handleBulkUserStatus = withAsync(async (status) => { if (!selectedUserIds.length) throw new Error('Сначала выбери пользователей.'); await api.bulkAdminUsers({ user_ids: selectedUserIds, status }); setSelectedUserIds([]); await loadAdmin(true, 'users'); setNotice(status === 'inactive' ? 'Пользователи переведены в неактивные.' : 'Пользователи удалены из выбора.'); });
  const handleAdminUserFormChange = (field, value) => setAdminUserForm((prev) => ({ ...prev, [field]: value }));
  const handleOpenCreateAdminUser = () => { setAdminUserForm(adminUserFormFromUser()); setAdminUserHistory([]); setAdminUserModalOpen(true); };
  const handleEditAdminUser = withAsync(async (userId) => { const [detail, history] = await Promise.all([api.getAdminUser(userId), api.getAdminUserHistory(userId)]); setAdminUserForm(adminUserFormFromUser(detail.user)); setAdminUserHistory(history.history || []); setAdminUserModalOpen(true); setAppState((prev) => ({ ...prev, admin: { ...prev.admin, section: 'users' } })); });
  const handleResetAdminUserForm = () => { setAdminUserForm(adminUserFormFromUser()); setAdminUserHistory([]); setAdminUserModalOpen(false); };
  const handleSaveAdminUser = withAsync(async () => { if (!adminUserForm.id) { if (!adminUserForm.email.trim()) throw new Error('Для нового пользователя нужен email.'); if (!adminUserForm.password.trim()) throw new Error('Для нового пользователя нужен пароль.'); if (!adminUserForm.name.trim()) throw new Error('Для нового пользователя нужно имя.'); } const payload = buildAdminUserPayload(adminUserForm); const result = adminUserForm.id ? await api.updateAdminUser(adminUserForm.id, payload) : await api.createAdminUser(payload); await loadAdmin(true, 'users'); const [detail, history] = await Promise.all([api.getAdminUser(result.user.id), api.getAdminUserHistory(result.user.id)]); setAdminUserForm(adminUserFormFromUser(detail.user)); setAdminUserHistory(history.history || []); setAdminUserModalOpen(false); setNotice(adminUserForm.id ? 'Пользователь обновлён.' : 'Пользователь создан.'); });
  const handleImportCsv = withAsync(async () => { if (!importCsv.trim()) throw new Error('Сначала вставь CSV.'); await api.importAdminUsersCsv({ csv_text: importCsv.trim(), default_password: 'temporary-pass-123' }); await loadAdmin(true, 'users'); setNotice('Импорт пользователей завершён.'); });

  const handleEventsFilterChange = withAsync(async (field, value) => { const nextFilters = { ...appState.admin.eventsFilters, [field]: value }; setAppState((prev) => ({ ...prev, admin: { ...prev.admin, eventsFilters: nextFilters } })); const payload = await api.getAdminEvents({ ...nextFilters, date_from: nextFilters.date_from ? new Date(nextFilters.date_from).toISOString() : '', date_to: nextFilters.date_to ? new Date(nextFilters.date_to).toISOString() : '' }); setAppState((prev) => ({ ...prev, admin: { ...prev.admin, eventsFilters: nextFilters, events: payload.events || [] } })); });

  const handleOpenDataset = (datasetKey) => { setActiveDatasetKey(datasetKey); setReferenceDraft(null); setReferenceHistory([]); };
  const handleEditReferenceItem = withAsync(async (datasetKey, item) => { setActiveDatasetKey(datasetKey); setReferenceDraft(buildReferenceDraft(datasetKey, item)); const history = await api.getAdminReferenceItemHistory(datasetKey, item.item_key); setReferenceHistory(history.history || []); });
  const handleCreateReferenceItem = (datasetKey) => { setActiveDatasetKey(datasetKey); setReferenceDraft(buildReferenceDraft(datasetKey, null)); setReferenceHistory([]); };
  const handleReferenceDraftChange = (field, value) => setReferenceDraft((prev) => ({ ...prev, [field]: value }));
  const handleToggleReferenceItem = (datasetKey, itemKey, checked) => setSelectedReferenceItems((prev) => ({ ...prev, [datasetKey]: checked ? Array.from(new Set([...(prev[datasetKey] || []), itemKey])) : (prev[datasetKey] || []).filter((entry) => entry !== itemKey) }));
  const handleBulkReferenceStatus = withAsync(async (datasetKey, status) => { const itemKeys = selectedReferenceItems[datasetKey] || []; if (!itemKeys.length) throw new Error('Сначала выбери элементы справочника.'); await api.bulkAdminReferenceItems(datasetKey, { item_keys: itemKeys, status }); setSelectedReferenceItems((prev) => ({ ...prev, [datasetKey]: [] })); await loadAdmin(true, 'references'); setNotice(status === 'inactive' ? 'Элементы справочника переведены в неактивные.' : 'Элементы справочника удалены из выбора.'); });
  const handleSaveReference = withAsync(async () => { if (!referenceDraft) return; const payload = parseReferenceDraftPayload(referenceDraft); const datasetKey = referenceDraft.datasetKey; const existing = (appState.admin.references?.[datasetKey]?.items || []).find((item) => item.item_key === referenceDraft.item_key.trim()); if (existing) await api.updateAdminReferenceItem(datasetKey, referenceDraft.item_key.trim(), payload); else await api.createAdminReferenceItem(datasetKey, payload); await loadAdmin(true, 'references'); const history = await api.getAdminReferenceItemHistory(datasetKey, referenceDraft.item_key.trim()); setReferenceHistory(history.history || []); setNotice(existing ? 'Элемент справочника обновлён.' : 'Элемент справочника создан.'); });

  if (booting) return <div className="loading-screen">Загружаю рабочее пространство…</div>;
  if (!appState.authenticated) return <LoginScreen serviceInfo={serviceInfo} setupRequired={setupRequired} loginForm={loginForm} setupForm={setupForm} error={error} loading={busy} onLoginChange={(e) => setLoginForm((prev) => ({ ...prev, [e.target.name]: e.target.value }))} onSetupChange={(e) => setSetupForm((prev) => ({ ...prev, [e.target.name]: e.target.value }))} onLogin={handleLogin} onSetup={handleSetup} />;

  return <div className="app-layout"><Sidebar appState={appState} onNavigate={handleNavigate} onCreateThread={handleCreateThread} onSelectThread={handleSelectThread} onOpenThreadsModal={() => setThreadsModalOpen(true)} onLogout={handleLogout} /><main className="main-panel">{(error || notice) ? <div className={`global-banner ${error ? 'error' : 'ok'}`}>{error || notice}</div> : null}{appState.screen === 'chat' ? <ChatScreen appState={appState} composerText={composerText} composerFiles={composerFiles} composerExistingFiles={composerExistingFiles} requestPolicyDraft={requestPolicyDraft} sending={busy} onComposerChange={(e) => setComposerText(e.target.value)} onComposerKeyDown={handleComposerKeyDown} onFileChange={(e) => setComposerFiles(Array.from(e.target.files || []))} onToggleExistingFile={toggleExistingFile} onOpenUserFile={handleOpenUserFile} onDeleteFile={handleDeleteFile} onApplyStarterPrompt={handleApplyStarterPrompt} onRequestPolicyChange={handleRequestPolicyChange} onSend={handleSend} onRenameThread={handleRenameThread} onArchiveThread={handleArchiveThread} onDeleteThread={handleDeleteThread} onDismissWelcome={handleDismissChatWelcome} onSaveDashboard={openCreateDashboardRefreshJob} onOpenAttachment={handleOpenAttachment} onExportMessage={handleExportMessage} /> : null}{appState.screen === 'profile' ? <ProfileScreen user={appState.user} profileSummary={appState.profileSummary} userFiles={appState.userFiles} threadFiles={appState.threadFiles} activeThreadTitle={appState.threads.find((thread) => String(thread.id) === String(appState.activeThreadId))?.title || ''} profileForm={profileForm} passwordForm={passwordForm} profileSection={profileSection} profileFileQuery={profileFileQuery} profileFileType={profileFileType} bootstrap={appState.bootstrap} onSectionChange={setProfileSection} onProfileFileFilterChange={handleProfileFileFilterChange} onProfileChange={handleProfileChange} onPasswordChange={handlePasswordChange} onSaveProfile={handleSaveProfile} onChangePassword={handleChangePassword} onOpenUserFile={handleOpenUserFile} onDeleteFile={handleDeleteFile} onToggleExistingFile={toggleExistingFile} composerExistingFiles={composerExistingFiles} /> : null}{appState.screen === 'jobs' ? <JobsScreen jobsMeta={appState.jobsMeta} jobs={appState.jobs} activeJob={appState.activeJob} onSelectJob={handleSelectJob} onRunJob={handleRunJob} onToggleSubscribe={handleToggleSubscribe} onUpdateDisplayName={handleUpdateDisplayName} onOpenCreate={openCreateJob} onOpenEdit={openEditJob} onOpenRecipients={openRecipientsPicker} onOpenAccess={openAccessPicker} onToggleStatus={handleToggleJobStatus} onDeleteJob={handleDeleteJob} /> : null}{appState.screen === 'admin' && appState.user?.role === 'admin' ? <AdminScreen admin={appState.admin} onSectionChange={handleAdminSectionChange} selectedUserIds={selectedUserIds} onToggleUser={handleToggleUserSelection} onSelectAllUsers={handleSelectAllUsers} onClearSelection={handleClearSelection} onBulkUserStatus={handleBulkUserStatus} onOpenCreateUser={handleOpenCreateAdminUser} onEditUser={handleEditAdminUser} onAssignJob={openCreateJobForUser} adminUserForm={adminUserForm} adminUserHistory={adminUserHistory} adminUserModalOpen={adminUserModalOpen} onAdminUserFormChange={handleAdminUserFormChange} onSaveAdminUser={handleSaveAdminUser} onCloseAdminUserModal={handleResetAdminUserForm} importCsv={importCsv} onImportCsvChange={setImportCsv} onImportCsv={handleImportCsv} activeDatasetKey={activeDatasetKey} selectedReferenceItems={selectedReferenceItems} onOpenDataset={handleOpenDataset} onCreateReferenceItem={handleCreateReferenceItem} onEditReferenceItem={handleEditReferenceItem} referenceDraft={referenceDraft} referenceHistory={referenceHistory} onReferenceDraftChange={handleReferenceDraftChange} onSaveReference={handleSaveReference} onToggleReferenceItem={handleToggleReferenceItem} onBulkReferenceStatus={handleBulkReferenceStatus} onEventsFilterChange={handleEventsFilterChange} dataPolicyDraft={dataPolicyDraft} onDataPolicyDraftChange={handleDataPolicyDraftChange} onSaveDataPolicy={handleSaveDataPolicy} onSaveNotice={handleSaveNotice} onOpenThread={handleAdminOpenThread} /> : null}</main>{threadsModalOpen ? <ThreadsModal open={threadsModalOpen} threads={appState.threads} activeThreadId={appState.activeThreadId} onSelectThread={(threadId) => { setThreadsModalOpen(false); handleSelectThread(threadId); }} onToggleArchiveThread={handleToggleArchiveThread} onClose={() => setThreadsModalOpen(false)} /> : null}{jobModalOpen ? <JobDraftModal open={jobModalOpen} draft={jobDraft} jobsMeta={appState.jobsMeta} currentUserId={appState.user?.id} currentThreadId={appState.activeThreadId} onClose={handleCloseJobModal} onChange={handleJobDraftChange} onSave={handleSaveJob} isEditing={Boolean(editingJobId)} /> : null}{jobMembersModal.open ? <JobMembersModal open={jobMembersModal.open} mode={jobMembersModal.mode} job={jobMembersModal.job} jobsMeta={appState.jobsMeta} currentUserId={appState.user?.id} currentThreadId={appState.activeThreadId} onClose={closeJobMembersModal} onSave={handleSaveJobMembers} /> : null}{adminUserModalOpen ? <AdminUserModal open={adminUserModalOpen} userForm={adminUserForm} userHistory={adminUserHistory} importCsv={importCsv} onClose={handleResetAdminUserForm} onChange={handleAdminUserFormChange} onSave={handleSaveAdminUser} onImportCsvChange={setImportCsv} onImportCsv={handleImportCsv} /> : null}{interactionSetupOpen ? <InteractionSetupModal open={interactionSetupOpen} user={appState.user} bootstrap={appState.bootstrap} onDismiss={() => setInteractionSetupOpen(false)} onOpenProfile={() => { setInteractionSetupOpen(false); setProfileSection('response'); setAppState((prev) => ({ ...prev, screen: 'profile' })); }} /> : null}{previewFile ? <FilePreviewModal file={previewFile} onClose={() => setPreviewFile(null)} /> : null}</div>;
}
