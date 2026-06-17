const STORAGE_KEY = 'hermes_web_mvp_token';

const API_BASE = (import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/$/, '');
const SERVICE_INFO_PATH = (import.meta.env.VITE_SERVICE_INFO_PATH || `${API_BASE}/service-info`).replace(/\/$/, '');

export class ApiError extends Error {
  constructor(message, status = 0, code = '') {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
  }
}

const ERROR_MAP = {
  email_already_exists: 'Пользователь с таким email уже существует.',
  password_too_short: 'Пароль должен быть не короче 8 символов.',
  invalid_credentials: 'Неверный email или пароль.',
  invalid_token: 'Сессия истекла. Войдите снова.',
  invalid_service_response: 'Сервис временно ответил некорректно. Обнови экран и повтори действие.',
  auth_required: 'Нужна авторизация.',
  admin_required: 'Нужны права администратора.',
  version_conflict: 'Данные уже изменились в другой сессии. Обнови экран и повтори действие.',
  current_password_invalid: 'Текущий пароль указан неверно.',
  content_required: 'Нужно добавить текст или файл.',
  file_not_found: 'Файл не найден.',
  too_many_files: 'В одном сообщении можно использовать не больше 5 файлов.',
  import_rows_required: 'Нужны строки для импорта.',
  job_self_subscribe_forbidden: 'Самоподписка для этой задачи недоступна.',
  reference_item_exists: 'Элемент справочника с таким ключом уже существует.',
  import_password_too_short: 'Пароль должен быть не короче 8 символов.',
  reference_item_required: 'Нужно указать ключ и название элемента справочника.',
  hermes_cron_recipients_unsupported: 'Для задач Hermes Cron назначение получателей через пользователей интерфейса пока не поддерживается. Здесь можно только смотреть текущую цель доставки.',
  unsupported_export_format: 'Такой формат экспорта пока не поддерживается.',
  message_export_role_unsupported: 'Это сообщение пока нельзя экспортировать как файл.',
  export_dependency_missing_docx: 'Экспорт в Word сейчас временно недоступен на сервере.',
  export_dependency_missing_xlsx: 'Экспорт в Excel сейчас временно недоступен на сервере.',
  export_dependency_missing_pdf: 'Экспорт в PDF сейчас временно недоступен на сервере.',
};

function humanizeApiError(code, fallbackStatus) {
  return ERROR_MAP[code] || code || fallbackStatus || 'Ошибка запроса';
}

export function getStoredToken() {
  return window.localStorage.getItem(STORAGE_KEY) || '';
}

export function setStoredToken(token) {
  if (token) window.localStorage.setItem(STORAGE_KEY, token);
  else window.localStorage.removeItem(STORAGE_KEY);
}

function buildAuthorizedRequestUrl(path, token, { includeTokenInQuery = false } = {}) {
  const normalizedPath = String(path || '');
  const requestUrl = normalizedPath.startsWith('http://') || normalizedPath.startsWith('https://')
    ? normalizedPath
    : normalizedPath.startsWith(API_BASE)
      ? normalizedPath
      : `${API_BASE}${normalizedPath.startsWith('/') ? normalizedPath : `/${normalizedPath}`}`;
  if (!includeTokenInQuery || !token) return requestUrl;
  const url = new URL(requestUrl, window.location.origin);
  if (!url.searchParams.has('access_token')) url.searchParams.set('access_token', token);
  return `${url.pathname}${url.search}${url.hash}`;
}

async function openAuthorizedUrl(path, preferredName = 'file') {
  const token = getStoredToken();
  const requestUrl = buildAuthorizedRequestUrl(path, token, { includeTokenInQuery: true });
  const link = document.createElement('a');
  link.href = requestUrl;
  link.target = '_blank';
  link.rel = 'noopener noreferrer';
  link.dataset.filename = preferredName;
  document.body.appendChild(link);
  link.click();
  link.remove();
  return { opened: true, name: preferredName };
}

async function downloadAuthorizedUrl(path, preferredName = 'file') {
  const headers = {};
  const token = getStoredToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const requestUrl = buildAuthorizedRequestUrl(path, token);
  const response = await fetch(requestUrl, { headers });
  if (!response.ok) {
    const text = await response.text();
    let data = {};
    if (text) {
      try { data = JSON.parse(text); } catch {}
    }
    throw new ApiError(humanizeApiError(data.error, `HTTP ${response.status}`), response.status, data.error || '');
  }
  const blob = await response.blob();
  const objectUrl = window.URL.createObjectURL(blob);
  const disposition = response.headers.get('content-disposition') || '';
  const asciiMatch = disposition.match(/filename="?([^";]+)"?/i);
  const utfMatch = disposition.match(/filename\*=UTF-8''([^;]+)/i);
  const serverName = utfMatch ? decodeURIComponent(utfMatch[1]) : (asciiMatch ? asciiMatch[1] : '');
  const filename = serverName || preferredName;
  const link = document.createElement('a');
  link.href = objectUrl;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => window.URL.revokeObjectURL(objectUrl), 60_000);
  return { downloaded: true, name: filename };
}

async function requestAbsolute(url, options = {}) {
  const headers = { ...(options.headers || {}) };
  const token = getStoredToken();
  if (!(options.body instanceof FormData) && !headers['Content-Type']) headers['Content-Type'] = 'application/json';
  if (token) headers.Authorization = `Bearer ${token}`;
  const response = await fetch(url, { ...options, headers });
  const text = await response.text();
  let data = {};
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      throw new ApiError(`Сервис вернул не JSON (${response.status})`, response.status);
    }
  }
  if (!response.ok) throw new ApiError(humanizeApiError(data.error, `HTTP ${response.status}`), response.status, data.error || '');
  return data;
}

