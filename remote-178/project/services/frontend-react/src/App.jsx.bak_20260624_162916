import { useEffect, useMemo, useRef, useState } from 'react';
import { ApiError, api, getStoredToken, setStoredToken } from './api.js';

const EMPTY_LOGIN = { email: '', password: '' };
const EMPTY_SETUP = { name: '', email: '', password: '' };
const UI_STATE_STORAGE_KEY = 'hermes_web_mvp_ui_state';
const ADMIN_SECTIONS = ['overview', 'users', 'operations', 'references', 'data_policy'];
const SCREENS = ['chat', 'profile', 'jobs', 'admin'];
const PROFILE_SECTIONS = ['summary', 'identity', 'response', 'files'];
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

function buildDashboardJobDraft(message, timezone = 'UTC') {
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
    return new Date(value).toLocaleString('ru-RU');
  } catch {
    return value;
  }
}

function formatTsCompact(value) {
  if (!value) return '—';
  try {
    return new Date(value).toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
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

function humanizeJobStatus(status) {
  return ({ active: 'активна', paused: 'на паузе', disabled: 'отключена' })[status] || status || '—';
}

function humanizeRunStatus(status) {
  return ({ ok: 'успешно', error: 'ошибка', running: 'выполняется', success: 'успешно' })[status] || status || 'Без запусков';
}

function humanizeVisibility(value) {
  return ({ private: 'Приватно', shared: 'По доступу', workspace: 'Вся рабочая область' })[value] || value || '—';
}

function humanizeUserStatus(value) {
  return ({ active: 'Активен', inactive: 'Не активен', deleted: 'Удалён' })[value] || value || '—';
}

function initialJobDraft(timezone = 'UTC') {
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
    search_mode_override: runtimePolicy.default_mode || 'registered_only',
    selected_source_ids: [],
    allow_external_for_this_request: null,
    force_refresh: false,
    save_results_locally: true,
  };
}

function cloneDataPolicyForDraft(policy = null) {
  const runtime = policy || {};
  return {
    source_registry: {
      version: runtime.source_registry?.version || 1,
      items: Array.isArray(runtime.source_registry?.items) ? runtime.source_registry.items.map((item) => ({ ...item })) : [],
    },
    processing_policy: {
      default_mode: runtime.processing_policy?.default_mode || 'registered_only',
      allow_override: Boolean(runtime.processing_policy?.allow_override),
      allowed_modes: Array.isArray(runtime.processing_policy?.allowed_modes) ? [...runtime.processing_policy.allowed_modes] : [],
      mode_labels: { ...(runtime.processing_policy?.mode_labels || {}) },
      mode_descriptions: { ...(runtime.processing_policy?.mode_descriptions || {}) },
      default_external_action: runtime.processing_policy?.default_external_action || 'preserve_local_copy',
      source_selection_order: Array.isArray(runtime.processing_policy?.source_selection_order) ? [...runtime.processing_policy.source_selection_order] : [],
      mode_options: Array.isArray(runtime.processing_policy?.mode_options) ? runtime.processing_policy.mode_options.map((item) => ({ ...item })) : [],
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
  const raw = typeof message?.content === 'string' ? message.content : '';
  if (message?.role === 'user' && (message?.meta?.attachments || []).length) {
    if (message?.meta?.user_text !== undefined) return message.meta.user_text || '';
    return raw.replace(/\n\nВ сообщении приложены файлы:[\s\S]*$/, '').trim();
  }
  if (message?.role === 'assistant') {
    return raw.replace(/^MEDIA:[^\n]+$/gm, '').replace(/\n{3,}/g, '\n\n').trim();
  }
  return raw;
}

function compactThreadTitle(thread) {
  return thread?.title || 'Новый чат';
}

function threadLastActivity(thread) {
  return thread?.updated_at || thread?.created_at || null;
}

function threadHasUnread(thread) {
  return Boolean(thread?.has_unread);
}

function fileSummaryText(file) {
  const excerpt = String(file?.preview_excerpt || file?.preview_text || '').replace(/\s+/g, ' ').trim();
  if (excerpt) return excerpt.length > 140 ? `${excerpt.slice(0, 137)}…` : excerpt;
  if (file?.extraction_note) return String(file.extraction_note);
  return file?.text_extracted ? 'Текст извлечён' : 'Файл загружен без текстового извлечения';
}

function fileStatusMeta(file) {
  return `${formatTs(file?.created_at)} · ${fileSummaryText(file)}`;
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

function MessageBubble({ message, bootstrap, onSaveDashboard }) {
  const side = message.role === 'user' ? 'user' : 'assistant';
  const attachments = message.meta?.attachments || [];
  const isPending = Boolean(message.meta?.pending);
  const isError = Boolean(message.meta?.error);
  const requestPolicy = message.meta?.request_execution_policy || null;
  const dashboardArtifact = message.meta?.dashboard_artifact || null;
  const canSaveDashboard = Boolean(onSaveDashboard && dashboardArtifact?.path && message.role === 'assistant');
  return (
    <article className={`message-bubble ${side} ${isPending ? 'pending' : ''} ${isError ? 'error' : ''}`}>
      <div className="message-role">{message.role === 'user' ? 'Вы' : 'Hermes'}</div>
      <div className="message-content">{messageDisplayText(message) || '…'}</div>
      {requestPolicy ? <div className="message-policy-strip"><span className="policy-chip">{humanizeProcessingMode(requestPolicy.search_mode_override, bootstrap)}</span><span className="muted small">{requestPolicySummary(message)}</span></div> : null}
      {attachments.length > 0 && <ul className="attachment-list">{attachments.map((file, i) => <li key={`${file.original_name || file.stored_name || 'file'}-${i}`}>{message.id && String(message.id).startsWith('temp-') === false ? <button className="attachment-link-btn" type="button" onClick={() => api.openFile({ ...file, download_url: file?.download_url || `/messages/${message.id}/attachments/${i}` })}>{file.original_name || file.stored_name || `Файл ${i + 1}`}</button> : <span>{file.original_name || file.stored_name || 'Файл'}</span>}</li>)}</ul>}
      {dashboardArtifact?.path ? <div className="message-artifact-box"><div className="artifact-head"><strong>Артефакт дашборда</strong><span className="muted small">{dashboardArtifact.file_name || 'markdown'}</span></div><div className="artifact-actions"><a href={`/api/files/open-local?path=${encodeURIComponent(dashboardArtifact.path)}`} target="_blank" rel="noreferrer">Открыть markdown</a>{canSaveDashboard ? <button className="ghost-btn ghost-btn-xs" type="button" onClick={() => onSaveDashboard(message)}>Сохранить как задачу</button> : null}</div></div> : null}
      <div className="message-meta">{isPending ? 'Hermes обрабатывает сообщение…' : isError ? 'Ошибка обработки сообщения' : formatTs(message.created_at)}</div>
    </article>
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
  const visibleThreads = appState.threads.slice(0, 8);
  const visibleScreens = SCREENS.filter((screen) => !(screen === 'admin' && appState.user?.role !== 'admin'));
  return (
    <aside className="sidebar">
      <div>
        <div className="eyebrow">Hermes Web</div>
        <h2>{appState.user?.name || 'Пользователь'}</h2>
        <div className="muted">{appState.user?.email}</div>
      </div>
      <nav className="nav-stack">
        {visibleScreens.map((screen) => <button key={screen} type="button" className={`nav-btn nav-btn-${screen} ${appState.screen === screen ? 'active' : ''}`} onClick={() => onNavigate(screen)}>{screen === 'chat' ? 'Чаты' : screen === 'profile' ? 'Профиль' : screen === 'jobs' ? 'Задачи' : 'Управление'}</button>)}
      </nav>
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
        {appState.threads.length === 0 ? <div className="empty-box">Чатов пока нет</div> : null}
      </div>
      <div className="sidebar-footer">
        <div className="muted small">Всего чатов: {appState.threads.length}</div>
        <button className="ghost-btn" onClick={onLogout} type="button">Выйти</button>
      </div>
    </aside>
  );
}

function ChatScreen({ appState, composerText, composerFiles, composerExistingFiles, requestPolicyDraft, sending, onComposerChange, onComposerKeyDown, onFileChange, onToggleExistingFile, onOpenUserFile, onApplyStarterPrompt, onRequestPolicyChange, onToggleRequestSource, onSend, onRenameThread, onArchiveThread, onDismissWelcome, onSaveDashboard }) {
  const activeThread = useMemo(() => appState.threads.find((thread) => String(thread.id) === String(appState.activeThreadId)) || null, [appState.activeThreadId, appState.threads]);
  const messagesRef = useRef(null);
  const composerTextareaRef = useRef(null);
  const warningText = String(appState.bootstrap?.chat_notice?.text || '').trim();
  const warningVisible = Boolean(appState.bootstrap?.chat_notice?.enabled && warningText);
  const showWelcome = appState.messages.length === 0 && !appState.chatWelcomeDismissed;
  const starterPrompts = starterPromptsFromBootstrap(appState.bootstrap).slice(0, 4);
  const [paramsOpen, setParamsOpen] = useState(false);
  const [filesOpen, setFilesOpen] = useState(false);
  const selectedSourceCount = requestPolicyDraft.selected_source_ids?.length || 0;
  const selectedFileCount = composerFiles.length + composerExistingFiles.length;
  const selectedModeDescription = (appState.bootstrap?.data_policy?.processing_policy?.mode_options || []).find((item) => item.value === requestPolicyDraft.search_mode_override)?.description || 'Режим определяет, можно ли выходить во внешний контур и в каком порядке выбирать источники.';

  useEffect(() => {
    if (!messagesRef.current || showWelcome) return;
    messagesRef.current.scrollTop = messagesRef.current.scrollHeight;
  }, [appState.activeThreadId, appState.messages, showWelcome]);

  useEffect(() => {
    if (!composerTextareaRef.current) return;
    composerTextareaRef.current.style.height = 'auto';
    composerTextareaRef.current.style.height = `${Math.min(composerTextareaRef.current.scrollHeight, 240)}px`;
  }, [composerText]);

  return (
    <div className="screen-shell chat-screen">
      <header className="section-head">
        <div className="chat-header-main">
          <div>
            <div className="eyebrow">Чаты</div>
            <p className="muted small chat-section-copy">Рабочий раздел для диалога, файлов и обсуждения.</p>
            <h1>{compactThreadTitle(activeThread)}</h1>
          </div>
          <div className="chat-header-meta">
            {activeThread?.archived ? <span className="status-chip">В архиве</span> : null}
            {sending ? <span className="status-chip warn">Hermes обрабатывает сообщение…</span> : null}
          </div>
        </div>
        <div className="head-actions chat-header-actions">
          {activeThread ? <button className="ghost-btn" onClick={onRenameThread} type="button">Переименовать</button> : null}
          {activeThread ? <button className="ghost-btn" onClick={onArchiveThread} type="button">{activeThread.archived ? 'Вернуть из архива' : 'В архив'}</button> : null}
        </div>
      </header>
      {warningVisible && !showWelcome ? <div className="chat-guide-banner compact"><strong>Внимание</strong><span className="inline-label-separator">—</span><span>{warningText}</span></div> : null}
      <div className="chat-workspace">
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
            {appState.messages.map((message, index) => <MessageBubble key={message.id || `${message.created_at}-${index}`} message={message} bootstrap={appState.bootstrap} onSaveDashboard={onSaveDashboard} />)}
            {appState.messages.length <= 1 ? <div className="chat-low-activity-hint"><strong>Диалог только начинается.</strong><span>Сформулируйте следующий шаг ниже, чтобы собрать контекст и продолжить работу в этом чате.</span></div> : null}
          </>}
        </section>
        <aside className="chat-sidepanel">
          <form className="composer sticky-composer chat-composer-card" onSubmit={onSend}>
            <div className="composer-shell">
              <div className="composer-main">
                <div className="composer-summary composer-summary-compact">
                  <div className="eyebrow">Сообщение в чат</div>
                  <h3>Продолжить диалог</h3>
                </div>
                <label className="sr-only" htmlFor="chat-composer-textarea">Сообщение</label>
                <textarea id="chat-composer-textarea" ref={composerTextareaRef} className="composer-textarea" value={composerText} onChange={onComposerChange} onKeyDown={onComposerKeyDown} placeholder="Напишите сообщение для текущего чата…" rows={1} />
                <div className="composer-selection-summary muted small">{selectedFileCount ? `Контекст: новых файлов ${composerFiles.length}, из профиля ${composerExistingFiles.length}.` : 'Можно добавить файлы и точечно настроить режим запроса.'}</div>
              </div>
              <div className="composer-toolbar">
                <div className="composer-popover-anchor">
                  <button className={`ghost-btn composer-tool-btn ${filesOpen ? 'active' : ''}`} onClick={() => { setFilesOpen((prev) => !prev); setParamsOpen(false); }} type="button">Файлы{selectedFileCount ? ` · ${selectedFileCount}` : ''}</button>
                  {filesOpen ? <div className={`composer-popover composer-files-popover ${appState.userFiles.length ? 'with-profile-list' : ''}`}>
                    <div className="composer-popover-title">Контекст и вложения</div>
                    <label className="file-label file-label-inline"><input multiple onChange={onFileChange} type="file" />Добавить новые файлы</label>
                    {composerFiles.length > 0 ? <div className="muted small">Новые файлы: {composerFiles.map((file) => file.name).join(', ')}</div> : null}
                    <details className="details-box context-disclosure" open={composerExistingFiles.length > 0}>
                      <summary>Файлы из профиля {composerExistingFiles.length > 0 ? `· выбрано ${composerExistingFiles.length}` : ''}</summary>
                      <div className="existing-files-block pinned-existing-files">
                        <div className="composer-section-head"><div className="eyebrow">Файлы из профиля</div><div className="muted small">Можно использовать любой ранее загруженный файл из профиля.</div></div>
                        <div className="existing-file-grid existing-file-list-compact">
                          {appState.userFiles.map((file) => {
                            const checked = composerExistingFiles.some((item) => Number(item.id) === Number(file.id));
                            return <label className={`existing-file-card file-row ${checked ? 'selected' : ''}`} key={file.id}><input checked={checked} onChange={() => onToggleExistingFile(file)} type="checkbox" /><div><div className="file-card-head"><strong>{file.original_name}</strong><button className="ghost-btn ghost-btn-xs" onClick={(event) => { event.preventDefault(); event.stopPropagation(); onOpenUserFile(file); }} type="button">Открыть</button></div><div className="muted small">{formatBytes(file.size_bytes)} · {file.mime_type || '—'}</div><div className="muted small">{fileStatusMeta(file)}</div></div></label>;
                          })}
                          {appState.userFiles.length === 0 ? <div className="muted small">В профиле пока нет файлов.</div> : null}
                        </div>
                      </div>
                    </details>
                  </div> : null}
                </div>
                <div className="composer-popover-anchor">
                  <button className={`ghost-btn composer-tool-btn ${paramsOpen ? 'active' : ''}`} onClick={() => { setParamsOpen((prev) => !prev); setFilesOpen(false); }} type="button">Параметры{selectedSourceCount ? ` · ${selectedSourceCount}` : ''}</button>
                  {paramsOpen ? <div className="composer-popover composer-params-popover">
                    <div className="composer-popover-title">Режим запроса</div>
                    <div className="composer-params-stack">
                      <label>Режим обработки<select value={requestPolicyDraft.search_mode_override || ''} onChange={(e) => onRequestPolicyChange('search_mode_override', e.target.value)}>{(appState.bootstrap?.data_policy?.processing_policy?.mode_options || []).map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>
                      <div className="muted small">{selectedModeDescription}</div>
                      <label className="checkbox-card compact"><input type="checkbox" checked={Boolean(requestPolicyDraft.force_refresh)} onChange={(e) => onRequestPolicyChange('force_refresh', e.target.checked)} /><div><strong>Игнорировать прошлый кэш</strong><div className="muted small">Полезно, если дашборд нужно пересобрать заново.</div></div></label>
                      <label className="checkbox-card compact"><input type="checkbox" checked={Boolean(requestPolicyDraft.save_results_locally)} onChange={(e) => onRequestPolicyChange('save_results_locally', e.target.checked)} /><div><strong>Сохранить результат локально</strong><div className="muted small">Markdown-артефакт сохранится рядом с runtime-данными.</div></div></label>
                      <label className="checkbox-card compact"><input type="checkbox" checked={Boolean(requestPolicyDraft.allow_external_for_this_request)} onChange={(e) => onRequestPolicyChange('allow_external_for_this_request', e.target.checked)} /><div><strong>Разрешить внешние источники</strong><div className="muted small">Явный override для выхода за пределы внутренних данных.</div></div></label>
                      <details className="details-box context-disclosure">
                        <summary>Разрешённые источники {selectedSourceCount ? `· выбрано ${selectedSourceCount}` : ''}</summary>
                        <div className="source-picker-grid">{(appState.bootstrap?.data_policy?.source_registry?.items || []).map((item) => { const checked = (requestPolicyDraft.selected_source_ids || []).includes(item.source_key); return <label key={item.source_key} className={`checkbox-card source-choice-card ${checked ? 'selected' : ''}`}><input type="checkbox" checked={checked} onChange={() => onToggleRequestSource(item.source_key)} /><div><strong>{item.name}</strong><div className="muted small">{item.origin === 'internal' ? 'внутренний' : 'внешний'} · {item.trust_level} · {item.registration_status}</div></div></label>; })}</div>
                      </details>
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

function ProfileScreen({ user, profileSummary, userFiles, profileForm, passwordForm, profileSection, profileFileQuery, profileFileType, bootstrap, onSectionChange, onProfileFileFilterChange, onProfileChange, onPasswordChange, onSaveProfile, onChangePassword, onOpenUserFile }) {
  const files = useMemo(() => filteredUserFiles(userFiles, { query: profileFileQuery, type: profileFileType }), [userFiles, profileFileQuery, profileFileType]);
  const toneOptions = useMemo(() => referenceOptions(bootstrap, 'assistant_tones', profileForm.tone), [bootstrap, profileForm.tone]);
  const answerDepthOptions = useMemo(() => referenceOptions(bootstrap, 'assistant_answer_depths', profileForm.answer_depth), [bootstrap, profileForm.answer_depth]);
  const interactionModeOptions = useMemo(() => referenceOptions(bootstrap, 'assistant_interaction_modes', profileForm.interaction_mode), [bootstrap, profileForm.interaction_mode]);
  const totalFiles = userFiles.length;
  const filesReady = userFiles.filter((file) => file.text_extracted).length;
  return (
    <div className="screen-shell scrollable">
      <header className="section-head compact"><div><div className="eyebrow">Профиль</div><h1>Профиль пользователя</h1></div></header>
      <div className="head-actions profile-tabs">{PROFILE_SECTIONS.map((section) => <button key={section} className={`ghost-btn ${profileSection === section ? 'active' : ''}`} type="button" onClick={() => onSectionChange(section)}>{section === 'summary' ? 'Сводка' : section === 'identity' ? 'Личные данные' : section === 'response' ? 'Как отвечать' : 'Файлы'}</button>)}</div>
      {profileSection === 'summary' ? <div className="grid two-cols profile-summary-layout"><section className="panel-card stack profile-hero-card"><div className="profile-hero-top"><div><div className="eyebrow">Состояние профиля</div><h3>{user?.name || user?.email || 'Профиль пользователя'}</h3><div className="muted">{user?.title || (user?.role === 'admin' ? 'Администратор рабочей области' : 'Пользователь рабочей области')}</div></div><div className="profile-health-chip">{[user?.name, user?.timezone, user?.language, user?.goals, user?.assistant_profile?.about_user].filter((item) => String(item || '').trim()).length < 5 ? 'Нужно заполнить ещё 1 поле' : 'Профиль заполнен'}</div></div><div className="summary-grid summary-grid-tight"><div className="summary-box"><span>Заполненность</span><strong>{[user?.name, user?.timezone, user?.language, user?.goals, user?.assistant_profile?.about_user].filter((item) => String(item || '').trim()).length}/5</strong></div><div className="summary-box"><span>Файлы профиля</span><strong>{totalFiles}</strong></div><div className="summary-box"><span>Распознано</span><strong>{filesReady}</strong></div></div><div className="profile-next-step"><strong>Следующий шаг</strong><span>{[user?.name, user?.timezone, user?.language, user?.goals, user?.assistant_profile?.about_user].filter((item) => String(item || '').trim()).length < 5 ? 'Проверьте личные данные и дополните профиль, чтобы ответы Hermes были точнее.' : 'Профиль готов к работе. При необходимости обновите настройки ответов или набор файлов.'}</span></div></section><section className="panel-card stack"><h3>Сводка профиля</h3><div className="muted small">Email: {user?.email || '—'}</div><div className="muted small">Первичная настройка: {user?.onboarding_completed ? 'завершена' : 'не завершена'}</div>{profileSummary?.bullets?.length ? <ul className="bullet-list">{profileSummary.bullets.map((item, index) => <li key={index}>{item}</li>)}</ul> : <div className="muted">Добавьте личные данные и рабочий контекст, чтобы профиль стал полезнее для ответов.</div>}<div className="profile-quick-links"><button className="ghost-btn" type="button" onClick={() => onSectionChange('identity')}>Проверить личные данные</button><button className="ghost-btn" type="button" onClick={() => onSectionChange('files')}>Открыть файлы</button></div></section></div> : null}
      {profileSection === 'identity' ? <div className="grid two-cols"><section className="panel-card stack"><h3>Основные данные</h3><label>Имя<input name="name" value={profileForm.name} onChange={onProfileChange} /></label><label>Часовой пояс<input name="timezone" value={profileForm.timezone} onChange={onProfileChange} /></label><label>Язык<input name="language" value={profileForm.language} onChange={onProfileChange} /></label><label>Команда<input name="team" value={profileForm.team} onChange={onProfileChange} /></label><label>Роль / должность<input name="title" value={profileForm.title} onChange={onProfileChange} /></label><label>Цели<textarea name="goals" rows={3} value={profileForm.goals} onChange={onProfileChange} /></label><label>Ограничения<textarea name="constraints" rows={3} value={profileForm.constraints} onChange={onProfileChange} /></label><button className="primary-btn" onClick={onSaveProfile} type="button">Сохранить профиль</button></section><section className="panel-card stack"><h3>Смена пароля</h3><label>Текущий пароль<input name="currentPassword" type="password" value={passwordForm.currentPassword} onChange={onPasswordChange} /></label><label>Новый пароль<input name="newPassword" type="password" value={passwordForm.newPassword} onChange={onPasswordChange} /></label><button className="ghost-btn" onClick={onChangePassword} type="button">Обновить пароль</button></section></div> : null}
      {profileSection === 'response' ? <div className="grid two-cols"><section className="panel-card stack"><div className="head-actions"><div><h3>Как отвечать по умолчанию</h3><div className="muted small">Настройки берутся из runtime-справочников и сохраняются в профиль.</div></div></div><label>Ключевые рамки и приоритеты<textarea name="pinned" rows={4} value={profileForm.pinned} onChange={onProfileChange} placeholder="Ключевые рамки, приоритеты, запреты — по одной строке" /></label><label>Манера ответа<select name="tone" value={profileForm.tone} onChange={onProfileChange}>{toneOptions.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label><label>Глубина ответа<select name="answer_depth" value={profileForm.answer_depth} onChange={onProfileChange}>{answerDepthOptions.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label><label>Режим взаимодействия<select name="interaction_mode" value={profileForm.interaction_mode} onChange={onProfileChange}>{interactionModeOptions.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label><label>О пользователе<textarea name="about_user" rows={4} value={profileForm.about_user} onChange={onProfileChange} placeholder="Контекст о роли, зоне ответственности и типовых задачах" /></label><button className="primary-btn" onClick={onSaveProfile} type="button">Сохранить настройки ответов</button></section><section className="panel-card stack compact-card"><h3>Что влияет на ответы</h3><div className="muted">На качество ответа здесь сильнее всего влияют рабочий контекст, ключевые рамки и выбранный режим взаимодействия.</div><div className="profile-next-step"><strong>Сейчас в профиле</strong><span>{profileForm.about_user?.trim() || 'Дополнительный контекст пока не заполнен.'}</span></div></section></div> : null}
      {profileSection === 'files' ? <section className="panel-card stack"><div className="head-actions"><h3>Файлы и повторное использование</h3><div className="muted small">Всего файлов: {totalFiles} · распознано: {filesReady}</div></div><div className="grid two-cols"><label>Поиск<input value={profileFileQuery} onChange={(e) => onProfileFileFilterChange('query', e.target.value)} placeholder="Имя файла, тип, фрагмент" /></label><label>Тип<select value={profileFileType} onChange={(e) => onProfileFileFilterChange('type', e.target.value)}><option value="all">Все</option><option value="text_ready">С распознанным текстом</option><option value="stored_only">Без распознанного текста</option></select></label></div>{files.length === 0 ? <div className="muted">Файлы по выбранному фильтру не найдены.</div> : null}<div className="table-list profile-files-list">{files.map((file) => <div className="table-row profile-file-row" key={file.id}><div className="profile-file-main"><div className="file-card-head"><strong>{file.original_name}</strong></div><div className="muted small">{formatBytes(file.size_bytes)} · {file.mime_type || '—'} · {formatTs(file.created_at)}</div><div className="muted small profile-file-summary">{fileSummaryText(file)}</div></div><div className="profile-file-actions"><button className="ghost-btn ghost-btn-xs" onClick={() => onOpenUserFile(file)} type="button">Открыть</button></div></div>)}</div></section> : null}
    </div>
  );
}

function JobDraftModal({ open, draft, jobsMeta, currentUserId, currentThreadId, onClose, onChange, onSave, isEditing }) {
  const [recipientPickerOpen, setRecipientPickerOpen] = useState(false);
  const [recipientQuery, setRecipientQuery] = useState('');
  const [recipientRole, setRecipientRole] = useState('all');
  const [recipientTeam, setRecipientTeam] = useState('all');
  if (!open || !draft) return null;
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
            <label>Тип<select value={draft.job_type} onChange={(e) => onChange('job_type', e.target.value)}>{Object.entries(jobsMeta?.templates || {}).map(([key, value]) => <option key={key} value={key}>{value.label}</option>)}</select></label>
            {draft.source_of_truth === 'hermes_cron' ? <label>Доставка результата<select value={draft.deliver || 'origin'} onChange={(e) => onChange('deliver', e.target.value)}><option value="origin">В этот чат</option><option value="telegram">Telegram Home</option><option value="local">Только локально</option></select></label> : <label>Кто видит задачу<select value={draft.visibility} onChange={(e) => onChange('visibility', e.target.value)}><option value="private">Только владелец</option><option value="shared">Только по доступу</option><option value="workspace">Вся рабочая область</option></select></label>}
          </div>
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
            <div className="grid two-cols">{(template.fields || []).map((field) => <label key={field.key}>{field.label}{field.type === 'textarea' ? <textarea rows={3} value={draft.parameters?.[field.key] || ''} onChange={(e) => onChange('parameter', { key: field.key, value: e.target.value })} placeholder={field.placeholder || ''} /> : field.type === 'select' ? <select value={draft.parameters?.[field.key] || field.options?.[0] || ''} onChange={(e) => onChange('parameter', { key: field.key, value: e.target.value })}>{(field.options || []).map((option) => <option key={option} value={option}>{option}</option>)}</select> : <input value={draft.parameters?.[field.key] || ''} onChange={(e) => onChange('parameter', { key: field.key, value: e.target.value })} placeholder={field.placeholder || ''} />}</label>)}</div>
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

function JobMembersModal({ open, mode, job, jobsMeta, currentUserId, currentThreadId, onClose, onToggleRecipientUser, onToggleRecipientThread, onAddAccessUser, onRemoveAccessUser }) {
  const [query, setQuery] = useState('');
  const [role, setRole] = useState('all');
  const [team, setTeam] = useState('all');
  if (!open || !job) return null;
  const recipientUsers = usersAvailableForAccess(jobsMeta?.users || [], currentUserId);
  const recipientThreads = threadsAvailableForRecipients(jobsMeta?.threads || [], currentThreadId);
  const filteredUsers = filterAssignableUsers(recipientUsers, { query, role, team });
  const teams = uniqueUserTeams(recipientUsers);
  const roleOptions = Array.from(new Set(recipientUsers.map((user) => user.role).filter(Boolean))).sort();
  const isRecipients = mode === 'recipients';
  return (
    <div className="modal-backdrop-react" onClick={onClose}>
      <div className="modal-react modal-react-narrow" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header-react">
          <div>
            <h3>{isRecipients ? 'Добавить получателей' : 'Добавить доступ'}</h3>
            <div className="muted">{isRecipients ? 'Выбери, кому приходит рассылка с результатом задачи.' : 'Выбери пользователей, которые могут подписаться на задачу и работать с ней.'}</div>
          </div>
          <button className="ghost-btn" onClick={onClose} type="button">Закрыть</button>
        </div>
        <div className="stack">
          <div className="grid three-cols">
            <label>Имя или email<input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Имя, email, роль" /></label>
            <label>Роль<select value={role} onChange={(e) => setRole(e.target.value)}><option value="all">Все роли</option>{roleOptions.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
            <label>Подразделение<select value={team} onChange={(e) => setTeam(e.target.value)}><option value="all">Все подразделения</option>{teams.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
          </div>
          {isRecipients ? <>
            <div className="table-list recipient-candidate-list">{filteredUsers.map((user) => { const checked = (job.recipients || []).some((item) => item.recipient_type === 'fixed_user' && String(item.target_value) === String(user.id)); return <label key={`picker-user-${user.id}`} className={`checkbox-card recipient-choice-card ${checked ? 'selected' : ''}`}><input type="checkbox" checked={checked} onChange={() => onToggleRecipientUser(job, user)} /><div><strong>{user.name || user.email}</strong><div className="muted small">{[user.email, user.role, user.team, user.title].filter(Boolean).join(' · ') || 'Без дополнительных признаков'}</div></div></label>; })}{!filteredUsers.length ? <div className="muted">По текущему фильтру пользователи не найдены.</div> : null}</div>
            <details className="details-box"><summary>Чаты-источники для доставки</summary><div className="muted small">Нужны только если рассылку надо привязать к конкретному chat-контексту.</div><div className="table-list recipient-candidate-list">{recipientThreads.map((thread) => { const checked = (job.recipients || []).some((item) => item.recipient_type === 'fixed_thread' && String(item.target_value) === String(thread.id)); return <label key={`picker-thread-${thread.id}`} className={`checkbox-card recipient-choice-card ${checked ? 'selected' : ''}`}><input type="checkbox" checked={checked} onChange={() => onToggleRecipientThread(job, thread)} /><div><strong>{thread.title}</strong><div className="muted small">{thread.email || 'без владельца'}</div></div></label>; })}</div></details>
          </> : <div className="table-list recipient-candidate-list">{filteredUsers.map((user) => { const exists = (job.access || []).some((row) => Number(row.user_id) === Number(user.id)); return <div key={`access-user-${user.id}`} className={`table-row recipient-row recipient-inline-row ${exists ? 'selected' : ''}`}><div><strong>{user.name || user.email}</strong><div className="muted small">{[user.email, user.role, user.team, user.title].filter(Boolean).join(' · ') || 'Без дополнительных признаков'}</div></div><div className="recipient-row-actions">{exists ? <button className="ghost-btn" type="button" onClick={() => onRemoveAccessUser(job, user.id)}>Убрать</button> : <button className="ghost-btn" type="button" onClick={() => onAddAccessUser(job, user)}>Добавить</button>}</div></div>; })}{!filteredUsers.length ? <div className="muted">По текущему фильтру пользователи не найдены.</div> : null}</div>}
        </div>
      </div>
    </div>
  );
}

function JobsScreen({ jobsMeta, jobs, activeJob, onSelectJob, onRunJob, onToggleSubscribe, onUpdateDisplayName, onOpenCreate, onOpenEdit, onOpenRecipients, onOpenAccess, onToggleStatus }) {
  const canEdit = activeJob && (activeJob.role === 'owner' || activeJob.role === 'admin') && (!activeJob.read_only || activeJob.source_of_truth === 'hermes_cron');
  const canRun = activeJob && (activeJob.role === 'owner' || activeJob.role === 'admin');
  const canPauseResume = canRun;
  const canSubscribe = activeJob && !activeJob.read_only && (Boolean(activeJob.can_self_subscribe) || Boolean(activeJob.subscription?.subscribed) || Boolean(activeJob.is_subscribed));
  return (
    <div className="screen-shell scrollable">
      <header className="section-head compact"><div><div className="eyebrow">Задачи</div><h1>Задачи Hermes</h1><p className="muted">Плановые задачи, получатели результата и история запусков.</p></div><div className="head-actions"><button className="primary-btn" onClick={onOpenCreate} type="button">+ Новая задача</button></div></header>
      <div className="grid jobs-cols">
        <section className="panel-card stack">
          <div className="head-actions"><h3>Список задач</h3><div className="muted small">{jobsMeta?.can_manage ? 'Можно создавать и редактировать задачи.' : 'Раздел открыт в режиме чтения.'}</div></div>
          <div className="table-list">{jobs.map((job) => <button className={`job-card ${String(activeJob?.id) === String(job.id) ? 'active' : ''}`} key={job.id} onClick={() => onSelectJob(job.id)} type="button"><strong>{job.display_name || job.name}</strong><span className="job-card-status">{humanizeJobStatus(job.status)}</span><span className="muted small">{job.last_run_status ? `Последний запуск: ${humanizeRunStatus(job.last_run_status)}` : 'Ещё не запускалась'}</span><span className="muted small">Следующий запуск: {formatTsCompact(job.next_run_at)}</span></button>)}</div>
        </section>
        <section className="panel-card stack">
          <h3>Детали задачи</h3>
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
                  <span className={`status-chip ${activeJob.last_run_status === 'success' ? 'ok' : activeJob.last_run_status === 'failed' ? 'danger' : 'warn'}`}>{activeJob.last_run_status ? `Последний запуск: ${humanizeRunStatus(activeJob.last_run_status)}` : 'Ещё не запускалась'}</span>
                </div>
              </div>
              <div className="job-meta-grid job-meta-grid-compact">
                <div><span>Следующий запуск</span><strong>{formatTs(activeJob.next_run_at)}</strong></div>
                <div><span>Последний запуск</span><strong>{formatTs(activeJob.last_run_at)}</strong></div>
              </div>
              <label>Публичное название задачи<input defaultValue={activeJob.display_name || ''} key={`job-alias-${activeJob.id}-${activeJob.version || 1}`} id="jobAliasInputReact" /></label>
              <div className="head-actions job-actions-row">
                {canPauseResume ? <button className="primary-btn" onClick={() => onToggleStatus(activeJob)} type="button">{activeJob.status === 'paused' ? 'Возобновить задачу' : 'Приостановить задачу'}</button> : null}
                {canRun ? <button className="ghost-btn" onClick={() => onRunJob(activeJob.id)} type="button">Запустить сейчас</button> : null}
                {canEdit ? <button className="ghost-btn" onClick={() => onOpenEdit(activeJob)} type="button">Открыть настройки</button> : null}
                {canSubscribe ? <button className="ghost-btn" onClick={() => onToggleSubscribe(activeJob)} type="button">{activeJob.subscription?.subscribed || activeJob.is_subscribed ? 'Отключить рассылку' : 'Подключить рассылку'}</button> : null}
                {canEdit ? <button className="ghost-btn" onClick={() => onUpdateDisplayName(activeJob.id, document.getElementById('jobAliasInputReact')?.value || '')} type="button">Сохранить название</button> : null}
              </div>
            </section>
            <div className="grid two-cols job-detail-support-grid">
              <section className="panel-card compact-card stack surface-subtle">
                <div className="head-actions job-section-actions"><div><h4>Кто получает результат</h4><div className="muted small">Кому приходит рассылка с результатом задачи.</div></div>{canEdit ? <button className="ghost-btn ghost-btn-xs job-inline-action" onClick={() => onOpenRecipients(activeJob)} type="button">Добавить получателей</button> : null}</div>
                <div className="table-list">{(activeJob.recipients || []).map((item, index) => <div className="table-row recipient-row" key={`${item.recipient_type}-${item.target_value}-${index}`}><div><strong>{recipientLabel(item)}</strong><div className="muted small">{item.recipient_type === 'fixed_user' ? 'Пользователь' : item.recipient_type === 'fixed_thread' ? 'Чат-источник' : 'Получатель по умолчанию'}</div></div><div className="muted small">{item.recipient_type === 'fixed_thread' ? item.target_value : ''}</div></div>)}{!(activeJob.recipients || []).length ? <div className="muted">Получатели ещё не заданы.</div> : null}</div>
              </section>
              <section className="panel-card compact-card stack surface-subtle">
                <div className="head-actions job-section-actions"><div><h4>Кто видит задачу</h4><div className="muted small">Кто может подписаться на задачу и работать с ней.</div></div>{canEdit ? <button className="ghost-btn ghost-btn-xs job-inline-action" onClick={() => onOpenAccess(activeJob)} type="button">Добавить доступ</button> : null}</div>
                <div className="muted small">Режим: {humanizeVisibility(activeJob.visibility)}</div>
                <div className="table-list">{(activeJob.access || []).map((row, index) => <div className="table-row recipient-row" key={`${row.user_id}-${index}`}><div><strong>{accessLabel(row, jobsMeta?.users || [])}</strong><div className="muted small">читатель</div></div></div>)}{!(activeJob.access || []).length ? <div className="muted">Дополнительный доступ не выдан.</div> : null}</div>
              </section>
            </div>
            <details className="details-box"><summary>История запусков</summary><div className="table-like-head"><span>Статус</span><span>Итог</span><span>Когда</span></div><div className="table-list">{(activeJob.runs || []).map((run, index) => <div className="table-row table-row-3cols" key={`${run.started_at || index}-${index}`}><div><strong>{humanizeRunStatus(run.status)}</strong></div><div className="muted small">{run.summary || 'Итог не указан'}</div><div className="muted small">{formatTs(run.started_at || run.created_at)}</div></div>)}{!(activeJob.runs || []).length ? <div className="muted">История запусков пока пуста.</div> : null}</div></details>
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

function AdminUsersSection({ users, selectedUserIds, onToggleUser, onSelectAll, onClearSelection, onBulkStatus, onOpenCreate, onEditUser }) {
  const activeCount = users.filter((user) => (user.status || (user.deleted_at ? 'deleted' : user.is_active === false ? 'inactive' : 'active')) === 'active').length;
  return <section className="panel-card stack admin-users-fullwidth">
    <div className="head-actions"><div><h3>Пользователи</h3><div className="muted small">Управление доступом, ролями и рабочей нагрузкой.</div></div><div className="head-actions"><button className="ghost-btn" type="button" onClick={onSelectAll}>Выбрать всех</button><button className="ghost-btn" type="button" onClick={onClearSelection}>Снять выбор</button><button className="primary-btn" type="button" onClick={onOpenCreate}>Новый пользователь</button></div></div>
    <div className="summary-grid"><div className="summary-box"><span>Всего</span><strong>{users.length}</strong></div><div className="summary-box"><span>Активны</span><strong>{activeCount}</strong></div><div className="summary-box"><span>Выбрано</span><strong>{selectedUserIds.length}</strong></div></div>
    <div className="head-actions"><button className="ghost-btn" type="button" disabled={!selectedUserIds.length} onClick={() => onBulkStatus('inactive')}>Сделать неактивными</button><button className="ghost-btn" type="button" disabled={!selectedUserIds.length} onClick={() => onBulkStatus('deleted')}>Удалить из выбора</button></div>
    <div className="table-like-head table-like-head-users"><span>Пользователь</span><span>Статус</span><span>Чаты</span><span>Задачи</span><span>Действие</span></div>
    <div className="table-list">{users.map((user) => { const checked = selectedUserIds.includes(Number(user.id)); const status = humanizeUserStatus(user.status || (user.deleted_at ? 'deleted' : user.is_active === false ? 'inactive' : 'active')); return <div className="table-row table-row-users" key={user.id}><div className="user-cell"><label className="checkbox-inline"><input type="checkbox" checked={checked} onChange={(e) => onToggleUser(user.id, e.target.checked)} /><span /></label><div className="grow"><strong>{user.name || user.email}</strong><div className="muted small">{user.email}</div><div className="muted small">{user.role} · версия {user.version ?? '—'}</div></div></div><div className="muted small"><strong>{status}</strong></div><div className="metric-cell"><strong>{user.thread_count || 0}</strong><span className="muted small">чатов</span></div><div className="metric-cell"><strong>{user.job_count || 0}</strong><span className="muted small">задач</span></div><div><button className="ghost-btn" type="button" onClick={() => onEditUser(user.id)}>Редактировать</button></div></div>; })}</div>
  </section>;
}

function AdminDataPolicySection({ dataPolicy, onPolicyDraftChange, onSave }) {
  const registryItems = dataPolicy?.source_registry?.items || [];
  const policy = dataPolicy?.processing_policy || {};
  return <div className="grid two-cols admin-split">
    <section className="panel-card stack">
      <div className="head-actions"><div><h3>Доверенность и реестр источников</h3><div className="muted small">Админ управляет тем, какие источники считаются внутренними, внешними и насколько им можно доверять.</div></div></div>
      <div className="table-list">{registryItems.map((item, index) => <div className="table-row source-admin-row" key={item.source_key}><div className="grow"><strong>{item.name}</strong><div className="muted small">{item.source_key} · {item.connector_kind} · {item.usage_scope}</div></div><label>Контур<select value={item.origin} onChange={(e) => onPolicyDraftChange('source_field', { index, field: 'origin', value: e.target.value })}><option value="internal">internal</option><option value="external">external</option></select></label><label>Доверие<select value={item.trust_level} onChange={(e) => onPolicyDraftChange('source_field', { index, field: 'trust_level', value: e.target.value })}><option value="trusted">trusted</option><option value="review_required">review_required</option><option value="experimental">experimental</option></select></label><label>Регистрация<select value={item.registration_status} onChange={(e) => onPolicyDraftChange('source_field', { index, field: 'registration_status', value: e.target.value })}><option value="registered">registered</option><option value="known_external">known_external</option><option value="unregistered">unregistered</option></select></label><label className="checkbox-inline"><input type="checkbox" checked={Boolean(item.enabled)} onChange={(e) => onPolicyDraftChange('source_field', { index, field: 'enabled', value: e.target.checked })} /><span />Включён</label></div>)}{!registryItems.length ? <div className="muted">Источники пока не заданы.</div> : null}</div>
    </section>
    <section className="panel-card stack">
      <div className="head-actions"><div><h3>Политика построения дашбордов</h3><div className="muted small">Определяет режим по умолчанию и можно ли пользователю менять его на уровне конкретного запроса.</div></div></div>
      <label>Режим по умолчанию<select value={policy.default_mode || 'registered_only'} onChange={(e) => onPolicyDraftChange('policy_field', { field: 'default_mode', value: e.target.value })}>{(policy.mode_options || []).map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>
      <label className="checkbox-card compact"><input type="checkbox" checked={Boolean(policy.allow_override)} onChange={(e) => onPolicyDraftChange('policy_field', { field: 'allow_override', value: e.target.checked })} /><div><strong>Разрешить override из чата</strong><div className="muted small">Если выключить, все запросы будут идти строго по default_mode.</div></div></label>
      <label>Действие для внешних данных<select value={policy.default_external_action || 'preserve_local_copy'} onChange={(e) => onPolicyDraftChange('policy_field', { field: 'default_external_action', value: e.target.value })}><option value="preserve_local_copy">preserve_local_copy</option><option value="ephemeral_only">ephemeral_only</option></select></label>
      <label>Порядок выбора источников<input value={(policy.source_selection_order || []).join(', ')} onChange={(e) => onPolicyDraftChange('policy_field', { field: 'source_selection_order', value: e.target.value })} /></label>
      <div className="muted small">Формат: registered_internal, registered_external, unregistered_external.</div>
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
  return <section className="panel-card stack"><h3>Операции</h3><div className="muted">Последние действия в интерфейсе: что произошло, к какому объекту относится и какого это типа.</div><div className="grid three-cols"><label>С<input type="datetime-local" value={eventsFilters.date_from} onChange={(e) => onFiltersChange('date_from', e.target.value)} /></label><label>По<input type="datetime-local" value={eventsFilters.date_to} onChange={(e) => onFiltersChange('date_to', e.target.value)} /></label><label>Лимит<input type="number" min="1" max="500" value={eventsFilters.limit} onChange={(e) => onFiltersChange('limit', Number(e.target.value) || 100)} /></label></div><div className="head-actions"><a className="ghost-btn link-btn" href={csvUrl} target="_blank" rel="noreferrer">Выгрузить CSV</a><a className="ghost-btn link-btn" href={jsonUrl} target="_blank" rel="noreferrer">Выгрузить JSON</a><a className="ghost-btn link-btn" href={zipUrl} target="_blank" rel="noreferrer">Выгрузить ZIP</a></div><div className="table-list">{events.map((event, index) => <div className="table-row admin-event-row" key={`${event.created_at}-${index}`}><div><strong>{event.subject}</strong><div className="muted small">{event.email}</div><div className="muted small">{event.content_short}</div></div><div className="muted small"><strong>{eventKindLabel(event.event_type)}</strong><div>{event.event_type}</div></div><div className="muted small">{formatTs(event.created_at)}</div></div>)}{!events.length ? <div className="muted">События по выбранному диапазону не найдены.</div> : null}</div></section>;
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
  return <div className="screen-shell scrollable"><header className="section-head compact"><div><div className="eyebrow">Управление</div><h1>Административный обзор</h1></div></header><div className="head-actions admin-tabs">{ADMIN_SECTIONS.map((section) => <button key={section} className={`ghost-btn ${admin.section === section ? 'active' : ''}`} type="button" onClick={() => onSectionChange(section)}>{section === 'overview' ? 'Обзор' : section === 'users' ? 'Пользователи' : section === 'operations' ? 'Операции' : section === 'references' ? 'Справочники' : 'Источники и policy'}</button>)}</div>{admin.section === 'overview' ? <AdminOverviewSection admin={admin} onSaveNotice={props.onSaveNotice} /> : null}{admin.section === 'users' ? <AdminUsersSection users={admin.users} selectedUserIds={props.selectedUserIds} onToggleUser={props.onToggleUser} onSelectAll={props.onSelectAllUsers} onClearSelection={props.onClearSelection} onBulkStatus={props.onBulkUserStatus} onOpenCreate={props.onOpenCreateUser} onEditUser={props.onEditUser} /> : null}{admin.section === 'operations' ? <AdminOperationsSection eventsFilters={admin.eventsFilters} events={admin.events} onFiltersChange={props.onEventsFilterChange} /> : null}{admin.section === 'references' ? <AdminReferencesSection references={admin.references} activeDatasetKey={props.activeDatasetKey} referenceDraft={props.referenceDraft} referenceHistory={props.referenceHistory} selectedReferenceItems={props.selectedReferenceItems} onOpenDataset={props.onOpenDataset} onEditItem={props.onEditReferenceItem} onCreateItem={props.onCreateReferenceItem} onReferenceDraftChange={props.onReferenceDraftChange} onSaveReference={props.onSaveReference} onToggleReferenceItem={props.onToggleReferenceItem} onBulkReferenceStatus={props.onBulkReferenceStatus} /> : null}{admin.section === 'data_policy' ? <AdminDataPolicySection dataPolicy={admin.dataPolicy} onPolicyDraftChange={props.onPolicyDraftChange} onSave={props.onSaveDataPolicy} /> : null}</div>;
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

function ThreadsModal({ open, threads, activeThreadId, onSelectThread, onHideThread, onClose }) {
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
        <div className="table-list">{threads.map((thread) => <div className={`thread-item thread-item-modal ${String(thread.id) === String(activeThreadId) ? 'active' : ''}`} key={thread.id}><button className="thread-item thread-item-button-reset" type="button" onClick={() => onSelectThread(thread.id)}><div className="thread-item-top"><div className="thread-title-stack"><strong>{thread.title || 'Без названия'}</strong>{thread.archived ? <span className="thread-state-chip">В архиве</span> : null}</div><span className="thread-date">{formatTsCompact(threadLastActivity(thread))}</span></div><div className="thread-item-bottom"><span>{thread.preview || 'Без превью'}</span></div><div className="muted small">Последнее взаимодействие: {formatTs(threadLastActivity(thread))}</div></button><button className="ghost-btn ghost-btn-xs" onClick={() => onHideThread(thread.id)} type="button">Скрыть</button></div>)}{threads.length === 0 ? <div className="empty-box">Чатов пока нет.</div> : null}</div>
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
    <div className="modal-backdrop-react" onClick={onDismiss}>
      <div className="modal-react modal-react-narrow" onClick={(e) => e.stopPropagation()}>
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
            <div className="muted small">Открою профиль сразу на настройках, чтобы это заняло меньше минуты.</div>
            <div className="summary-grid summary-grid-tight onboarding-reference-grid">
              <div className="summary-box"><span>Тон по умолчанию</span><strong>{toneOptions[0]?.label || 'Деловой'}</strong></div>
              <div className="summary-box"><span>Глубина</span><strong>{answerDepthOptions[0]?.label || 'Сбалансированная'}</strong></div>
              <div className="summary-box"><span>Манера</span><strong>{interactionModeOptions[0]?.label || 'Уточнять по необходимости'}</strong></div>
            </div>
          </div>
          <div className="head-actions onboarding-actions">
            <button className="primary-btn" onClick={onOpenProfile} type="button">Настроить сейчас</button>
            <button className="ghost-btn" onClick={onDismiss} type="button">Позже</button>
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
  const [jobDraft, setJobDraft] = useState(initialJobDraft('UTC'));
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
    const threads = threadResult.value.threads || [];
    const feedbackReasons = reasons.status === 'fulfilled' ? (reasons.value.reasons || []) : [];
    const userFiles = files.value.files || [];
    const jobsMetaValue = jobsMeta.value;
    const savedUiState = uiStateRef.current || readUiState();
    const role = me.value.user?.role || 'user';
    const activeThreadId = pickExistingId(threads, savedUiState.activeThreadId, appState.activeThreadId);
    let messages = [];
    if (activeThreadId) messages = (await api.getThread(activeThreadId)).messages || [];
    setProfileForm(profileFormFromUser(me.value.user));
    const shouldOpenInteractionSetup = needsInteractionSetup(me.value.user);
    setInteractionSetupOpen(shouldOpenInteractionSetup);
    setProfileSection(shouldOpenInteractionSetup ? 'response' : 'summary');
    setRequestPolicyDraft(initialRequestExecutionPolicy(bootstrap.value?.data_policy?.processing_policy));
    setDataPolicyDraft(cloneDataPolicyForDraft(bootstrap.value?.data_policy));
    const nextScreen = shouldOpenInteractionSetup ? 'profile' : sanitizeScreen(keepScreen || savedUiState.screen || appState.screen || 'chat', role);
    setAppState((prev) => ({ ...prev, authenticated: true, screen: nextScreen, user: me.value.user, personalization: me.value.personalization || '', profileSummary: me.value.profile_summary || null, bootstrap: bootstrap.value, feedbackReasons, threads, activeThreadId, chatWelcomeDismissed: messages.length > 0 ? true : prev.chatWelcomeDismissed, messages, userFiles, jobsMeta: jobsMetaValue, jobs: prev.jobs || [], activeJobId: prev.activeJobId || savedUiState.activeJobId || null, activeJob: prev.activeJob || null, admin: { ...(prev.admin || initialAppState().admin), section: sanitizeAdminSection(savedUiState.adminSection || prev.admin?.section) } }));
  }

  async function loadJobs(selectFirst = false) {
    const jobsResult = await api.getJobs('all');
    const jobs = jobsResult.jobs || [];
    const savedUiState = uiStateRef.current || readUiState();
    let activeJobId = selectFirst ? null : pickExistingId(jobs, appState.activeJobId, savedUiState.activeJobId);
    if (!activeJobId && jobs.length > 0) activeJobId = jobs[0]?.id || null;
    let activeJob = null;
    if (activeJobId) activeJob = (await api.getJob(activeJobId)).job || null;
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
    if (force || requestedSection === 'data_policy') tasks.push(api.getAdminDataSources());
    else tasks.push(Promise.resolve(null));
    const [health, users, threads, jobs, references, chatNotice, eventsData, dataPolicyData] = await Promise.all(tasks);
    const resolvedDataPolicy = dataPolicyData ? {
      source_registry: dataPolicyData.source_registry || { version: 1, items: [] },
      processing_policy: dataPolicyData.processing_policy || {},
    } : null;
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
  const handleCreateThread = withAsync(async () => { const result = await api.createThread(); const threads = (await api.getThreads()).threads || []; const threadPayload = await api.getThread(result.thread.id); setAppState((prev) => ({ ...prev, screen: 'chat', threads, activeThreadId: result.thread.id, chatWelcomeDismissed: false, messages: threadPayload.messages || [] })); setThreadsModalOpen(false); setNotice('Новый чат создан.'); });
  const handleSelectThread = withAsync(async (threadId) => { const payload = await api.getThread(threadId); setAppState((prev) => ({ ...prev, screen: 'chat', activeThreadId: payload.thread.id, chatWelcomeDismissed: false, messages: payload.messages || [], threads: prev.threads.map((thread) => String(thread.id) === String(payload.thread.id) ? payload.thread : thread) })); setThreadsModalOpen(false); });
  const handleRenameThread = withAsync(async () => { const thread = appState.threads.find((item) => String(item.id) === String(appState.activeThreadId)); if (!thread) return; const title = window.prompt('Новое название чата', thread.title || ''); if (!title || title.trim() === thread.title) return; await api.updateThread(thread.id, { title: title.trim(), version: thread.version ?? 1 }); const [threads, payload] = await Promise.all([api.getThreads(), api.getThread(thread.id)]); setAppState((prev) => ({ ...prev, threads: threads.threads || prev.threads, messages: payload.messages || prev.messages })); setNotice('Название чата обновлено.'); });
  const handleArchiveThread = withAsync(async () => { const thread = appState.threads.find((item) => String(item.id) === String(appState.activeThreadId)); if (!thread) return; await api.updateThread(thread.id, { archived: !thread.archived, version: thread.version ?? 1 }); const threads = (await api.getThreads()).threads || []; const activeThreadId = threads.find((item) => String(item.id) === String(thread.id)) ? thread.id : (threads[0]?.id || null); let messages = []; if (activeThreadId) messages = (await api.getThread(activeThreadId)).messages || []; setAppState((prev) => ({ ...prev, threads, activeThreadId, chatWelcomeDismissed: false, messages })); setNotice(thread.archived ? 'Чат восстановлен из архива.' : 'Чат перенесён в архив.'); });
  const handleHideThread = withAsync(async (threadId) => { const thread = appState.threads.find((item) => String(item.id) === String(threadId)); if (!thread) return; await api.updateThread(thread.id, { ui_hidden: true, version: thread.version ?? 1 }); const threads = (await api.getThreads()).threads || []; const nextActiveId = String(appState.activeThreadId) === String(threadId) ? (threads[0]?.id || null) : appState.activeThreadId; let messages = appState.messages; if (nextActiveId && String(nextActiveId) !== String(appState.activeThreadId)) messages = (await api.getThread(nextActiveId)).messages || []; if (!nextActiveId) messages = []; setAppState((prev) => ({ ...prev, threads, activeThreadId: nextActiveId, chatWelcomeDismissed: false, messages })); setNotice('Чат скрыт из интерфейса. На бэке он сохранён.'); });
  const handleOpenUserFile = withAsync(async (file) => { if (!file) return; await api.openFile(file); });
  const handleSend = withAsync(async (event) => {
    event.preventDefault();
    const textValue = composerText.trim();
    if (!textValue && composerFiles.length === 0 && composerExistingFiles.length === 0) return;
    const pendingFiles = [...composerFiles];
    const reusedFiles = [...composerExistingFiles];
    const requestPolicyPayload = {
      ...requestPolicyDraft,
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
  const handleNavigate = withAsync(async (screen) => { setAppState((prev) => ({ ...prev, screen })); if (screen === 'profile') setProfileSection((prev) => prev || 'summary'); if (screen === 'jobs') await loadJobs(appState.jobs.length === 0); if (screen === 'admin' && appState.user?.role === 'admin') await loadAdmin(!appState.admin.loaded); });
  const handleSelectJob = withAsync(async (jobId) => { if (appState.jobs.length === 0) await loadJobs(); await loadJob(jobId); });
  const handleRunJob = withAsync(async (jobId) => { await api.runJob(jobId); await loadJobs(false); await loadJob(jobId); if (appState.user?.role === 'admin') await loadAdmin(true); setNotice('Запуск задачи отправлен.'); });
  const handleToggleSubscribe = withAsync(async (job) => { if (job.subscription?.subscribed || job.is_subscribed) await api.unsubscribeJob(job.id); else await api.subscribeJob(job.id); await loadJob(job.id); const jobsResult = await api.getJobs('all'); setAppState((prev) => ({ ...prev, jobs: jobsResult.jobs || prev.jobs })); setNotice(job.subscription?.subscribed || job.is_subscribed ? 'Подписка отключена.' : 'Подписка включена.'); });
  const handleToggleJobStatus = withAsync(async (job) => { await api.updateJob(job.id, { status: job.status === 'paused' ? 'active' : 'paused', version: job.version ?? 1 }); await loadJobs(false); await loadJob(job.id); if (appState.user?.role === 'admin') await loadAdmin(true); setNotice(job.status === 'paused' ? 'Задача возобновлена.' : 'Задача поставлена на паузу.'); });
  const handleUpdateDisplayName = withAsync(async (jobId, displayName) => { const current = appState.activeJob; if (!current) return; await api.updateJob(jobId, { display_name: displayName.trim(), version: current.version ?? 1 }); await loadJobs(false); await loadJob(jobId); setNotice(displayName.trim() ? 'Общее название сохранено.' : 'Общее название очищено.'); });
  const handleSaveNotice = withAsync(async (enabled, text) => { const result = await api.saveAdminChatNotice({ enabled, text: text.trim() }); setAppState((prev) => ({ ...prev, bootstrap: { ...(prev.bootstrap || {}), chat_notice: result.chat_notice }, admin: { ...prev.admin, chatNotice: result.chat_notice } })); setNotice('Объявление обновлено.'); });
  const handleOpenInteractionSetup = () => { setInteractionSetupOpen(false); setProfileSection('response'); setAppState((prev) => ({ ...prev, screen: 'profile' })); };
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
    if (scope === 'policy_field') {
      const nextValue = payload.field === 'source_selection_order'
        ? String(payload.value || '').split(',').map((item) => item.trim()).filter(Boolean)
        : payload.value;
      return { ...prev, processing_policy: { ...(prev.processing_policy || {}), [payload.field]: nextValue } };
    }
    return prev;
  });
  const handleSaveDataPolicy = withAsync(async () => {
    const registryPayload = { source_registry: { version: dataPolicyDraft.source_registry?.version || 1, items: dataPolicyDraft.source_registry?.items || [] } };
    const policyPayload = {
      default_mode: dataPolicyDraft.processing_policy?.default_mode || 'registered_only',
      allow_override: Boolean(dataPolicyDraft.processing_policy?.allow_override),
      allowed_modes: dataPolicyDraft.processing_policy?.allowed_modes || [],
      mode_labels: dataPolicyDraft.processing_policy?.mode_labels || {},
      mode_descriptions: dataPolicyDraft.processing_policy?.mode_descriptions || {},
      default_external_action: dataPolicyDraft.processing_policy?.default_external_action || 'preserve_local_copy',
      source_selection_order: dataPolicyDraft.processing_policy?.source_selection_order || [],
    };
    const [registryResult, policyResult] = await Promise.all([
      api.saveAdminDataSources(registryPayload),
      api.saveAdminProcessingPolicy(policyPayload),
    ]);
    const mergedPolicy = {
      source_registry: registryResult.source_registry || registryPayload.source_registry,
      processing_policy: policyResult.processing_policy || policyPayload,
    };
    setDataPolicyDraft(cloneDataPolicyForDraft(mergedPolicy));
    setRequestPolicyDraft(initialRequestExecutionPolicy(mergedPolicy.processing_policy));
    setAppState((prev) => ({
      ...prev,
      bootstrap: { ...(prev.bootstrap || {}), data_policy: mergedPolicy },
      admin: { ...prev.admin, dataPolicy: mergedPolicy },
    }));
    setNotice('Policy источников обновлена.');
  });
  const toggleExistingFile = (file) => setComposerExistingFiles((prev) => prev.some((item) => Number(item.id) === Number(file.id)) ? prev.filter((item) => Number(item.id) !== Number(file.id)) : [...prev, file]);

  const openCreateJob = () => { setEditingJobId(null); setJobDraft(initialJobDraft(appState.user?.timezone || 'UTC')); setJobModalOpen(true); };
  const openCreateDashboardRefreshJob = (message) => { setEditingJobId(null); setAppState((prev) => ({ ...prev, screen: 'jobs' })); setJobDraft(buildDashboardJobDraft(message, appState.user?.timezone || 'UTC')); setJobModalOpen(true); };
  const openEditJob = (job) => { setEditingJobId(job.id); setJobDraft({ name: job.name || '', version: job.version ?? 1, description: job.description || '', prompt_template: job.prompt_template || '', job_type: job.job_type || appState.jobsMeta?.templates_order?.[0] || 'daily_brief', visibility: job.visibility || 'private', status: job.status || 'active', source_of_truth: job.source_of_truth || 'local_jobs', deliver: job.deliver || job.parameters?.deliver || 'origin', self_subscribe_enabled: Boolean(job.self_subscribe_enabled), self_subscribe_scope: job.self_subscribe_scope || 'visible_users', schedule_kind: job.schedule_kind || 'daily', time_of_day: job.time_of_day || '09:00', timezone: job.timezone || appState.user?.timezone || 'UTC', start_date: job.start_date || new Date().toISOString().slice(0, 10), days_of_week: [...(job.days_of_week || ['mon'])], parameters: { ...(job.parameters || {}) }, access: [...(job.access || []).map((item) => ({ user_id: Number(item.user_id), role: item.role || 'viewer' }))], recipients: [...(job.recipients || []).map((item) => ({ recipient_type: item.recipient_type, target_value: String(item.target_value), label: item.label }))] }); setJobModalOpen(true); };
  const openRecipientsPicker = (job) => setJobMembersModal({ open: true, mode: 'recipients', job });
  const openAccessPicker = (job) => setJobMembersModal({ open: true, mode: 'access', job });
  const closeJobMembersModal = () => setJobMembersModal({ open: false, mode: 'recipients', job: null });
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
  const handleUpdateJobRecipients = withAsync(async (jobId, recipients) => { const current = await api.getJob(jobId); const job = current.job; if (!job) return; const payload = { version: job.version ?? 1, recipients };
    await api.updateJob(jobId, payload);
    await loadJobs(false);
    await loadJob(jobId);
    setJobMembersModal((prev) => prev.open ? { ...prev, job: { ...(prev.job || {}), recipients } } : prev);
    setNotice('Получатели обновлены.');
  });
  const handleUpdateJobAccess = withAsync(async (jobId, access) => { const current = await api.getJob(jobId); const job = current.job; if (!job) return; const payload = { version: job.version ?? 1, access };
    await api.updateJob(jobId, payload);
    await loadJobs(false);
    await loadJob(jobId);
    setJobMembersModal((prev) => prev.open ? { ...prev, job: { ...(prev.job || {}), access } } : prev);
    setNotice('Доступ обновлён.');
  });
  const handleToggleRecipientUserQuick = async (job, user) => { const currentRecipients = [...(job?.recipients || [])]; const exists = currentRecipients.some((item) => item.recipient_type === 'fixed_user' && String(item.target_value) === String(user.id)); const recipients = exists ? currentRecipients.filter((item) => !(item.recipient_type === 'fixed_user' && String(item.target_value) === String(user.id))) : [...currentRecipients, { recipient_type: 'fixed_user', target_value: String(user.id), label: user.name || user.email || `user:${user.id}` }]; await handleUpdateJobRecipients(job.id, recipients); };
  const handleToggleRecipientThreadQuick = async (job, thread) => { const currentRecipients = [...(job?.recipients || [])]; const exists = currentRecipients.some((item) => item.recipient_type === 'fixed_thread' && String(item.target_value) === String(thread.id)); const recipients = exists ? currentRecipients.filter((item) => !(item.recipient_type === 'fixed_thread' && String(item.target_value) === String(thread.id))) : [...currentRecipients, { recipient_type: 'fixed_thread', target_value: String(thread.id), label: thread.title || `chat:${thread.id}` }]; await handleUpdateJobRecipients(job.id, recipients); };
  const handleAddAccessUserQuick = async (job, user) => { const currentAccess = [...(job?.access || [])]; if (currentAccess.some((row) => Number(row.user_id) === Number(user.id))) return; const access = [...currentAccess, { user_id: Number(user.id), role: 'viewer' }]; await handleUpdateJobAccess(job.id, access); };
  const handleRemoveAccessUserQuick = async (job, userId) => { const access = [...(job?.access || [])].filter((row) => Number(row.user_id) !== Number(userId)); await handleUpdateJobAccess(job.id, access); };

  const handleAdminSectionChange = withAsync(async (section) => { setAppState((prev) => ({ ...prev, admin: { ...prev.admin, section } })); if (section === 'operations' || section === 'data_policy') await loadAdmin(true, section); });
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

  return <div className="app-layout"><Sidebar appState={appState} onNavigate={handleNavigate} onCreateThread={handleCreateThread} onSelectThread={handleSelectThread} onOpenThreadsModal={() => setThreadsModalOpen(true)} onLogout={handleLogout} /><main className="main-panel">{(error || notice) ? <div className={`global-banner ${error ? 'error' : 'ok'}`}>{error || notice}</div> : null}{appState.screen === 'chat' ? <ChatScreen appState={appState} composerText={composerText} composerFiles={composerFiles} composerExistingFiles={composerExistingFiles} requestPolicyDraft={requestPolicyDraft} sending={busy} onComposerChange={(e) => setComposerText(e.target.value)} onComposerKeyDown={handleComposerKeyDown} onFileChange={(e) => setComposerFiles(Array.from(e.target.files || []))} onToggleExistingFile={toggleExistingFile} onOpenUserFile={handleOpenUserFile} onApplyStarterPrompt={handleApplyStarterPrompt} onRequestPolicyChange={handleRequestPolicyChange} onToggleRequestSource={handleToggleRequestSource} onSend={handleSend} onRenameThread={handleRenameThread} onArchiveThread={handleArchiveThread} onDismissWelcome={handleDismissChatWelcome} onSaveDashboard={openCreateDashboardRefreshJob} /> : null}{appState.screen === 'profile' ? <ProfileScreen user={appState.user} profileSummary={appState.profileSummary} userFiles={appState.userFiles} profileForm={profileForm} passwordForm={passwordForm} profileSection={profileSection} profileFileQuery={profileFileQuery} profileFileType={profileFileType} bootstrap={appState.bootstrap} onSectionChange={setProfileSection} onProfileFileFilterChange={handleProfileFileFilterChange} onProfileChange={handleProfileChange} onPasswordChange={handlePasswordChange} onSaveProfile={handleSaveProfile} onChangePassword={handleChangePassword} onOpenUserFile={handleOpenUserFile} /> : null}{appState.screen === 'jobs' ? <JobsScreen jobsMeta={appState.jobsMeta} jobs={appState.jobs} activeJob={appState.activeJob} onSelectJob={handleSelectJob} onRunJob={handleRunJob} onToggleSubscribe={handleToggleSubscribe} onUpdateDisplayName={handleUpdateDisplayName} onOpenCreate={openCreateJob} onOpenEdit={openEditJob} onOpenRecipients={openRecipientsPicker} onOpenAccess={openAccessPicker} onToggleStatus={handleToggleJobStatus} /> : null}{appState.screen === 'admin' ? (appState.user?.role === 'admin' ? <AdminScreen admin={{ ...appState.admin, dataPolicy: dataPolicyDraft }} onSectionChange={handleAdminSectionChange} onSaveNotice={handleSaveNotice} selectedUserIds={selectedUserIds} onToggleUser={handleToggleUserSelection} onSelectAllUsers={handleSelectAllUsers} onClearSelection={handleClearSelection} onBulkUserStatus={handleBulkUserStatus} onEditUser={handleEditAdminUser} onOpenCreateUser={handleOpenCreateAdminUser} onEventsFilterChange={handleEventsFilterChange} activeDatasetKey={activeDatasetKey} referenceDraft={referenceDraft} referenceHistory={referenceHistory} selectedReferenceItems={selectedReferenceItems} onOpenDataset={handleOpenDataset} onEditReferenceItem={handleEditReferenceItem} onCreateReferenceItem={handleCreateReferenceItem} onReferenceDraftChange={handleReferenceDraftChange} onSaveReference={handleSaveReference} onToggleReferenceItem={handleToggleReferenceItem} onBulkReferenceStatus={handleBulkReferenceStatus} onPolicyDraftChange={handleDataPolicyDraftChange} onSaveDataPolicy={handleSaveDataPolicy} /> : <div className="screen-shell"><div className="empty-box large">Экран доступен только администратору.</div></div>) : null}</main><JobDraftModal open={jobModalOpen} draft={jobDraft} jobsMeta={appState.jobsMeta} currentUserId={appState.user?.id} currentThreadId={appState.activeThreadId} onClose={() => setJobModalOpen(false)} onChange={handleJobDraftChange} onSave={handleSaveJob} isEditing={Boolean(editingJobId)} /><JobMembersModal open={jobMembersModal.open} mode={jobMembersModal.mode} job={jobMembersModal.job} jobsMeta={appState.jobsMeta} currentUserId={appState.user?.id} currentThreadId={appState.activeThreadId} onClose={closeJobMembersModal} onToggleRecipientUser={handleToggleRecipientUserQuick} onToggleRecipientThread={handleToggleRecipientThreadQuick} onAddAccessUser={handleAddAccessUserQuick} onRemoveAccessUser={handleRemoveAccessUserQuick} /><AdminUserModal open={adminUserModalOpen} userForm={adminUserForm} userHistory={adminUserHistory} onChange={handleAdminUserFormChange} onSave={handleSaveAdminUser} onClose={handleResetAdminUserForm} onImportCsvChange={setImportCsv} onImportCsv={handleImportCsv} importCsv={importCsv} /><ThreadsModal open={threadsModalOpen} threads={appState.threads} activeThreadId={appState.activeThreadId} onSelectThread={handleSelectThread} onHideThread={handleHideThread} onClose={() => setThreadsModalOpen(false)} /><InteractionSetupModal open={interactionSetupOpen} user={appState.user} bootstrap={appState.bootstrap} onOpenProfile={handleOpenInteractionSetup} onDismiss={() => setInteractionSetupOpen(false)} /></div>;
}