function request(path, options = {}) {
  return requestAbsolute(`${API_BASE}${path}`, options);
}

function requestPublicJson(url) {
  return requestAbsolute(url, { headers: { Accept: 'application/json' } });
}

function buildQuery(params = {}) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return;
    search.set(key, String(value));
  });
  const query = search.toString();
  return query ? `?${query}` : '';
}

export const api = {
  getServiceInfo: () => requestPublicJson(SERVICE_INFO_PATH),
  getSetupStatus: () => requestPublicJson(`${API_BASE}/setup/status`),
  login: (email, password) => request('/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) }),
  restoreSession: () => request('/auth/session'),
  logout: () => request('/auth/logout', { method: 'POST' }),
  bootstrapAdmin: (payload) => request('/setup/bootstrap-admin', { method: 'POST', body: JSON.stringify(payload) }),
  getMe: () => request('/me'),
  saveMe: (payload) => request('/me', { method: 'PATCH', body: JSON.stringify(payload) }),
  changePassword: (currentPassword, newPassword) => request('/me/change-password', { method: 'POST', body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }) }),
  getBootstrap: () => request('/bootstrap'),
  getFeedbackReasons: () => request('/feedback/reasons'),
  getFiles: (limit = 200) => request(`/files?limit=${limit}`),
  openFile: (file) => openAuthorizedUrl(file?.download_url || `/files/${encodeURIComponent(file?.id)}/download`, file?.original_name || 'file'),
  getThreads: () => request('/threads?include_archived=1'),
  getThread: (threadId) => request(`/threads/${threadId}`),
  createThread: () => request('/threads', { method: 'POST', body: JSON.stringify({ title: 'Новый чат', preview: 'Новый чат' }) }),
  updateThread: (threadId, payload) => request(`/threads/${threadId}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  sendMessage: (threadId, payload) => payload instanceof FormData ? request(`/threads/${threadId}/messages`, { method: 'POST', body: payload }) : request(`/threads/${threadId}/messages`, { method: 'POST', body: JSON.stringify(payload) }),
  exportMessage: (messageId, format = 'txt') => downloadAuthorizedUrl(`/messages/${encodeURIComponent(messageId)}/export?format=${encodeURIComponent(format)}`, `assistant-message.${format}`),
  getJobsMeta: () => request('/jobs/meta'),
  getJobs: (scope = 'all') => request(`/jobs?scope=${encodeURIComponent(scope)}`),
  createJob: (payload) => request('/jobs', { method: 'POST', body: JSON.stringify(payload) }),
  getJob: (jobId) => request(`/jobs/${encodeURIComponent(jobId)}`),
  updateJob: (jobId, payload) => request(`/jobs/${encodeURIComponent(jobId)}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  runJob: (jobId) => request(`/jobs/${encodeURIComponent(jobId)}/run`, { method: 'POST' }),
  getJobRuns: (jobId) => request(`/jobs/${encodeURIComponent(jobId)}/runs`),
  subscribeJob: (jobId) => request(`/jobs/${encodeURIComponent(jobId)}/subscribe`, { method: 'POST' }),
  unsubscribeJob: (jobId) => request(`/jobs/${encodeURIComponent(jobId)}/unsubscribe`, { method: 'POST' }),
  getAdminHealth: () => request('/admin/health'),
  getAdminOverviewTimeseries: (granularity = 'day') => request(`/admin/overview-timeseries${buildQuery({ granularity })}`),
  getAdminUsers: () => request('/admin/users'),
  getAdminUser: (userId) => request(`/admin/users/${userId}`),
  createAdminUser: (payload) => request('/admin/users', { method: 'POST', body: JSON.stringify(payload) }),
  updateAdminUser: (userId, payload) => request(`/admin/users/${userId}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  bulkAdminUsers: (payload) => request('/admin/users/bulk-status', { method: 'POST', body: JSON.stringify(payload) }),
  getAdminUserHistory: (userId) => request(`/admin/users/${userId}/history`),
  importAdminUsersCsv: (payload) => request('/admin/users/import', { method: 'POST', body: JSON.stringify(payload) }),
  getAdminThreads: () => request('/admin/threads'),
  getAdminJobs: () => request('/admin/jobs'),
  getAdminReferenceData: () => request('/admin/reference-data'),
  createAdminReferenceItem: (datasetKey, payload) => request(`/admin/reference-data/${encodeURIComponent(datasetKey)}/items`, { method: 'POST', body: JSON.stringify(payload) }),
  updateAdminReferenceItem: (datasetKey, itemKey, payload) => request(`/admin/reference-data/${encodeURIComponent(datasetKey)}/items/${encodeURIComponent(itemKey)}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  bulkAdminReferenceItems: (datasetKey, payload) => request(`/admin/reference-data/${encodeURIComponent(datasetKey)}/bulk-status`, { method: 'POST', body: JSON.stringify(payload) }),
  getAdminReferenceItemHistory: (datasetKey, itemKey) => request(`/admin/reference-data/${encodeURIComponent(datasetKey)}/items/${encodeURIComponent(itemKey)}/history`),
  getAdminDashboardPolicy: () => request('/admin/dashboard-policy'),
  saveAdminDashboardPolicy: (payload) => request('/admin/dashboard-policy', { method: 'PATCH', body: JSON.stringify(payload) }),
  getAdminChatNotice: () => request('/admin/chat-notice'),
  saveAdminChatNotice: (payload) => request('/admin/chat-notice', { method: 'PATCH', body: JSON.stringify(payload) }),
  getAdminEvents: (params = {}) => request(`/admin/events${buildQuery(params)}`),
  adminEventsExportUrl: (params = {}, format = 'csv') => `${API_BASE}/admin/events${buildQuery({ ...params, export: format })}`,
  requestAbsolute,
};
