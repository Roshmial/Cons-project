const APP_CONFIG = window.__APP_CONFIG__ || {};
const API_BASE = (APP_CONFIG.apiBaseUrl || '/api').replace(/\/$/, '');
const SERVICE_INFO_PATH = (APP_CONFIG.serviceInfoPath || `${API_BASE}/service-info`).replace(/\/$/, '');
const STORAGE_KEY = 'hermes_web_mvp_token';
const THREAD_READ_STORAGE_KEY = 'hermes_web_mvp_thread_reads';
const WEEKDAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'];
const WEEKDAY_LABELS = { mon: 'Пн', tue: 'Вт', wed: 'Ср', thu: 'Чт', fri: 'Пт', sat: 'Сб', sun: 'Вс' };

const state = {
  token: localStorage.getItem(STORAGE_KEY),
  screen: 'chat',
  user: null,
  personalization: '',
  profileSummary: null,
  bootstrap: null,
  threads: [],
  activeThreadId: null,
  messages: [],
  feedbackReasons: [],
  showArchived: false,
  showAllThreads: false,
  jobs: [],
  jobsMeta: null,
  activeJobId: null,
  jobScope: 'all',
  jobSearchQuery: '',
  jobNameEditMode: false,
  admin: {
    health: null,
    users: [],
    selectedUserIds: [],
    selectedReferenceItems: {},
    threads: [],
    jobs: [],
    events: [],
    eventsFilter: { dateFrom: '', dateTo: '', limit: 100 },
    sources: null,
    references: {},
    editingUserId: null,
    editingUserVersion: null,
    userHistory: [],
    referenceHistory: {},
    chatNotice: null,
    overviewTimeseries: { granularity: 'day', buckets: [] },
    userSort: { key: 'name', direction: 'asc' },
  },
  mode: '-',
  serviceStatus: 'Подключение…',
  lastAssistantMessageId: null,
  pendingFiles: [],
  pendingExistingFiles: [],
  userFiles: [],
  fileFilterQuery: '',
  fileFilterType: 'all',
  fileFilterScope: 'all',
  profileSection: 'identity',
  adminSection: 'overview',
  isSending: false,
  chatWelcomeDismissed: false,
  jobDraft: null,
  editingJobId: null,
  setupRequired: false,
  demoMode: false,
  threadReadMap: {},
  uiRefreshTimer: null,
  isRefreshingThreads: false,
  isRefreshingJobs: false,
  isRefreshingAdmin: false,
  threadLoadRequestSeq: 0,
  activeThreadLoadSeq: 0,
};

const els = {
  loginScreen: document.getElementById('loginScreen'),
  appShell: document.getElementById('appShell'),
  appContent: document.querySelector('#appShell .content'),
  loginInput: document.getElementById('loginInput'),
  passwordInput: document.getElementById('passwordInput'),
  loginBtn: document.getElementById('loginBtn'),
  loginError: document.getElementById('loginError'),
  setupCard: document.getElementById('setupCard'),
  setupNameInput: document.getElementById('setupNameInput'),
  setupEmailInput: document.getElementById('setupEmailInput'),
  setupPasswordInput: document.getElementById('setupPasswordInput'),
  setupBtn: document.getElementById('setupBtn'),
  logoutBtn: document.getElementById('logoutBtn'),
  threadList: document.getElementById('threadList'),
  allThreadsBtn: document.getElementById('allThreadsBtn'),
  toggleArchivedBtn: document.getElementById('toggleArchivedBtn'),
  refreshBtn: document.getElementById('refreshBtn'),
  mainTitle: document.getElementById('mainTitle'),
  mainSubtitle: document.getElementById('mainSubtitle'),
  statusText: document.getElementById('statusText'),
  topbarProfileBtn: document.getElementById('topbarProfileBtn'),
  sidebarUserLabel: document.getElementById('sidebarUserLabel'),
  sidebarUserRole: document.getElementById('sidebarUserRole'),
  banner: document.getElementById('banner'),
  adminNavBtn: document.getElementById('adminNavBtn'),

  screenChat: document.getElementById('screenChat'),
  screenJobs: document.getElementById('screenJobs'),
  screenProfile: document.getElementById('screenProfile'),
  screenAdmin: document.getElementById('screenAdmin'),
  navButtons: Array.from(document.querySelectorAll('[data-screen]')),

  chatWelcome: document.getElementById('chatWelcome'),
  chatIntroCard: document.querySelector('.chat-intro-card'),
  chatPolicyBanner: document.getElementById('chatPolicyBanner'),
  topbarChatGuide: document.getElementById('topbarChatGuide'),
  chatThreadHeader: document.querySelector('.chat-thread-header'),
  chatThreadTitle: document.getElementById('chatThreadTitle'),
  chatMessages: document.getElementById('chatMessages'),
  chatConversationScroll: document.querySelector('.chat-conversation-scroll'),
  chatScrollTopBtn: document.getElementById('chatScrollTopBtn'),
  composer: document.getElementById('composer'),
  promptInput: document.getElementById('promptInput'),
  fileInput: document.getElementById('fileInput'),
  attachFileBtn: document.getElementById('attachFileBtn'),
  selectedFiles: document.getElementById('selectedFiles'),
  fileHint: document.getElementById('fileHint'),
  composerStatus: document.getElementById('composerStatus'),
  sendBtn: document.getElementById('sendBtn'),
  renameThreadBtn: document.getElementById('renameThreadBtn'),
  archiveThreadBtn: document.getElementById('archiveThreadBtn'),
  newThreadBtn: document.getElementById('newThreadBtn'),

  profileName: document.getElementById('profileName'),
  profileTimezone: document.getElementById('profileTimezone'),
  profileLanguage: document.getElementById('profileLanguage'),
  profileTeam: document.getElementById('profileTeam'),
  profileTitle: document.getElementById('profileTitle'),
  profileGoals: document.getElementById('profileGoals'),
  profileConstraints: document.getElementById('profileConstraints'),
  profilePinned: document.getElementById('profilePinned'),
  profileTone: document.getElementById('profileTone'),
  profileDepth: document.getElementById('profileDepth'),
  profileMode: document.getElementById('profileMode'),
  profileAbout: document.getElementById('profileAbout'),
  profileStylePreview: document.getElementById('profileStylePreview'),
  profileIdentityCard: document.getElementById('profileIdentityCard'),
  profileResponseCard: document.getElementById('profileResponseCard'),
  profileFilesCard: document.getElementById('profileFilesCard'),
  profileSectionSummary: document.getElementById('profileSectionSummary'),
  profileSectionIdentity: document.getElementById('profileSectionIdentity'),
  profileSectionResponse: document.getElementById('profileSectionResponse'),
  profileSectionFiles: document.getElementById('profileSectionFiles'),
  profileTabs: Array.from(document.querySelectorAll('[data-profile-section]')),
  profileFilesMeta: document.getElementById('profileFilesMeta'),
  profileFileSearch: document.getElementById('profileFileSearch'),
  profileFileScopeFilter: document.getElementById('profileFileScopeFilter'),
  profileFileTypeFilter: document.getElementById('profileFileTypeFilter'),
  profileFiles: document.getElementById('profileFiles'),
  profileCurrentPassword: document.getElementById('profileCurrentPassword'),
  profileNewPassword: document.getElementById('profileNewPassword'),
  changePasswordBtn: document.getElementById('changePasswordBtn'),
  profilePasswordHint: document.getElementById('profilePasswordHint'),
  saveProfileBtn: document.getElementById('saveProfileBtn'),
  profileSaveHint: document.getElementById('profileSaveHint'),

  jobsList: document.getElementById('jobsList'),
  jobDetail: document.getElementById('jobDetail'),
  newJobBtn: document.getElementById('newJobBtn'),
  jobScopeFilter: document.getElementById('jobScopeFilter'),
  jobSearchInput: document.getElementById('jobSearchInput'),
  jobsMetaNote: document.getElementById('jobsMetaNote'),

  adminMetrics: document.getElementById('adminMetrics'),
  adminCharts: document.getElementById('adminCharts'),
  adminUsers: document.getElementById('adminUsers'),
  adminUsersTable: document.getElementById('adminUsersTable'),
  adminSelectAllUsersBtn: document.getElementById('adminSelectAllUsersBtn'),
  adminClearUserSelectionBtn: document.getElementById('adminClearUserSelectionBtn'),
  adminBulkInactiveUsersBtn: document.getElementById('adminBulkInactiveUsersBtn'),
  adminBulkDeleteUsersBtn: document.getElementById('adminBulkDeleteUsersBtn'),
  adminUserSelectionStatus: document.getElementById('adminUserSelectionStatus'),
  adminThreads: document.getElementById('adminThreads'),
  adminJobs: document.getElementById('adminJobs'),
  adminEvents: document.getElementById('adminEvents'),
  adminEventsDateFrom: document.getElementById('adminEventsDateFrom'),
  adminEventsDateTo: document.getElementById('adminEventsDateTo'),
  adminEventsApplyBtn: document.getElementById('adminEventsApplyBtn'),
  adminEventsResetBtn: document.getElementById('adminEventsResetBtn'),
  adminEventsExportCsvBtn: document.getElementById('adminEventsExportCsvBtn'),
  adminEventsExportJsonBtn: document.getElementById('adminEventsExportJsonBtn'),
  adminEventsStatus: document.getElementById('adminEventsStatus'),
  adminDbInfo: document.getElementById('adminDbInfo'),
  adminSources: document.getElementById('adminSources'),
  adminReferenceData: document.getElementById('adminReferenceData'),
  adminUserFormMode: document.getElementById('adminUserFormMode'),
  adminUserSelect: document.getElementById('adminUserSelect'),
  adminUserEmail: document.getElementById('adminUserEmail'),
  adminUserName: document.getElementById('adminUserName'),
  adminUserRole: document.getElementById('adminUserRole'),
  adminUserStatusSelect: document.getElementById('adminUserStatusSelect'),
  adminUserPassword: document.getElementById('adminUserPassword'),
  adminUserTimezone: document.getElementById('adminUserTimezone'),
  adminUserLanguage: document.getElementById('adminUserLanguage'),
  adminUserTeam: document.getElementById('adminUserTeam'),
  adminUserTitle: document.getElementById('adminUserTitle'),
  adminUserGoals: document.getElementById('adminUserGoals'),
  adminUserConstraints: document.getElementById('adminUserConstraints'),
  adminUserTone: document.getElementById('adminUserTone'),
  adminUserDepth: document.getElementById('adminUserDepth'),
  adminUserMode: document.getElementById('adminUserMode'),
  adminUserAbout: document.getElementById('adminUserAbout'),
  adminUserPinned: document.getElementById('adminUserPinned'),
  adminUserStylePreview: document.getElementById('adminUserStylePreview'),
  adminUserSaveBtn: document.getElementById('adminUserSaveBtn'),
  adminUserResetBtn: document.getElementById('adminUserResetBtn'),
  adminUserStatus: document.getElementById('adminUserStatus'),
  adminUserHistory: document.getElementById('adminUserHistory'),
  adminImportCsv: document.getElementById('adminImportCsv'),
  adminImportBtn: document.getElementById('adminImportBtn'),
  adminTemplateBtn: document.getElementById('adminTemplateBtn'),
  adminImportStatus: document.getElementById('adminImportStatus'),
  adminReferenceStatus: document.getElementById('adminReferenceStatus'),
  adminChatNoticeEnabled: document.getElementById('adminChatNoticeEnabled'),
  adminChatNoticeText: document.getElementById('adminChatNoticeText'),
  adminChatNoticeSaveBtn: document.getElementById('adminChatNoticeSaveBtn'),
  adminChatNoticeStatus: document.getElementById('adminChatNoticeStatus'),
  adminSectionTabs: Array.from(document.querySelectorAll('[data-admin-section]')),
  adminPanels: Array.from(document.querySelectorAll('[data-admin-panel]')),
  adminReferenceDetail: document.getElementById('adminReferenceDetail'),
  adminUserCard: document.getElementById('adminUserCard'),
  adminUserCardTitle: document.getElementById('adminUserCardTitle'),
  adminUserCardSubtitle: document.getElementById('adminUserCardSubtitle'),
  adminOpenCreateUserBtn: document.getElementById('adminOpenCreateUserBtn'),
  adminCloseUserCardBtn: document.getElementById('adminCloseUserCardBtn'),
  adminReferenceCard: document.getElementById('adminReferenceCard'),
  adminCloseReferenceCardBtn: document.getElementById('adminCloseReferenceCardBtn'),
  adminReferenceCardTitle: document.getElementById('adminReferenceCardTitle'),
  adminReferenceCardSubtitle: document.getElementById('adminReferenceCardSubtitle'),
  adminReferenceItemCard: document.getElementById('adminReferenceItemCard'),
  adminCloseReferenceItemCardBtn: document.getElementById('adminCloseReferenceItemCardBtn'),
  adminReferenceItemCardTitle: document.getElementById('adminReferenceItemCardTitle'),
  adminReferenceItemCardSubtitle: document.getElementById('adminReferenceItemCardSubtitle'),
  adminReferenceItemMode: document.getElementById('adminReferenceItemMode'),
  adminReferenceItemDatasetKey: document.getElementById('adminReferenceItemDatasetKey'),
  adminReferenceItemKeyInput: document.getElementById('adminReferenceItemKeyInput'),
  adminReferenceItemLabelInput: document.getElementById('adminReferenceItemLabelInput'),
  adminReferenceItemSortOrderInput: document.getElementById('adminReferenceItemSortOrderInput'),
  adminReferenceItemStatusSelect: document.getElementById('adminReferenceItemStatusSelect'),
  adminReferenceItemPayloadInput: document.getElementById('adminReferenceItemPayloadInput'),
  adminReferenceItemStatus: document.getElementById('adminReferenceItemStatus'),
  adminReferenceItemSaveBtn: document.getElementById('adminReferenceItemSaveBtn'),
  adminChartGranularity: document.getElementById('adminChartGranularity'),

  jobModalBackdrop: document.getElementById('jobModalBackdrop'),
  closeJobModalBtn: document.getElementById('closeJobModalBtn'),
  saveJobBtn: document.getElementById('saveJobBtn'),
  jobModalTitle: document.getElementById('jobModalTitle'),
  jobNameInput: document.getElementById('jobNameInput'),
  jobTypeSelect: document.getElementById('jobTypeSelect'),
  jobDescriptionInput: document.getElementById('jobDescriptionInput'),
  jobPromptInput: document.getElementById('jobPromptInput'),
  jobVisibilitySelect: document.getElementById('jobVisibilitySelect'),
  jobStatusSelect: document.getElementById('jobStatusSelect'),
  jobSelfSubscribeEnabledSelect: document.getElementById('jobSelfSubscribeEnabledSelect'),
  jobSelfSubscribeScopeSelect: document.getElementById('jobSelfSubscribeScopeSelect'),
  jobSelfSubscribeHint: document.getElementById('jobSelfSubscribeHint'),
  jobCronDeliveryCard: document.getElementById('jobCronDeliveryCard'),
  jobCronDeliverSelect: document.getElementById('jobCronDeliverSelect'),
  jobCronDeliverHint: document.getElementById('jobCronDeliverHint'),
  jobRecipientsCard: document.getElementById('jobRecipientsCard'),
  jobScheduleKindSelect: document.getElementById('jobScheduleKindSelect'),
  jobTimeInput: document.getElementById('jobTimeInput'),
  jobTimezoneInput: document.getElementById('jobTimezoneInput'),
  jobStartDateInput: document.getElementById('jobStartDateInput'),
  jobWeeklyDays: document.getElementById('jobWeeklyDays'),
  jobSchedulePreview: document.getElementById('jobSchedulePreview'),
  jobTemplateFields: document.getElementById('jobTemplateFields'),
  jobAccessList: document.getElementById('jobAccessList'),
  addAccessBtn: document.getElementById('addAccessBtn'),
  jobRecipientList: document.getElementById('jobRecipientList'),
  threadsModalBackdrop: document.getElementById('threadsModalBackdrop'),
  threadsModalList: document.getElementById('threadsModalList'),
  closeThreadsModalBtn: document.getElementById('closeThreadsModalBtn'),
  scrollTopButtons: Array.from(document.querySelectorAll('[data-scroll-top]')),
};

function humanizeApiError(code, fallbackStatus) {
  const mapping = {
    email_already_exists: 'Пользователь с таким email уже существует.',
    password_too_short: 'Пароль должен быть не короче 10 символов.',
    version_conflict: 'Данные были изменены в другой сессии или другим пользователем. Обнови экран и повтори сохранение.',
    user_not_found: 'Пользователь не найден.',
    reference_item_required: 'Нужно заполнить обязательные поля элемента справочника.',
    reference_item_exists: 'Элемент справочника с таким ключом уже существует.',
    reference_item_not_found: 'Элемент справочника не найден.',
    reference_dataset_not_found: 'Справочник не найден.',
    admin_required: 'Нужны права администратора.',
    auth_required: 'Нужна авторизация.',
    invalid_token: 'Сессия истекла. Войди заново.',
    invalid_service_response: 'Сервис временно ответил некорректно. Обнови экран и повтори действие.',
    assistant_profile_invalid_tone: 'Выбранный тон отключён или отсутствует в справочнике.',
    assistant_profile_invalid_answer_depth: 'Выбранная глубина отключена или отсутствует в справочнике.',
    assistant_profile_invalid_interaction_mode: 'Выбранная манера взаимодействия отключена или отсутствует в справочнике.',
    job_self_subscribe_forbidden: 'Самоподписка для этой задачи недоступна.',
    job_self_subscribe_scope_invalid: 'У задачи указан некорректный режим самоподписки.',
  };
  return mapping[code] || code || fallbackStatus;
}

async function api(path, options = {}) {
  const headers = Object.assign({}, options.headers || {});
  if (!(options.body instanceof FormData) && !headers['Content-Type']) {
    headers['Content-Type'] = 'application/json';
  }
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  const response = await fetch(`${API_BASE}${path}`, { ...options, headers });
  const text = await response.text();
  let data = {};
  if (text) {
    try {
      data = JSON.parse(text);
    } catch (error) {
      throw new Error(humanizeApiError('invalid_service_response', `HTTP ${response.status}`));
    }
  }
  if (!response.ok) throw new Error(humanizeApiError(data.error, `HTTP ${response.status}`));
  return data;
}

function setToken(token) {
  state.token = token;
  if (token) localStorage.setItem(STORAGE_KEY, token);
  else localStorage.removeItem(STORAGE_KEY);
}

function showBanner(text, isError = true) {
  els.banner.textContent = text;
  els.banner.classList.remove('hidden');
  els.banner.classList.toggle('info-banner', !isError);
  els.banner.style.borderColor = isError ? 'rgba(251, 113, 133, 0.45)' : 'var(--line)';
  els.banner.style.background = isError ? 'rgba(251, 113, 133, 0.12)' : '#fff';
  els.banner.style.color = isError ? '#ffd7df' : 'var(--text)';
}

function showInfoBanner(text) {
  showBanner(text, false);
}

function jobVisualName(job) {
  return String(job?.display_name || '').trim() || job?.name || 'Без названия';
}

function jobLastOutcomeLabel(job) {
  const status = String(job?.last_run_status || '').trim();
  if (!status) return 'Без запусков';
  return humanizeStatus(status);
}

function jobNextRunLabel(job) {
  return job?.next_run_at ? formatTs(job.next_run_at) : 'Не запланирован';
}

function formatTsCompact(value) {
  if (!value) return '—';
  return new Date(value).toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function filterVisibleJobs(jobs) {
  const query = String(state.jobSearchQuery || '').trim().toLowerCase();
  if (!query) return jobs;
  return jobs.filter(job => {
    const haystack = [
      jobVisualName(job),
      job?.name,
      job?.display_name,
      job?.schedule_summary,
      job?.last_run_summary,
      job?.last_run_status,
      job?.status,
    ].filter(Boolean).join(' ').toLowerCase();
    return haystack.includes(query);
  });
}

function openJobNameEditor() {
  state.jobNameEditMode = true;
  renderJobDetail();
  requestAnimationFrame(() => els.jobDetail.querySelector('#jobAliasInput')?.focus());
}

function closeJobNameEditor() {
  state.jobNameEditMode = false;
}

function summarizeJobRecipients(job) {
  const recipients = job?.recipients || [];
  if (!recipients.length) return 'отдельные чаты задач не выбраны';
  if (recipients.length === 1) return recipients[0].label || recipients[0].target_value || '1 чат';
  return `${recipients.length} чата`;
}

function isHermesCronJob(job) {
  return job?.source_of_truth === 'hermes_cron';
}

function humanizeCronDeliverTarget(value) {
  const target = String(value || '').trim();
  if (!target || target === 'origin') return 'исходный чат запуска';
  if (target === 'local') return 'только локально';
  if (target === 'telegram') return 'Telegram home';
  return target;
}

function applyJobModalMode() {
  const isCron = state.jobDraft?.source_of_truth === 'hermes_cron';
  const localOnlyCards = [document.getElementById('jobParamsCard'), document.getElementById('jobAccessCard'), document.getElementById('jobSelfSubscribeCard'), els.jobRecipientsCard];
  localOnlyCards.forEach(node => node?.classList.toggle('hidden', isCron));
  els.jobCronDeliveryCard?.classList.toggle('hidden', !isCron);
  els.jobTypeSelect.disabled = isCron;
  els.jobDescriptionInput.disabled = isCron;
  els.jobPromptInput.disabled = isCron;
  els.jobVisibilitySelect.disabled = isCron;
  els.jobScheduleKindSelect.disabled = isCron;
  els.jobTimeInput.disabled = isCron;
  els.jobTimezoneInput.disabled = isCron;
  els.jobStartDateInput.disabled = isCron;
  if (els.jobWeeklyDays) {
    Array.from(els.jobWeeklyDays.querySelectorAll('button')).forEach(button => {
      button.disabled = isCron;
    });
  }
  if (isCron && els.jobCronDeliverHint) {
    els.jobCronDeliverHint.textContent = 'Для Hermes cron можно безопасно менять только deliver target: в исходный чат запуска, в Telegram home или оставить локально.';
  }
}

function summarizeJobAccess(job) {
  const accessCount = (job?.access || []).length;
  if (job?.visibility === 'private') return 'видна только создателю и администратору';
  if (job?.visibility === 'workspace') return 'видна всей рабочей области';
  if (!accessCount) return 'допуск не задан';
  return `${accessCount} в доступе`;
}

function userSortValue(user, key) {
  if (key === 'name') return String(user?.name || '').toLowerCase();
  if (key === 'email') return String(user?.email || '').toLowerCase();
  if (key === 'role') return String(user?.role || '').toLowerCase();
  if (key === 'status') return String(user?.status || (user?.deleted_at ? 'deleted' : (user?.is_active === false ? 'inactive' : 'active'))).toLowerCase();
  if (key === 'thread_count') return Number(user?.thread_count || 0);
  if (key === 'job_count') return Number(user?.job_count || 0);
  if (key === 'active_sessions') return Number(user?.active_sessions || 0);
  return String(user?.[key] || '').toLowerCase();
}

function getSortedAdminUsers() {
  const users = [...(state.admin?.users || [])];
  const sort = state.admin?.userSort || { key: 'name', direction: 'asc' };
  const direction = sort.direction === 'desc' ? -1 : 1;
  users.sort((a, b) => {
    const aValue = userSortValue(a, sort.key);
    const bValue = userSortValue(b, sort.key);
    if (typeof aValue === 'number' && typeof bValue === 'number') {
      if (aValue === bValue) return Number(a.id || 0) - Number(b.id || 0);
      return (aValue - bValue) * direction;
    }
    const compared = String(aValue).localeCompare(String(bValue), 'ru', { sensitivity: 'base' });
    if (compared === 0) return (Number(a.id || 0) - Number(b.id || 0)) * direction;
    return compared * direction;
  });
  return users;
}

function setAdminUserSort(key) {
  const current = state.admin?.userSort || { key: 'name', direction: 'asc' };
  const nextDirection = current.key === key && current.direction === 'asc' ? 'desc' : 'asc';
  state.admin.userSort = { key, direction: nextDirection };
  renderAdmin();
}

function sortButtonLabel(label, key) {
  const sort = state.admin?.userSort || { key: 'name', direction: 'asc' };
  const active = sort.key === key;
  const arrow = !active ? '↕' : (sort.direction === 'asc' ? '↑' : '↓');
  return `<button type="button" class="sort-btn ${active ? 'active' : ''}" data-admin-user-sort="${key}"><span>${label}</span><span class="sort-arrow">${arrow}</span></button>`;
}

function hideBanner() {
  els.banner.textContent = '';
  els.banner.classList.add('hidden');
  els.banner.classList.remove('info-banner');
}

function loadThreadReadMap() {
  try {
    return JSON.parse(localStorage.getItem(THREAD_READ_STORAGE_KEY) || '{}') || {};
  } catch {
    return {};
  }
}

function saveThreadReadMap() {
  localStorage.setItem(THREAD_READ_STORAGE_KEY, JSON.stringify(state.threadReadMap || {}));
}

function threadUnread(thread) {
  if (!thread || !thread.last_message_at) return false;
  if (Number(thread.id) === Number(state.activeThreadId)) return false;
  const seenAt = state.threadReadMap?.[String(thread.id)] || '';
  return !seenAt || new Date(thread.last_message_at).getTime() > new Date(seenAt).getTime();
}

function markThreadRead(threadId, timestamp = null) {
  if (!threadId) return;
  const thread = state.threads.find(item => Number(item.id) === Number(threadId));
  state.threadReadMap[String(threadId)] = timestamp || thread?.last_message_at || new Date().toISOString();
  saveThreadReadMap();
}

function scrollChatToBottom() {
  requestAnimationFrame(() => {
    const host = els.chatConversationScroll || els.chatMessages;
    host.scrollTop = host.scrollHeight;
  });
}

function scrollChatToTop() {
  requestAnimationFrame(() => {
    const host = els.chatConversationScroll || els.chatMessages;
    host.scrollTop = 0;
  });
}

function scrollMainToTop() {
  if (state.screen === 'chat' && (els.chatConversationScroll || els.chatMessages)) {
    scrollChatToTop();
    return;
  }
  if (els.appContent) {
    els.appContent.scrollTo({ top: 0, behavior: 'smooth' });
    return;
  }
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function updateChatScrollUi() {
  if (!els.chatScrollTopBtn) return;
  if (state.screen !== 'chat') {
    els.chatScrollTopBtn.classList.add('hidden');
    return;
  }
  const host = els.chatConversationScroll || els.chatMessages;
  const scrollTop = host?.scrollTop || 0;
  els.chatScrollTopBtn.classList.toggle('hidden', scrollTop < 280);
}

function pinChatIntroWithinScreen() {
  if (!els.chatIntroCard) return;
  els.chatIntroCard.style.position = 'relative';
  els.chatIntroCard.style.top = 'auto';
  els.chatIntroCard.style.zIndex = '1';
}

function buildJobPromptFromThread(thread = getActiveThread()) {
  const excerpt = (state.messages || []).slice(-8).map(message => {
    const role = message.role === 'assistant' ? 'Ева' : 'Пользователь';
    const text = messageDisplayText(message) || (message.meta?.attachments?.length ? '[файлы без текста]' : '');
    return `${role}: ${String(text || '').trim()}`.trim();
  }).filter(Boolean).join('\n');
  const title = thread?.title || 'Текущий чат';
  return `Используй контекст этого чата как исходную рамку регулярной задачи.\nТема: ${title}.\nЕсли в чате были уточнения, следуй им.\n\nКонтекст диалога:\n${excerpt}`.trim();
}

function startUiAutoRefresh() {
  if (state.uiRefreshTimer) clearInterval(state.uiRefreshTimer);
  state.uiRefreshTimer = setInterval(() => {
    if (!state.token || document.hidden || state.isRefreshingThreads || state.isRefreshingJobs) return;
    guarded(async () => {
      await refreshThreads();
      if (state.screen === 'jobs') await refreshJobs();
    });
  }, 15000);
}

function attachmentStatus(file) {
  if (file?.assistant_generated) return { label: 'Подготовлено ответом', className: 'good strong' };
  if (file?.text_extracted) return { label: 'Текст извлечён', className: 'good strong' };
  if (file?.extraction_note) return { label: file.extraction_note, className: 'warn' };
  return { label: 'Сохранён', className: '' };
}

function filteredUserFiles() {
  const query = (state.fileFilterQuery || '').trim().toLowerCase();
  return (state.userFiles || []).filter(file => {
    if (state.fileFilterScope === 'current_thread' && state.activeThreadId && Number(file.thread_id) !== Number(state.activeThreadId)) return false;
    if (state.fileFilterType === 'text_ready' && !file.text_extracted) return false;
    if (state.fileFilterType === 'stored_only' && file.text_extracted) return false;
    if (!query) return true;
    const haystack = [file.original_name, file.preview_text, file.extraction_note, file.mime_type].join(' ').toLowerCase();
    return haystack.includes(query);
  });
}

function queueExistingFile(fileId) {
  const found = state.userFiles.find(item => Number(item.id) === Number(fileId));
  if (!found) return;
  if (state.pendingExistingFiles.find(item => Number(item.id) === Number(found.id))) {
    showBanner('Этот файл уже добавлен в отправку.', false);
    return;
  }
  const total = (state.pendingFiles?.length || 0) + (state.pendingExistingFiles?.length || 0);
  if (total >= 5) {
    showBanner('В одном сообщении можно использовать до 5 файлов.', true);
    return;
  }
  state.pendingExistingFiles.push(found);
  renderSelectedFiles();
  updateComposerState();
  switchScreen('chat');
  showBanner(`Файл «${found.original_name}» добавлен в отправку.`, false);
}

function renderProfileSummary() {
  if (!state.user) return;
  const checks = [
    ['Имя', state.user.name],
    ['Таймзона', state.user.timezone],
    ['Язык', state.user.language],
    ['Цели', state.user.goals],
    ['Что полезно знать', state.user.assistant_profile?.about_user],
  ];
  const filled = checks.filter(([, value]) => String(value || '').trim()).length;
  const totalFiles = (state.userFiles || []).length;
  const filesReady = (state.userFiles || []).filter(file => file.text_extracted).length;
  const currentThreadFiles = (state.userFiles || []).filter(file => Number(file.thread_id) === Number(state.activeThreadId)).length;
  if (els.profileIdentityCard) {
    els.profileIdentityCard.innerHTML = `
      <div class="section-title">Кто вы для системы</div>
      <strong>${esc(state.user.name || state.user.email || 'Профиль')}</strong>
      <div class="muted" style="margin-top:6px;">${esc(state.user.title || (state.user.role === 'admin' ? 'Администратор' : 'Пользователь'))}</div>
      <div class="muted" style="margin-top:10px;">Заполнено ${filled} из ${checks.length} ключевых блоков.</div>
      <div class="summary-grid" style="margin-top:12px;">
        <div class="summary-tile"><div class="muted">Роль</div><strong>${esc(state.user.role === 'admin' ? 'Админ' : 'Пользователь')}</strong></div>
        <div class="summary-tile"><div class="muted">Команда</div><strong>${esc(state.user.team || '—')}</strong></div>
        <div class="summary-tile"><div class="muted">Таймзона</div><strong>${esc(state.user.timezone || '—')}</strong></div>
      </div>
    `;
  }
  if (els.profileResponseCard) {
    els.profileResponseCard.innerHTML = `
      <div class="section-title">Как отвечать по умолчанию</div>
      <strong>${esc(humanStyleSummary())}</strong>
      <div class="muted" style="margin-top:8px;">${esc(state.user.assistant_profile?.about_user || 'Дополнительный контекст пока не заполнен.')}</div>
      <div class="summary-grid" style="margin-top:12px;">
        <div class="summary-tile"><div class="muted">Тон</div><strong>${esc(currentOptionText(els.profileTone) || '—')}</strong></div>
        <div class="summary-tile"><div class="muted">Глубина</div><strong>${esc(currentOptionText(els.profileDepth) || '—')}</strong></div>
        <div class="summary-tile"><div class="muted">Манера</div><strong>${esc(currentOptionText(els.profileMode) || '—')}</strong></div>
      </div>
    `;
  }
  if (els.profileFilesCard) {
    els.profileFilesCard.innerHTML = `
      <div class="section-title">Файлы и повторное использование</div>
      <strong>${totalFiles}</strong>
      <div class="muted" style="margin-top:6px;">Всего файлов в личном контуре · ${filesReady} с извлечённым текстом · ${currentThreadFiles} связано с открытым чатом.</div>
      <div class="summary-grid" style="margin-top:12px;">
        <div class="summary-tile"><div class="muted">С текстом</div><strong>${filesReady}</strong></div>
        <div class="summary-tile"><div class="muted">В текущем чате</div><strong>${currentThreadFiles}</strong></div>
        <div class="summary-tile"><div class="muted">Без текста</div><strong>${Math.max(totalFiles - filesReady, 0)}</strong></div>
      </div>
    `;
  }
}

function renderChatPolicyBanner() {
  const notice = state.bootstrap?.chat_notice;
  const warningText = String(notice?.text || '').trim();
  const warningVisible = Boolean(notice?.enabled && warningText);
  const hasMessages = state.messages.length > 0;
  const zeroState = state.screen === 'chat' && !hasMessages && !state.chatWelcomeDismissed;
  const cards = [];
  if (warningVisible && !zeroState) {
    cards.push(`<div class="chat-guide-item"><strong>Внимание</strong>${esc(warningText)}</div>`);
  }
  if (els.topbarChatGuide) {
    const visible = state.screen === 'chat' && cards.length > 0;
    els.topbarChatGuide.classList.toggle('hidden', !visible);
    if (visible) els.topbarChatGuide.innerHTML = cards.join('');
  }
  if (els.chatPolicyBanner) {
    els.chatPolicyBanner.classList.add('hidden');
    els.chatPolicyBanner.innerHTML = warningVisible ? `<strong style="display:block;margin-bottom:6px;">Внимание</strong>${esc(warningText)}` : '';
  }
}

function openAdminUserCard(mode = 'create') {
  els.adminUserCard?.classList.remove('hidden');
  if (els.adminUserFormMode) els.adminUserFormMode.value = mode;
  if (els.adminUserCardTitle) {
    els.adminUserCardTitle.textContent = mode === 'edit' ? 'Редактировать пользователя' : 'Создать пользователя';
  }
  if (els.adminUserCardSubtitle) {
    els.adminUserCardSubtitle.textContent = mode === 'edit'
      ? 'Редактирование открыто из строки таблицы. Создание вынесено в отдельный сценарий.'
      : 'Отдельная форма создания. Редактирование существующих записей открывается только из таблицы.';
  }
}

function closeAdminUserCard() {
  els.adminUserCard?.classList.add('hidden');
}

function openAdminReferenceCard() {
  els.adminReferenceCard?.classList.remove('hidden');
}

function closeAdminReferenceCard() {
  els.adminReferenceCard?.classList.add('hidden');
}

function normalizeText(value) {
  return String(value ?? '').trim();
}

function referenceDatasetMeta(datasetKey) {
  return state.admin.references?.[datasetKey] || state.bootstrap?.references?.[datasetKey] || null;
}

function referenceDatasetLabel(datasetKey) {
  return referenceDatasetMeta(datasetKey)?.label || datasetKey || 'Справочник';
}

function referenceItemVisualLabel(item) {
  return item?.label || item?.item_key || 'элемент';
}

function buildReferenceExtraPayload(datasetKey, itemKey, label, existingItem = null) {
  const preserved = existingItem && typeof existingItem === 'object'
    ? JSON.parse(formatReferencePayload(existingItem) || '{}')
    : {};
  if (datasetKey === 'assistant_tones' || datasetKey === 'assistant_answer_depths' || datasetKey === 'assistant_interaction_modes') {
    return { ...preserved, prompt_value: preserved.prompt_value || itemKey };
  }
  if (datasetKey === 'help_articles') {
    return { ...preserved, points: Array.isArray(preserved.points) ? preserved.points : [] };
  }
  if (datasetKey === 'job_templates') {
    return {
      ...preserved,
      description: typeof preserved.description === 'string' ? preserved.description : '',
      fields: Array.isArray(preserved.fields) ? preserved.fields : [],
    };
  }
  if (datasetKey === 'starter_prompts') {
    return { ...preserved, prompt_value: preserved.prompt_value || label };
  }
  return preserved;
}

function openAdminReferenceItemCard(datasetKey, item = null) {
  const datasetLabel = referenceDatasetLabel(datasetKey);
  const visualLabel = referenceItemVisualLabel(item);
  if (els.adminReferenceItemDatasetKey) els.adminReferenceItemDatasetKey.value = datasetKey || '';
  if (els.adminReferenceItemMode) els.adminReferenceItemMode.value = item ? 'edit' : 'create';
  if (els.adminReferenceItemCardTitle) els.adminReferenceItemCardTitle.textContent = item ? 'Редактирование элемента справочника' : 'Новый элемент справочника';
  if (els.adminReferenceItemCardSubtitle) els.adminReferenceItemCardSubtitle.textContent = item ? `${datasetLabel} · изменение «${visualLabel}»` : `${datasetLabel} · создание новой записи`;
  if (els.adminReferenceItemKeyInput) { els.adminReferenceItemKeyInput.value = item?.item_key || ''; els.adminReferenceItemKeyInput.disabled = !!item; }
  if (els.adminReferenceItemLabelInput) els.adminReferenceItemLabelInput.value = item?.label || '';
  if (els.adminReferenceItemSortOrderInput) els.adminReferenceItemSortOrderInput.value = String(item?.sort_order ?? 0);
  if (els.adminReferenceItemStatusSelect) els.adminReferenceItemStatusSelect.value = item?.status || (item?.deleted_at ? 'deleted' : (item?.is_active === false ? 'inactive' : 'active'));
  if (els.adminReferenceItemPayloadInput) els.adminReferenceItemPayloadInput.value = item ? formatReferencePayload(item) : '{}';
  if (els.adminReferenceItemStatus) els.adminReferenceItemStatus.textContent = item ? `Редактируется элемент: ${visualLabel}` : `Служебные поля заполняются автоматически для справочника «${datasetLabel}».`;
  els.adminReferenceItemCard?.classList.remove('hidden');
}

function closeAdminReferenceItemCard() {
  els.adminReferenceItemCard?.classList.add('hidden');
}


function messageDisplayText(message) {
  const raw = typeof message.content === 'string' ? message.content : '';
  if (message.role === 'user' && (message.meta?.attachments || []).length) {
    if (message.meta?.user_text !== undefined) return message.meta.user_text || '';
    return raw.replace(/\n\nВ сообщении приложены файлы:[\s\S]*$/, '').trim();
  }
  if (message.role === 'assistant') {
    return raw.replace(/^MEDIA:[^\n]+$/gm, '').replace(/\n{3,}/g, '\n\n').trim();
  }
  return raw;
}

function updateComposerState() {
  if (!els.composerStatus || !els.sendBtn) return;
  const uploadCount = state.pendingFiles.length;
  const existingCount = state.pendingExistingFiles.length;
  const total = uploadCount + existingCount;
  if (state.isSending) {
    els.composerStatus.textContent = 'Отправляю сообщение и обновляю контекст…';
  } else if (total) {
    const parts = [];
    if (uploadCount) parts.push(`новых файлов: ${uploadCount}`);
    if (existingCount) parts.push(`из «Мои файлы»: ${existingCount}`);
    els.composerStatus.textContent = `К отправке подготовлено ${total} · ${parts.join(' · ')}`;
  } else {
    els.composerStatus.textContent = 'Можно отправить текст, новые файлы или повторно использовать файл из профиля.';
  }
  els.sendBtn.disabled = state.isSending || (!els.promptInput.value.trim() && !total);
}

function setAdminSection(section) {
  state.adminSection = section;
  els.adminSectionTabs.forEach(button => {
    button.classList.toggle('primary', button.dataset.adminSection === section);
    button.classList.toggle('ghost', button.dataset.adminSection !== section);
  });
  els.adminPanels.forEach(panel => {
    panel.classList.toggle('admin-panel-hidden', panel.dataset.adminPanel !== section);
  });
}

function setProfileSection(section) {
  state.profileSection = section;
  const panels = {
    summary: els.profileSectionSummary,
    identity: els.profileSectionIdentity,
    response: els.profileSectionResponse,
    files: els.profileSectionFiles,
  };
  els.profileTabs.forEach(button => {
    const active = button.dataset.profileSection === section;
    button.classList.toggle('active', active);
  });
  Object.entries(panels).forEach(([key, panel]) => {
    panel?.classList.toggle('hidden', key !== section);
  });
  if (section === 'files') renderProfileFiles();
}

function syncThreadActions() {
  const thread = getActiveThread();
  const welcomeVisible = !state.messages.length && !state.chatWelcomeDismissed;
  if (els.chatThreadHeader) {
    els.chatThreadHeader.classList.toggle('hidden', welcomeVisible);
  }
  if (els.chatThreadTitle) {
    els.chatThreadTitle.textContent = compactThreadTitle(thread);
  }
  if (!els.archiveThreadBtn || !els.renameThreadBtn) return;
  const disabled = !thread;
  els.archiveThreadBtn.disabled = disabled;
  els.renameThreadBtn.disabled = disabled;
  els.archiveThreadBtn.textContent = thread?.archived ? 'Вернуть из архива' : 'В архив';
}

function setLoginError(text) {
  els.loginError.textContent = text;
  els.loginError.classList.toggle('hidden', !text);
}

function formatTs(value) {
  if (!value) return '—';
  return new Date(value).toLocaleString('ru-RU');
}

function toDatetimeLocalValue(value) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  const pad = num => String(num).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function datetimeLocalToIso(value, { endOfMinute = false } = {}) {
  const raw = String(value || '').trim();
  if (!raw) return '';
  const normalized = endOfMinute && raw.length === 16 ? `${raw}:59` : raw;
  const date = new Date(normalized);
  return Number.isNaN(date.getTime()) ? '' : date.toISOString();
}

function adminEventsQueryParams(options = {}) {
  const filter = state.admin.eventsFilter || { dateFrom: '', dateTo: '', limit: 100 };
  const params = new URLSearchParams();
  const dateFrom = options.dateFrom ?? filter.dateFrom;
  const dateTo = options.dateTo ?? filter.dateTo;
  const limit = Number(options.limit ?? filter.limit ?? 100);
  if (dateFrom) params.set('date_from', dateFrom);
  if (dateTo) params.set('date_to', dateTo);
  params.set('limit', String(Number.isFinite(limit) && limit > 0 ? limit : 100));
  if (options.exportFormat) params.set('export', options.exportFormat);
  return params;
}

async function apiDownload(path, filename) {
  const headers = {};
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  const response = await fetch(`${API_BASE}${path}`, { headers });
  if (!response.ok) {
    let message = `HTTP ${response.status}`;
    const text = await response.text();
    if (text) {
      try {
        const data = JSON.parse(text);
        message = humanizeApiError(data.error, message);
      } catch (_) {
        message = text.slice(0, 120).replace(/\s+/g, ' ').trim() || message;
      }
    }
    throw new Error(message);
  }
  const blob = await response.blob();
  const href = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = href;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(href), 1000);
}

function formatNumber(value) {
  const num = Number(value);
  return Number.isFinite(num) ? num.toLocaleString('ru-RU') : '—';
}

function formatChartGranularity(value) {
  if (value === 'week') return 'по неделям';
  if (value === 'month') return 'по месяцам';
  return 'по дням';
}

function buildOverviewChartSvg(points) {
  const width = 520;
  const height = 180;
  const padding = { top: 12, right: 10, bottom: 24, left: 10 };
  const innerWidth = width - padding.left - padding.right;
  const innerHeight = height - padding.top - padding.bottom;
  const maxValue = Math.max(...points.map(point => Number(point.value || 0)), 1);
  const safeDenominator = Math.max(points.length - 1, 1);
  const coords = points.map((point, index) => {
    const x = padding.left + (innerWidth * index) / safeDenominator;
    const y = padding.top + innerHeight - ((Number(point.value || 0) / maxValue) * innerHeight);
    return [Number(x.toFixed(2)), Number(y.toFixed(2))];
  });
  const polyline = coords.map(([x, y]) => `${x},${y}`).join(' ');
  const area = `${padding.left},${height - padding.bottom} ${polyline} ${padding.left + innerWidth},${height - padding.bottom}`;
  const yTicks = [0, Math.round(maxValue / 2), maxValue].filter((value, index, arr) => arr.indexOf(value) === index);
  return `
    <svg class="admin-chart-svg" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" aria-hidden="true">
      ${yTicks.map(value => {
        const y = padding.top + innerHeight - ((value / maxValue) * innerHeight);
        return `<line class="admin-chart-axis" x1="${padding.left}" y1="${y}" x2="${padding.left + innerWidth}" y2="${y}"></line>`;
      }).join('')}
      <polygon class="admin-chart-area" points="${area}"></polygon>
      <polyline class="admin-chart-line" points="${polyline}"></polyline>
      ${coords.map(([x, y]) => `<circle class="admin-chart-point" cx="${x}" cy="${y}" r="3.5"></circle>`).join('')}
    </svg>`;
}

function renderOverviewChartCard(title, metricKey, note, buckets, granularity) {
  const points = (buckets || []).map(item => ({ label: item.bucket_label, value: Number(item[metricKey] || 0) }));
  const total = points.reduce((sum, point) => sum + point.value, 0);
  const peak = points.reduce((max, point) => Math.max(max, point.value), 0);
  const labels = points.length ? [points[0].label, points[Math.floor(points.length / 2)].label, points[points.length - 1].label] : ['—', '—', '—'];
  return `
    <div class="admin-chart">
      <div class="admin-chart-head">
        <div>
          <div class="muted">${esc(title)}</div>
          <strong>${formatNumber(total)}</strong>
          <div class="muted">${esc(note)}</div>
        </div>
        <div class="admin-chart-meta">
          <div class="muted">Пик</div>
          <strong>${formatNumber(peak)}</strong>
          <div class="muted">${esc(formatChartGranularity(granularity))}</div>
        </div>
      </div>
      ${buildOverviewChartSvg(points)}
      <div class="admin-chart-labels"><span>${esc(labels[0])}</span><span>${esc(labels[1])}</span><span>${esc(labels[2])}</span></div>
    </div>`;
}

function formatBytes(value) {
  const size = Number(value || 0);
  if (size < 1024) return `${size} Б`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} КБ`;
  return `${(size / (1024 * 1024)).toFixed(1)} МБ`;
}

function esc(value) {
  return String(value || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
    .replace(/\n/g, '<br>');
}

function getActiveThread() {
  return state.threads.find(thread => thread.id === state.activeThreadId) || null;
}

function getActiveJob() {
  return state.jobs.find(job => job.id === state.activeJobId) || null;
}

function humanStyleSummary(user = state.user) {
  if (!user?.style_summary) return 'не настроен';
  const s = user.style_summary;
  return `${s.tone} · ${s.answer_depth} · ${s.interaction_mode}`;
}

function profilePreviewText({ toneText, depthText, modeText, aboutText }) {
  const parts = [
    `Тон: ${toneText || 'не задан'}.`,
    `Глубина: ${depthText || 'не задана'}.`,
    `Манера: ${modeText || 'не задана'}.`,
  ];
  if (aboutText) parts.push(`Дополнительно учесть: ${aboutText}.`);
  return parts.join(' ');
}

function adminStylePreviewText() {
  return profilePreviewText({
    toneText: currentOptionText(els.adminUserTone),
    depthText: currentOptionText(els.adminUserDepth),
    modeText: currentOptionText(els.adminUserMode),
    aboutText: els.adminUserAbout.value.trim(),
  });
}

function referenceDatasetItems(datasetKey) {
  return state.bootstrap?.references?.[datasetKey]?.items || [];
}

function referenceOptions(datasetKey, currentValue = '') {
  const active = referenceDatasetItems(datasetKey).filter(item => item.is_active !== false && !item.deleted_at && item.status !== 'deleted');
  if (!currentValue) return active;
  if (active.some(item => optionValue(item) === currentValue)) return active;
  const fallback = referenceDatasetItems(datasetKey).find(item => optionValue(item) === currentValue);
  if (!fallback) return active;
  const suffix = fallback.status === 'deleted' || fallback.deleted_at ? 'удалено' : 'не активно';
  return [...active, { ...fallback, _inactive_preserved: true, _status_suffix: suffix }];
}

function optionLabel(option, fallbackValue = '') {
  const base = option?.label || option?.prompt_value || option?.item_key || fallbackValue || '—';
  return option?._inactive_preserved ? `${base} · ${option._status_suffix || 'не активно'}` : base;
}

function optionValue(option, fallbackValue = '') {
  return option?.item_key || fallbackValue || '';
}

function syncSelectOptions(selectEl, datasetKey, preferredValue = '', placeholder = '—') {
  if (!selectEl) return preferredValue || '';
  const options = referenceOptions(datasetKey, preferredValue);
  const values = options.map(item => optionValue(item));
  const fallbackValue = preferredValue && values.includes(preferredValue)
    ? preferredValue
    : (values[0] || '');
  selectEl.innerHTML = options.length
    ? options.map(item => `<option value="${esc(optionValue(item))}" ${item._inactive_preserved ? 'data-inactive-preserved="1"' : ''}>${esc(optionLabel(item))}</option>`).join('')
    : `<option value="">${esc(placeholder)}</option>`;
  if (fallbackValue) selectEl.value = fallbackValue;
  return fallbackValue;
}

function currentOptionText(selectEl) {
  if (!selectEl || selectEl.selectedIndex < 0) return '';
  return (selectEl.options[selectEl.selectedIndex]?.text || '').trim();
}

function ensureReferenceDrivenProfileControls() {
  const profile = state.user?.assistant_profile || {};
  syncSelectOptions(els.profileTone, 'assistant_tones', profile.tone, 'Нет активных значений');
  syncSelectOptions(els.profileDepth, 'assistant_answer_depths', profile.answer_depth, 'Нет активных значений');
  syncSelectOptions(els.profileMode, 'assistant_interaction_modes', profile.interaction_mode, 'Нет активных значений');
}

function ensureAdminUserReferenceControls(user = null) {
  const profile = user?.assistant_profile || {};
  syncSelectOptions(els.adminUserTone, 'assistant_tones', profile.tone || 'business', 'Нет активных значений');
  syncSelectOptions(els.adminUserDepth, 'assistant_answer_depths', profile.answer_depth || 'balanced', 'Нет активных значений');
  syncSelectOptions(els.adminUserMode, 'assistant_interaction_modes', profile.interaction_mode || 'compare_options', 'Нет активных значений');
}

function humanizeVisibility(value) {
  return ({ private: 'приватно', shared: 'по доступу', workspace: 'для рабочей области' })[value] || value || '—';
}

function humanizeStatus(value) {
  return ({ active: 'активна', paused: 'на паузе', success: 'успешно', ok: 'успешно', error: 'с ошибкой', running: 'выполняется' })[value] || value || '—';
}

function humanizeJobRole(value) {
  return ({ owner: 'владелец', admin: 'админ', editor: 'редактор', viewer: 'читатель', subscriber: 'подписчик' })[value] || value || '—';
}

function humanizeJobType(value) {
  return ({ daily_brief: 'ежедневный бриф', decision_review: 'разбор решения', research_watch: 'мониторинг темы', custom: 'своя задача' })[value] || value || '—';
}

function humanizeEventType(value) {
  if (!value) return '—';
  if (value === 'user') return 'сообщение пользователя';
  if (value === 'assistant') return 'ответ ассистента';
  if (value === 'job:success') return 'задача выполнена';
  if (value === 'job:error') return 'ошибка задачи';
  return value;
}

function renderSidebarProfile() {
  if (!state.user) return;
  if (els.sidebarUserLabel) els.sidebarUserLabel.textContent = state.user.name || 'Пользователь';
  if (els.sidebarUserRole) els.sidebarUserRole.textContent = state.user.title || (state.user.role === 'admin' ? 'Администратор' : 'Пользователь');
  const jobsNav = els.navButtons.find(button => button.dataset.screen === 'jobs');
  if (jobsNav) jobsNav.style.display = '';
  if (els.adminNavBtn) els.adminNavBtn.style.display = state.user.role === 'admin' ? '' : 'none';
  els.newJobBtn.style.display = '';
}

function firstMeaningfulLine(text) {
  return String(text || '')
    .split(/\r?\n/)
    .map(item => item.trim())
    .find(Boolean) || '';
}

function compactThreadTitle(thread) {
  const explicitTitle = String(thread?.title || '').trim();
  return (explicitTitle || 'Новый чат').slice(0, 140);
}

function updateArchiveToggleLabel() {
  if (els.allThreadsBtn) {
    els.allThreadsBtn.innerHTML = '<strong>Все чаты</strong><div class="muted" style="margin-top:4px;">Полный список в отдельном окне</div>';
  }
}

function renderThreadsModal() {
  if (!els.threadsModalList) return;
  const sorted = [...(state.threads || [])].sort((a, b) => String(b.updated_at || '').localeCompare(String(a.updated_at || '')));
  els.threadsModalList.innerHTML = sorted.length ? `
    <table class="data-table">
      <thead>
        <tr><th>Чат</th><th>Статус</th><th>Обновлён</th><th>Фрагмент</th><th></th></tr>
      </thead>
      <tbody>
        ${sorted.map(thread => `
          <tr class="${thread.id === state.activeThreadId ? 'active' : ''}">
            <td><strong>${esc(compactThreadTitle(thread))}</strong>${threadUnread(thread) ? ' <span class="thread-unread-dot" title="Есть непрочитанное"></span>' : ''}</td>
            <td>${thread.archived ? 'архив' : 'активный'}</td>
            <td>${formatTs(thread.updated_at || thread.last_message_at || thread.created_at)}</td>
            <td>${esc(firstMeaningfulLine(thread?.preview || '') || '—')}</td>
            <td><button type="button" class="btn ghost small" data-modal-thread-id="${thread.id}">Открыть</button></td>
          </tr>
        `).join('')}
      </tbody>
    </table>
  ` : '<div class="muted">Чатов пока нет.</div>';
  els.threadsModalList.querySelectorAll('[data-modal-thread-id]').forEach(button => {
    button.addEventListener('click', () => guarded(async () => {
      closeThreadsModal();
      await loadThread(Number(button.dataset.modalThreadId));
    }));
  });
}

function openThreadsModal() {
  renderThreadsModal();
  els.threadsModalBackdrop?.classList.remove('hidden');
}

function closeThreadsModal() {
  els.threadsModalBackdrop?.classList.add('hidden');
}

function renderThreads() {
  syncThreadActions();
  els.threadList.innerHTML = '';
  updateArchiveToggleLabel();
  const visibleThreads = (state.threads || [])
    .filter(thread => !thread.archived)
    .sort((a, b) => String(b.updated_at || '').localeCompare(String(a.updated_at || '')))
    .slice(0, 10);
  if (!visibleThreads.length) {
    const empty = document.createElement('div');
    empty.className = 'thread-item empty-state';
    empty.innerHTML = '<h4>Пока нет чатов</h4><p>Чатов пока нет. Создайте новый.</p>';
    els.threadList.appendChild(empty);
    return;
  }
  visibleThreads.forEach(thread => {
    const item = document.createElement('button');
    item.type = 'button';
    item.className = `thread-item ${thread.id === state.activeThreadId ? 'active' : ''}`;
    const title = compactThreadTitle(thread);
    const unread = threadUnread(thread);
    const preview = firstMeaningfulLine(thread?.preview || '');
    item.innerHTML = `
      <div class="thread-item-head">
        <h4>${esc(title)}</h4>
        ${unread ? '<span class="thread-unread-dot" title="Есть непрочитанное"></span>' : ''}
      </div>
      <small>${formatTs(thread.updated_at || thread.last_message_at || thread.created_at)} · сообщений: ${thread.message_count || 0}</small>
      ${preview ? `<div class="thread-preview">${esc(preview)}</div>` : ''}
    `;
    item.addEventListener('click', () => guarded(() => loadThread(thread.id)));
    els.threadList.appendChild(item);
  });
}

function renderChatWelcome() {
  const hasMessages = state.messages.length > 0;
  const titleEl = document.querySelector('.composer-title');
  const leadEl = document.querySelector('.composer-lead');
  if (titleEl) {
    titleEl.textContent = hasMessages || state.chatWelcomeDismissed
      ? 'Начните новый запрос или продолжайте диалог'
      : 'Опишите задачу или добавьте материалы';
  }
  if (leadEl) {
    leadEl.textContent = hasMessages || state.chatWelcomeDismissed
      ? 'Коротко опишите задачу, добавьте контекст или приложите материалы. Всё попадёт в текущий рабочий поток чата.'
      : 'Короткого описания, нескольких вводных или файлов достаточно, чтобы начать рабочий диалог.';
  }
  if (els.promptInput) {
    els.promptInput.placeholder = hasMessages || state.chatWelcomeDismissed
      ? 'Например: разберём проблему по шагам, сравним варианты решения или подготовим сообщение для коллеги.'
      : 'Например: разберём проблему по шагам, сравним варианты решения или подготовим сообщение для коллеги.';
  }
  if (els.chatThreadHeader) {
    els.chatThreadHeader.classList.toggle('hidden', !hasMessages && !state.chatWelcomeDismissed);
  }
  els.chatWelcome.classList.add('hidden');
  els.chatWelcome.innerHTML = '';
}

function renderMessages(scrollMode = 'preserve') {
  renderChatWelcome();
  syncThreadActions();
  els.chatMessages.innerHTML = '';
  state.lastAssistantMessageId = null;
  if (!state.messages.length) {
    if (!state.chatWelcomeDismissed) {
      els.chatMessages.innerHTML = '';
      if (scrollMode === 'top') scrollChatToTop();
      return;
    }
    const empty = document.createElement('div');
    empty.className = 'chat-empty-message';
    empty.innerHTML = '<h3>Диалог появится здесь</h3><div class="muted">Начни с вопроса, короткого описания ситуации или приложи файлы в нижнем блоке. После первого сообщения этот экран превратится в обычную рабочую переписку.</div>';
    els.chatMessages.appendChild(empty);
    if (scrollMode === 'top') scrollChatToTop();
    return;
  }
  state.messages.forEach(message => {
    const box = document.createElement('div');
    box.className = `message ${message.role === 'user' ? 'user' : 'assistant'}`;
    const actionHtml = message.role === 'assistant' && !message.typing
      ? `<div class="message-actions">
          <button type="button" class="btn ghost small" data-copy="${message.id}">Копировать</button>
          <button type="button" class="btn ghost small" data-feedback="good:${message.id}">Полезно</button>
          <button type="button" class="btn ghost small" data-feedback="bad:${message.id}">Нужна доработка</button>
        </div>`
      : '';
    const attachments = message.meta?.attachments || [];
    const attachmentsHtml = attachments.length
      ? `<div class="attachment-list">${attachments.map(file => {
          const status = attachmentStatus(file);
          return `
          <div class="attachment-card">
            <div class="attachment-head">
              <div>
                <strong>${esc(file.original_name)}</strong>
                <div class="muted">${esc(file.mime_type || 'файл')} · ${esc(formatBytes(file.size_bytes || 0))}</div>
              </div>
              <span class="status-badge ${status.className}">${esc(status.label)}</span>
            </div>
            ${file.preview_excerpt ? `<div style="margin-top:8px;">${esc(file.preview_excerpt)}</div>` : ''}
            ${file.reused ? '<div class="muted" style="margin-top:6px;">Файл использован повторно из личного списка.</div>' : ''}
            ${file.download_url ? `<div style="margin-top:8px;"><a href="${esc(file.download_url)}" target="_blank" rel="noopener">Скачать файл</a></div>` : ''}
          </div>`;
        }).join('')}</div>`
      : '';
    const displayText = messageDisplayText(message);
    const bodyHtml = message.typing
      ? '<div class="typing"><span></span><span></span><span></span></div>'
      : `${displayText ? `<div>${esc(displayText)}</div>` : ''}${attachmentsHtml}`;
    box.innerHTML = `
      <div>${bodyHtml || '<div class="muted">Сообщение без текста.</div>'}</div>
      <div class="message-footer">
        <span>${formatTs(message.created_at)}</span>
        ${actionHtml}
      </div>
    `;
    els.chatMessages.appendChild(box);
    if (message.role === 'assistant' && message.id) state.lastAssistantMessageId = message.id;
  });
  els.chatMessages.querySelectorAll('[data-copy]').forEach(button => {
    button.addEventListener('click', async () => {
      const messageId = Number(button.dataset.copy);
      const message = state.messages.find(item => item.id === messageId);
      if (!message) return;
      await navigator.clipboard.writeText(message.content || '');
      showBanner('Текст скопирован.', false);
    });
  });
  els.chatMessages.querySelectorAll('[data-feedback]').forEach(button => {
    button.addEventListener('click', () => {
      const [type, id] = button.dataset.feedback.split(':');
      guarded(() => sendQuickFeedback(Number(id), type === 'good'));
    });
  });
  if (scrollMode === 'bottom') scrollChatToBottom();
  if (scrollMode === 'top') scrollChatToTop();
  updateChatScrollUi();
  pinChatIntroWithinScreen();
}

function renderSelectedFiles() {
  const uploads = state.pendingFiles || [];
  const existing = state.pendingExistingFiles || [];
  const total = uploads.length + existing.length;
  els.selectedFiles.classList.toggle('hidden', !total);
  els.selectedFiles.innerHTML = [
    ...uploads.map((file, index) => `
      <div class="file-pill">
        <span>${esc(file.name)} · ${esc(formatBytes(file.size || 0))}</span>
        <button type="button" data-remove-upload="${index}">✕</button>
      </div>
    `),
    ...existing.map((file, index) => `
      <div class="file-pill">
        <span>${esc(file.original_name)} · из «Мои файлы»</span>
        <button type="button" data-remove-existing="${index}">✕</button>
      </div>
    `),
  ].join('');
  els.selectedFiles.querySelectorAll('[data-remove-upload]').forEach(button => {
    button.addEventListener('click', () => {
      state.pendingFiles.splice(Number(button.dataset.removeUpload), 1);
      renderSelectedFiles();
      updateComposerState();
    });
  });
  els.selectedFiles.querySelectorAll('[data-remove-existing]').forEach(button => {
    button.addEventListener('click', () => {
      state.pendingExistingFiles.splice(Number(button.dataset.removeExisting), 1);
      renderSelectedFiles();
      updateComposerState();
    });
  });
}

function renderProfileFiles() {
  if (!els.profileFiles) return;
  renderProfileSummary();
  const files = filteredUserFiles();
  const total = (state.userFiles || []).length;
  if (els.profileFilesMeta) {
    els.profileFilesMeta.textContent = files.length === total
      ? `Показаны все файлы: ${total}. Можно быстро отфильтровать только текущий чат или только файлы с извлечённым текстом.`
      : `По текущим фильтрам показано ${files.length} из ${total} файлов.`;
  }
  if (!files.length) {
    els.profileFiles.innerHTML = '<div class="muted">По текущим фильтрам файлов не найдено.</div>';
    return;
  }
  els.profileFiles.innerHTML = `
    <table class="data-table">
      <thead>
        <tr><th>Файл</th><th>Статус</th><th>Источник</th><th>Добавлен</th><th></th></tr>
      </thead>
      <tbody>
        ${files.map(file => {
          const status = attachmentStatus(file);
          return `
            <tr>
              <td>
                <strong>${esc(file.original_name)}</strong>
                <div class="muted">${esc(file.mime_type || 'файл')} · ${esc(formatBytes(file.size_bytes || 0))}</div>
                ${file.preview_text ? `<details class="details-block" style="margin-top:8px;"><summary>Фрагмент</summary><div class="payload-preview">${esc(file.preview_text.slice(0, 1200))}</div></details>` : ''}
              </td>
              <td><span class="status-badge ${status.className}">${esc(status.label)}</span></td>
              <td>${file.thread_id ? `Чат #${esc(String(file.thread_id))}` : 'Личный контур'}</td>
              <td>${formatTs(file.created_at)}</td>
              <td><button class="btn ghost small" type="button" data-file-reuse="${file.id}">Использовать</button></td>
            </tr>
          `;
        }).join('')}
      </tbody>
    </table>
  `;
}

function fillProfileForm() {
  if (!state.user) return;
  ensureReferenceDrivenProfileControls();
  els.profileName.value = state.user.name || '';
  els.profileTimezone.value = state.user.timezone || '';
  els.profileLanguage.value = state.user.language || '';
  els.profileTeam.value = state.user.team || '';
  els.profileTitle.value = state.user.title || '';
  els.profileGoals.value = state.user.goals || '';
  els.profileConstraints.value = state.user.constraints || '';
  els.profilePinned.value = (state.user.pinned || []).join('\n');
  els.profileTone.value = state.user.assistant_profile?.tone || els.profileTone.value || 'business';
  els.profileDepth.value = state.user.assistant_profile?.answer_depth || els.profileDepth.value || 'balanced';
  els.profileMode.value = state.user.assistant_profile?.interaction_mode || els.profileMode.value || 'compare_options';
  els.profileAbout.value = state.user.assistant_profile?.about_user || '';
  updateProfilePreview();
}

function updateProfilePreview() {
  els.profileStylePreview.textContent = profilePreviewText({
    toneText: currentOptionText(els.profileTone),
    depthText: currentOptionText(els.profileDepth),
    modeText: currentOptionText(els.profileMode),
    aboutText: els.profileAbout.value.trim(),
  });
}

function renderHelp() {
  const sectionCards = [
    {
      tag: 'Чаты',
      title: 'Рабочий диалог',
      points: [
        'Новый чат лучше открывать под новую тему, чтобы не смешивать контексты.',
        'Если важны документы, добавляй их сразу в чат или используй повторно из профиля.',
        'Enter отправляет сообщение, Shift+Enter оставляет перенос строки.',
      ],
    },
    {
      tag: 'Задачи',
      title: 'Регулярные задачи',
      points: [
        'Экран задач показывает реальное состояние Hermes cron: статус, расписание, доступ и историю запусков.',
        'Название задачи в списке можно настроить для удобства, не меняя тех. название cron-задачи.',
        'Если нужно полное редактирование cron-задачи, используй основной контур Hermes cron.',
      ],
    },
    {
      tag: 'Профиль',
      title: 'Личные настройки',
      points: [
        'Профиль — одно место для контекста о тебе, манеры ответа и списка личных файлов.',
        'Лучше держать здесь устойчивые вещи: цели, ограничения, рабочую роль, ключевые акценты.',
        'Файлы из личного списка можно быстро подключать к новым сообщениям без повторной загрузки.',
      ],
    },
    {
      tag: 'Управление',
      title: 'Админка и справочники',
      points: [
        'Обзор нужен для состояния системы, пользователи — для ручного управления доступом и профилями.',
        'Справочники меняют варианты интерфейса и подсказок сразу после сохранения.',
        'Шумные детали вроде JSON-полей и истории изменений раскрываются только по необходимости.',
      ],
    },
  ];
  const referenceCards = (state.bootstrap?.help || []).map(article => ({
    tag: 'Подсказка',
    title: article.title,
    points: article.points || [],
  }));
  const cards = [...sectionCards, ...referenceCards];
  els.helpGrid.innerHTML = cards.map(card => `
    <div class="card">
      <div class="help-card-head">
        <div>
          <strong>${esc(card.title)}</strong>
          <div class="muted">${esc(card.tag)}</div>
        </div>
      </div>
      <ul class="mini-list">${(card.points || []).map(point => `<li>${esc(point)}</li>`).join('')}</ul>
    </div>
  `).join('');
}

function renderJobsList() {
  const jobs = filterVisibleJobs(state.jobs);
  els.jobsList.innerHTML = '';
  if (els.jobsMetaNote) {
    const parts = [`Показано задач: ${jobs.length}`];
    const hasLocal = jobs.some(job => job.source_of_truth === 'local_jobs' || !job.source_of_truth);
    const hasHermes = jobs.some(job => job.source_of_truth === 'hermes_cron');
    if (hasLocal && hasHermes) parts.push('источники: Web MVP + Hermes cron');
    else if (hasHermes) parts.push('источник: Hermes cron');
    else if (hasLocal) parts.push('источник: Web MVP');
    if (state.jobSearchQuery.trim()) parts.push(`поиск: «${state.jobSearchQuery.trim()}»`);
    els.jobsMetaNote.textContent = parts.join(' · ');
  }
  if (!jobs.length) {
    els.jobsList.innerHTML = `<div class="empty-state"><h3 style="margin:0 0 8px;">Ничего не найдено</h3><div class="muted">Смени фильтр или очисти поисковый запрос.</div></div>`;
    renderJobDetail();
    return;
  }
  jobs.forEach(job => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `job-item ${job.id === state.activeJobId ? 'active' : ''}`;
    const visualName = jobVisualName(job);
    const outcomeClass = String(job.last_run_status || '').toLowerCase() === 'error' ? 'bad' : (String(job.last_run_status || '').toLowerCase() === 'ok' ? 'good' : 'neutral');
    button.innerHTML = `
      <div class="job-item-top">
        <div class="job-item-title-wrap">
          <strong>${esc(visualName)}</strong>
          <div class="muted job-item-subtitle">${esc(job.name)}</div>
        </div>
        <span class="job-chip-soft">${esc(humanizeStatus(job.status))}</span>
      </div>
      <div class="job-item-meta-line">
        <span class="job-inline-chip ${outcomeClass}">${esc(jobLastOutcomeLabel(job))}</span>
        <span class="job-item-next-run">Следующий: ${esc(formatTsCompact(job.next_run_at))}</span>
      </div>
    `;
    button.addEventListener('click', () => guarded(() => loadJob(job.id)));
    els.jobsList.appendChild(button);
  });
}

function renderJobDetail() {
  const job = getActiveJob();
  if (!job) {
    els.jobDetail.innerHTML = '<div class="empty-state job-empty-detail"><div><h3 style="margin:0 0 8px;">Выбери задачу</h3><div class="muted">Справа появятся описание, расписание, доступ и история запусков.</div></div></div>';
    return;
  }
  const role = job.role || 'viewer';
  const canRun = role === 'owner' || role === 'admin';
  const canPauseResume = role === 'owner' || role === 'admin';
  const canEdit = (role === 'owner' || role === 'admin') && (!job.read_only || isHermesCronJob(job));
  const canSubscribe = !job.read_only && (Boolean(job.can_self_subscribe) || Boolean(job.is_subscribed));
  const showParams = state.user?.role === 'admin';
  const visualName = jobVisualName(job);
  const sharedName = String(job.display_name || '').trim();
  const nameDisplay = sharedName || 'Пока не задано общее название.';
  const nameHint = sharedName
    ? 'Это общее название видно всем, у кого есть доступ к задаче.'
    : 'Общее название помогает отличать задачу в списке и видно всем, у кого есть доступ.';
  const nameEditVisible = canEdit && state.jobNameEditMode;
  const sourceLabel = job.source_of_truth === 'hermes_cron' ? 'Hermes cron' : 'Web MVP';
  const techNameHtml = `<div class="muted">Тех. название: ${esc(job.name)}</div>`;
  const sourceNameHtml = `<div class="muted">Источник: ${esc(sourceLabel)}</div>`;
  const visibilityNote = job.visibility === 'private'
    ? 'Видна только создателю и администратору.'
    : job.visibility === 'workspace'
      ? 'Видна всей рабочей области.'
      : 'Видна по явно выданному доступу.';
  const recipientRows = (job.recipients || []).length
    ? job.recipients.map(item => {
      const isLocalDelivery = item.recipient_type === 'delivery_target' && item.target_value === 'local';
      const recipientLabel = isLocalDelivery ? 'Без отправки в чат' : (item.label || item.target_value);
      const recipientNote = item.recipient_type === 'fixed_thread'
        ? 'для выбранного чата'
        : item.recipient_type === 'owner'
          ? 'для владельца задачи'
          : item.recipient_type === 'delivery_target'
            ? (isLocalDelivery ? 'Результат сохраняется во внутренней истории задачи и не отправляется в чат.' : (item.note || humanizeCronDeliverTarget(item.target_value)))
            : item.recipient_type;
      return `<div class="list-row"><strong>${esc(recipientLabel)}</strong><div class="muted">${esc(recipientNote)}</div></div>`;
    }).join('')
    : '<div class="list-row"><strong>Без отправки в чат</strong><div class="muted">Результат сохраняется во внутренней истории задачи и не отправляется в чат.</div></div>';
  const runRows = (job.runs || []).length
    ? job.runs.map(run => `<div class="list-row"><strong>${esc(humanizeStatus(run.status))}</strong><div class="muted">${formatTs(run.started_at)} · ${esc(run.trigger_type)}${run.summary ? ` · ${esc(run.summary)}` : ''}${run.error_text ? ` · ${esc(run.error_text)}` : ''}</div></div>`).join('')
    : '<div class="muted">История запусков пуста.</div>';
  const paramsFull = Object.entries(job.parameters || {}).map(([key, value]) => `<div class="list-row tight"><strong>${esc(key)}</strong><div class="muted">${esc(String(value))}</div></div>`).join('') || '<div class="muted">Параметры не заданы.</div>';
  els.jobDetail.innerHTML = `
    <div class="job-detail-stack">
      <div class="job-toolbar">
        <div class="job-identity-meta">
          <h3 style="margin:0;">${esc(visualName)}</h3>
          ${techNameHtml}
          ${sourceNameHtml}
        </div>
        <div class="inline-actions">
          ${canPauseResume ? `<button type="button" class="btn primary small" id="jobPauseResumeBtn">${job.status === 'paused' ? 'Возобновить задачу' : 'Поставить на паузу'}</button>` : ''}
          ${canRun ? '<button type="button" class="btn ghost small" id="jobRunBtn">Запустить сейчас</button>' : ''}
          ${canEdit ? `<button type="button" class="btn ghost small" id="jobEditBtn">Настроить задачу</button>` : ''}
          ${canSubscribe ? `<button type="button" class="btn ghost small" id="jobSubscribeBtn">${job.is_subscribed ? 'Отключить рассылку' : 'Подключить рассылку'}</button>` : ''}
        </div>
      </div>
      <div class="job-header-grid">
        <div class="job-hero">
          <div class="job-hero-block">
            <div class="section-title">Общее название</div>
            <div class="job-display-name ${sharedName ? '' : 'is-empty'}">${esc(nameDisplay)}</div>
            <div class="job-display-hint muted">${esc(nameHint)}</div>
            ${nameEditVisible ? `<div class="job-alias-row"><label class="field"><span>Общее название</span><input id="jobAliasInput" value="${esc(sharedName)}" placeholder="Например: Утренний мониторинг CTO" /></label><button type="button" class="btn ghost small" id="jobAliasSaveBtn">Сохранить название</button><button type="button" class="btn ghost small" id="jobAliasResetBtn">Сбросить</button><button type="button" class="btn ghost small" id="jobAliasCancelBtn">Отменить</button></div>` : ''}
            ${canEdit && !nameEditVisible ? '<div class="job-hero-actions"><button type="button" class="btn ghost small" id="jobAliasEditBtn">Изменить название</button></div>' : ''}
          </div>
        </div>
        <div class="job-side-summary">
          <div class="summary-tile summary-tile-status"><div class="summary-kicker">Состояние задачи</div><strong class="summary-value">${esc(humanizeStatus(job.status))}</strong><div class="summary-note">${job.status === 'paused' ? 'Задача сейчас не запускается по расписанию.' : 'Задача сейчас участвует в расписании.'}</div></div>
          <div class="summary-tile summary-tile-status"><div class="summary-kicker">Результат запуска</div><strong class="summary-value">${esc(jobLastOutcomeLabel(job))}</strong><div class="summary-note">${esc(job.last_run_summary || 'Краткий итог не указан.')}</div></div>
          <div class="summary-tile"><div class="summary-kicker">Следующий запуск</div><strong class="summary-value">${formatTs(job.next_run_at)}</strong><div class="summary-note">Расписание: ${esc(job.schedule_summary || '—')}</div></div>
          <div class="summary-tile"><div class="summary-kicker">Последний запуск</div><strong class="summary-value">${formatTs(job.last_run_at)}</strong><div class="summary-note">Подписчики: ${esc(String(job.subscriber_count || 0))}</div></div>
        </div>
      </div>
      <div class="job-access-grid">
        <div class="job-section-card job-section-plain job-details-group">
          <div class="job-card-head"><h4>Приватность</h4></div>
          <div class="list-block">${`<div class="list-row"><strong>${esc(humanizeVisibility(job.visibility))}</strong><div class="muted">${visibilityNote}</div></div>`}</div>
        </div>
        <div class="job-section-card job-section-plain job-details-group">
          <div class="job-card-head"><h4>Куда отправляется результат</h4></div>
          <div class="list-block">${recipientRows}</div>
        </div>
      </div>
      <div class="job-support-grid">
        <div class="job-section-card job-section-plain job-details-group job-history-section">
          <div class="job-card-head"><h4>История запусков</h4></div>
          <div class="list-block">${runRows}</div>
        </div>
      </div>
      ${showParams ? `<div class="job-support-grid"><div class="job-section-card job-section-plain job-details-group"><div class="job-card-head"><h4>Параметры</h4></div><details class="details-block"><summary>Показать параметры</summary><div class="list-block" style="margin-top:10px;">${paramsFull}</div></details></div></div>` : ''}
    </div>
  `;
  els.jobDetail.querySelector('#jobRunBtn')?.addEventListener('click', () => guarded(runActiveJob));
  els.jobDetail.querySelector('#jobPauseResumeBtn')?.addEventListener('click', () => guarded(toggleActiveJobStatus));
  els.jobDetail.querySelector('#jobEditBtn')?.addEventListener('click', openEditJobModal);
  els.jobDetail.querySelector('#jobSubscribeBtn')?.addEventListener('click', () => guarded(toggleSubscription));
  els.jobDetail.querySelector('#jobAliasEditBtn')?.addEventListener('click', openJobNameEditor);
  els.jobDetail.querySelector('#jobAliasCancelBtn')?.addEventListener('click', () => {
    closeJobNameEditor();
    renderJobDetail();
  });
  els.jobDetail.querySelector('#jobAliasSaveBtn')?.addEventListener('click', () => guarded(async () => {
    const displayName = els.jobDetail.querySelector('#jobAliasInput')?.value.trim() || '';
    const data = await api(`/jobs/${encodeURIComponent(job.id)}`, {
      method: 'PATCH',
      body: JSON.stringify({ display_name: displayName, version: job.version ?? 1 }),
    });
    const idx = state.jobs.findIndex(item => String(item.id) === String(job.id));
    if (idx >= 0) state.jobs[idx] = data.job;
    closeJobNameEditor();
    renderJobsList();
    renderJobDetail();
    showInfoBanner(displayName ? 'Общее название сохранено.' : 'Общее название очищено.');
  }));
  els.jobDetail.querySelector('#jobAliasResetBtn')?.addEventListener('click', () => guarded(async () => {
    const data = await api(`/jobs/${encodeURIComponent(job.id)}`, {
      method: 'PATCH',
      body: JSON.stringify({ display_name: '', version: job.version ?? 1 }),
    });
    const idx = state.jobs.findIndex(item => String(item.id) === String(job.id));
    if (idx >= 0) state.jobs[idx] = data.job;
    closeJobNameEditor();
    renderJobsList();
    renderJobDetail();
    showInfoBanner('Общее название сброшено.');
  }));
}

function formatReferencePayload(item) {
  const extra = Object.entries(item || {})
    .filter(([key]) => !['id', 'dataset_key', 'item_key', 'label', 'sort_order', 'is_active', 'deleted_at', 'status', 'version', 'created_at', 'updated_at'].includes(key))
    .reduce((acc, [key, value]) => ({ ...acc, [key]: value }), {});
  return JSON.stringify(extra, null, 2);
}

function collectAdminUserPayload() {
  const styleText = `${currentOptionText(els.adminUserTone)}, ${currentOptionText(els.adminUserDepth)}, ${currentOptionText(els.adminUserMode)}`;
  return {
    ...(state.admin.editingUserId ? { version: state.admin.editingUserVersion ?? 1 } : {}),
    email: els.adminUserEmail.value.trim(),
    name: els.adminUserName.value.trim(),
    role: els.adminUserRole.value,
    status: els.adminUserStatusSelect?.value || 'active',
    password: els.adminUserPassword.value,
    timezone: els.adminUserTimezone.value.trim(),
    language: els.adminUserLanguage.value.trim(),
    team: els.adminUserTeam.value.trim(),
    title: els.adminUserTitle.value.trim(),
    goals: els.adminUserGoals.value.trim(),
    style: styleText,
    constraints: els.adminUserConstraints.value.trim(),
    assistant_profile: {
      tone: els.adminUserTone.value,
      answer_depth: els.adminUserDepth.value,
      interaction_mode: els.adminUserMode.value,
      about_user: els.adminUserAbout.value.trim(),
    },
    about_user: els.adminUserAbout.value.trim(),
    pinned: els.adminUserPinned.value.split('\n').map(item => item.trim()).filter(Boolean),
  };
}

function resetAdminUserForm() {
  state.admin.editingUserId = null;
  state.admin.editingUserVersion = null;
  state.admin.userHistory = [];
  openAdminUserCard('create');
  els.adminUserFormMode.value = 'create';
  els.adminUserSelect.value = '';
  els.adminUserEmail.value = '';
  els.adminUserName.value = '';
  els.adminUserRole.value = 'user';
  if (els.adminUserStatusSelect) els.adminUserStatusSelect.value = 'active';
  els.adminUserPassword.value = '';
  els.adminUserTimezone.value = 'UTC';
  els.adminUserLanguage.value = 'ru';
  els.adminUserTeam.value = '';
  els.adminUserTitle.value = '';
  els.adminUserGoals.value = '';
  els.adminUserConstraints.value = '';
  ensureAdminUserReferenceControls();
  els.adminUserTone.value = els.adminUserTone.value || 'business';
  els.adminUserDepth.value = els.adminUserDepth.value || 'balanced';
  els.adminUserMode.value = els.adminUserMode.value || 'compare_options';
  els.adminUserAbout.value = '';
  els.adminUserPinned.value = '';
  els.adminUserStylePreview.textContent = adminStylePreviewText();
  els.adminUserStatus.textContent = '';
  renderAdminUserHistory();
}

function fillAdminUserForm(user) {
  if (!user) {
    resetAdminUserForm();
    return;
  }
  openAdminUserCard('edit');
  state.admin.editingUserId = user.id;
  state.admin.editingUserVersion = user.version ?? 1;
  ensureAdminUserReferenceControls(user);
  els.adminUserFormMode.value = 'edit';
  els.adminUserSelect.value = String(user.id);
  els.adminUserEmail.value = user.email || '';
  els.adminUserName.value = user.name || '';
  els.adminUserRole.value = user.role || 'user';
  if (els.adminUserStatusSelect) els.adminUserStatusSelect.value = user.status || 'active';
  els.adminUserPassword.value = '';
  els.adminUserTimezone.value = user.timezone || 'UTC';
  els.adminUserLanguage.value = user.language || 'ru';
  els.adminUserTeam.value = user.team || '';
  els.adminUserTitle.value = user.title || '';
  els.adminUserGoals.value = user.goals || '';
  els.adminUserConstraints.value = user.constraints || '';
  els.adminUserTone.value = user.assistant_profile?.tone || els.adminUserTone.value || 'business';
  els.adminUserDepth.value = user.assistant_profile?.answer_depth || els.adminUserDepth.value || 'balanced';
  els.adminUserMode.value = user.assistant_profile?.interaction_mode || els.adminUserMode.value || 'compare_options';
  els.adminUserAbout.value = user.assistant_profile?.about_user || '';
  els.adminUserPinned.value = (user.pinned || []).join('\n');
  els.adminUserStylePreview.textContent = adminStylePreviewText();
  els.adminUserStatus.textContent = `Редактируется: ${user.email} · версия ${user.version ?? 1}`;
}

function humanizeUserStatus(status) {
  return ({ active: 'активен', inactive: 'не активен', deleted: 'удалён' })[status] || status || '—';
}

function humanizeSoftStatus(status) {
  return ({ active: 'Активен', inactive: 'Не активен', deleted: 'Удалён' })[status] || '—';
}

function renderAdminUserHistory() {
  if (!els.adminUserHistory) return;
  const rows = state.admin.userHistory || [];
  if (!state.admin.editingUserId) {
    els.adminUserHistory.innerHTML = '<div class="muted">История изменений появится после выбора пользователя.</div>';
    return;
  }
  if (!rows.length) {
    els.adminUserHistory.innerHTML = '<div class="muted">История изменений пока пуста.</div>';
    return;
  }
  els.adminUserHistory.innerHTML = [`<div class="muted" style="margin-bottom:8px;">История изменений пользователя</div>`, ...rows.map(item => `
    <div class="list-row">
      <strong>${esc(item.change_type === 'create' ? 'Создание' : item.change_type === 'bulk_inactivate' ? 'Массовый перевод в неактивные' : item.change_type === 'bulk_delete' ? 'Массовое удаление' : 'Обновление')}</strong>
      <div class="muted">${formatTs(item.created_at)} · ${esc(item.actor_email || 'системный процесс')} · версия: ${esc(String(item.snapshot?.version ?? '—'))}</div>
      <div class="muted">${esc(item.snapshot?.email || '—')} · ${esc(item.snapshot?.role === 'admin' ? 'администратор' : 'пользователь')}</div>
    </div>
  `)].join('');
}

function getSelectedAdminUserIds() {
  const ids = Array.isArray(state.admin.selectedUserIds) ? state.admin.selectedUserIds : [];
  return ids.map(id => Number(id)).filter(id => Number.isInteger(id) && id > 0);
}

function syncAdminUserSelection() {
  const existingIds = new Set((state.admin.users || []).map(user => Number(user.id)));
  state.admin.selectedUserIds = getSelectedAdminUserIds().filter(id => existingIds.has(id));
}

function setAdminUserSelection(ids) {
  state.admin.selectedUserIds = Array.from(new Set((ids || []).map(id => Number(id)).filter(id => Number.isInteger(id) && id > 0)));
}

function renderAdminUserSelectionStatus() {
  if (!els.adminUserSelectionStatus) return;
  syncAdminUserSelection();
  const selectedIds = getSelectedAdminUserIds();
  const selectedUsers = state.admin.users.filter(user => selectedIds.includes(Number(user.id)));
  if (!selectedUsers.length) {
    els.adminUserSelectionStatus.textContent = 'Ничего не выбрано.';
  } else {
    const statuses = selectedUsers.map(user => user.status || (user.deleted_at ? 'deleted' : (user.is_active === false ? 'inactive' : 'active')));
    const activeCount = statuses.filter(status => status === 'active').length;
    const inactiveCount = statuses.filter(status => status === 'inactive').length;
    const deletedCount = statuses.filter(status => status === 'deleted').length;
    els.adminUserSelectionStatus.textContent = `Выбрано: ${selectedUsers.length} · активных ${activeCount} · неактивных ${inactiveCount} · удалённых ${deletedCount}`;
  }
  if (els.adminClearUserSelectionBtn) els.adminClearUserSelectionBtn.disabled = selectedUsers.length === 0;
  if (els.adminBulkInactiveUsersBtn) els.adminBulkInactiveUsersBtn.disabled = selectedUsers.length === 0;
  if (els.adminBulkDeleteUsersBtn) els.adminBulkDeleteUsersBtn.disabled = selectedUsers.length === 0;
}

function toggleAdminUserSelection(userId, checked) {
  const current = new Set(getSelectedAdminUserIds());
  const numericId = Number(userId);
  if (!Number.isInteger(numericId) || numericId <= 0) return;
  if (checked) current.add(numericId);
  else current.delete(numericId);
  state.admin.selectedUserIds = Array.from(current);
  renderAdminUserSelectionStatus();
}

async function bulkUpdateAdminUsers(status) {
  syncAdminUserSelection();
  const userIds = getSelectedAdminUserIds();
  if (!userIds.length) {
    showBanner('Сначала выбери пользователей в таблице.', true);
    return;
  }
  const result = await api('/admin/users/bulk-status', {
    method: 'POST',
    body: JSON.stringify({ user_ids: userIds, status }),
  });
  const labels = {
    inactive: 'переведены в неактивные',
    deleted: 'удалены из выбора',
    active: 'активированы',
  };
  setAdminUserSelection([]);
  await refreshAdmin();
  const changed = Array.isArray(result.users) ? result.users.length : userIds.length;
  const text = `Пользователи ${labels[status] || 'обновлены'}: ${changed}`;
  if (els.adminImportStatus) els.adminImportStatus.textContent = text;
  showBanner(text, false);
}

function getSelectedReferenceItemKeys(datasetKey) {
  const map = state.admin.selectedReferenceItems || {};
  const items = Array.isArray(map?.[datasetKey]) ? map[datasetKey] : [];
  return Array.from(new Set(items.map(itemKey => normalizeText(itemKey)).filter(Boolean)));
}

function syncAdminReferenceSelection(datasetKey) {
  const dataset = state.admin.references?.[datasetKey];
  if (!dataset) {
    delete state.admin.selectedReferenceItems?.[datasetKey];
    return;
  }
  const existingKeys = new Set((dataset.items || []).map(item => normalizeText(item.item_key)).filter(Boolean));
  const selected = getSelectedReferenceItemKeys(datasetKey).filter(itemKey => existingKeys.has(itemKey));
  state.admin.selectedReferenceItems = state.admin.selectedReferenceItems || {};
  if (selected.length) state.admin.selectedReferenceItems[datasetKey] = selected;
  else delete state.admin.selectedReferenceItems[datasetKey];
}

function setAdminReferenceSelection(datasetKey, itemKeys) {
  state.admin.selectedReferenceItems = state.admin.selectedReferenceItems || {};
  const normalized = Array.from(new Set((itemKeys || []).map(itemKey => normalizeText(itemKey)).filter(Boolean)));
  if (normalized.length) state.admin.selectedReferenceItems[datasetKey] = normalized;
  else delete state.admin.selectedReferenceItems[datasetKey];
}

function toggleAdminReferenceSelection(datasetKey, itemKey, checked) {
  const current = new Set(getSelectedReferenceItemKeys(datasetKey));
  const normalizedKey = normalizeText(itemKey);
  if (!normalizedKey) return;
  if (checked) current.add(normalizedKey);
  else current.delete(normalizedKey);
  setAdminReferenceSelection(datasetKey, Array.from(current));
  renderReferenceDetail(datasetKey);
}

function renderAdminReferenceSelectionStatus(datasetKey) {
  const dataset = state.admin.references?.[datasetKey];
  const statusEl = document.querySelector('[data-ref-selection-status]');
  const clearBtn = document.querySelector('[data-ref-clear-selection]');
  const inactiveBtn = document.querySelector('[data-ref-bulk-inactive]');
  const deleteBtn = document.querySelector('[data-ref-bulk-delete]');
  if (!dataset || !statusEl) return;
  syncAdminReferenceSelection(datasetKey);
  const selectedKeys = getSelectedReferenceItemKeys(datasetKey);
  const selectedItems = (dataset.items || []).filter(item => selectedKeys.includes(item.item_key));
  if (!selectedItems.length) {
    statusEl.textContent = 'Ничего не выбрано.';
  } else {
    const statuses = selectedItems.map(item => item.status || (item.deleted_at ? 'deleted' : (item.is_active === false ? 'inactive' : 'active')));
    const activeCount = statuses.filter(status => status === 'active').length;
    const inactiveCount = statuses.filter(status => status === 'inactive').length;
    const deletedCount = statuses.filter(status => status === 'deleted').length;
    statusEl.textContent = `Выбрано: ${selectedItems.length} · активных ${activeCount} · неактивных ${inactiveCount} · удалённых ${deletedCount}`;
  }
  if (clearBtn) clearBtn.disabled = selectedItems.length === 0;
  if (inactiveBtn) inactiveBtn.disabled = selectedItems.length === 0;
  if (deleteBtn) deleteBtn.disabled = selectedItems.length === 0;
}

async function bulkUpdateReferenceItems(datasetKey, status) {
  syncAdminReferenceSelection(datasetKey);
  const itemKeys = getSelectedReferenceItemKeys(datasetKey);
  if (!itemKeys.length) {
    showBanner('Сначала выбери элементы справочника в таблице.', true);
    return;
  }
  const result = await api(`/admin/reference-data/${datasetKey}/bulk-status`, {
    method: 'POST',
    body: JSON.stringify({ item_keys: itemKeys, status }),
  });
  const labels = {
    inactive: 'переведены в неактивные',
    deleted: 'удалены из выбора',
    active: 'активированы',
  };
  state.admin.references[datasetKey] = result.dataset;
  setAdminReferenceSelection(datasetKey, []);
  renderReferenceData();
  renderReferenceDetail(datasetKey);
  const changed = Array.isArray(result.items) ? result.items.length : itemKeys.length;
  const text = `Элементы справочника ${labels[status] || 'обновлены'}: ${changed}`;
  if (els.adminReferenceStatus) els.adminReferenceStatus.textContent = text;
  showBanner(text, false);
}

function renderReferenceData() {
  const refs = state.admin.references || {};
  const entries = Object.values(refs);
  if (!entries.length) {
    els.adminReferenceData.innerHTML = '<div class="muted">Справочники не загружены.</div>';
    if (els.adminReferenceStatus) els.adminReferenceStatus.textContent = '';
    if (els.adminReferenceDetail) els.adminReferenceDetail.innerHTML = '<div class="muted">Выбери справочник.</div>';
    return;
  }
  const totalItems = entries.reduce((sum, dataset) => sum + ((dataset.items || []).length), 0);
  const statusOf = item => item.status || (item.deleted_at ? 'deleted' : (item.is_active === false ? 'inactive' : 'active'));
  const activeItems = entries.reduce((sum, dataset) => sum + (dataset.items || []).filter(item => statusOf(item) === 'active').length, 0);
  const inactiveItems = entries.reduce((sum, dataset) => sum + (dataset.items || []).filter(item => statusOf(item) === 'inactive').length, 0);
  const deletedItems = entries.reduce((sum, dataset) => sum + (dataset.items || []).filter(item => statusOf(item) === 'deleted').length, 0);
  if (els.adminReferenceStatus) {
    els.adminReferenceStatus.textContent = `Справочников: ${entries.length} · элементов: ${totalItems} · активных: ${activeItems} · не активных: ${inactiveItems} · удалённых: ${deletedItems}`;
  }
  els.adminReferenceData.innerHTML = `
    <div class="files-table-wrap">
      <table class="data-table">
        <thead><tr><th>Название</th><th>Ключ</th><th>Описание</th><th>Элементы</th><th>Статусы</th><th></th></tr></thead>
        <tbody>
          ${entries.map(dataset => {
            const itemsCount = (dataset.items || []).length;
            const activeCount = (dataset.items || []).filter(item => statusOf(item) === 'active').length;
            const inactiveCount = (dataset.items || []).filter(item => statusOf(item) === 'inactive').length;
            const deletedCount = (dataset.items || []).filter(item => statusOf(item) === 'deleted').length;
            return `<tr>
              <td><strong>${esc(dataset.label || dataset.dataset_key)}</strong></td>
              <td>${esc(dataset.dataset_key)}</td>
              <td>${esc(dataset.description || 'Без описания')}</td>
              <td>${itemsCount}</td>
              <td><div class="admin-summary-line"><span class="soft-chip">Активных: ${activeCount}</span><span class="soft-chip">Не активных: ${inactiveCount}</span><span class="soft-chip">Удалённых: ${deletedCount}</span></div></td>
              <td><button class="btn ghost small" type="button" data-ref-open="${esc(dataset.dataset_key)}">Открыть</button></td>
            </tr>`;
          }).join('')}
        </tbody>
      </table>
    </div>
  `;
}

function renderReferenceDetail(datasetKey) {
  const dataset = state.admin.references?.[datasetKey];
  if (!dataset) {
    els.adminReferenceDetail.innerHTML = '<div class="muted">Справочник не найден.</div>';
    return;
  }
  openAdminReferenceCard();
  syncAdminReferenceSelection(datasetKey);
  const selectedKeys = new Set(getSelectedReferenceItemKeys(datasetKey));
  const allItemKeys = (dataset.items || []).map(item => normalizeText(item.item_key)).filter(Boolean);
  const allSelected = allItemKeys.length > 0 && allItemKeys.every(itemKey => selectedKeys.has(itemKey));
  const items = (dataset.items || []).map(item => {
    const historyKey = `${dataset.dataset_key}::${item.item_key}`;
    const history = state.admin.referenceHistory?.[historyKey] || [];
    const payloadPreview = formatReferencePayload(item);
    const itemStatus = item.status || (item.deleted_at ? 'deleted' : (item.is_active === false ? 'inactive' : 'active'));
    const historyBlock = history.length ? `
      <details class="details-block" style="margin-top:8px;">
        <summary>История изменений · ${history.length}</summary>
        <div class="list-block" style="margin-top:8px;">
          ${history.map(entry => `
            <div class="list-row tight">
              <strong>${esc(entry.change_type === 'create' ? 'Создание' : entry.change_type === 'bulk_inactivate' ? 'Массовый перевод в неактивные' : entry.change_type === 'bulk_delete' ? 'Массовое удаление' : entry.change_type === 'bulk_activate' ? 'Массовая активация' : 'Обновление')}</strong>
              <div class="muted">${formatTs(entry.created_at)} · ${esc(entry.actor_email || 'системный процесс')} · версия: ${esc(String(entry.snapshot?.version ?? '—'))}</div>
            </div>
          `).join('')}
        </div>
      </details>` : '';
    return `
      <tr>
        <td><input type="checkbox" data-ref-pick="${esc(dataset.dataset_key)}::${esc(item.item_key)}" ${selectedKeys.has(item.item_key) ? 'checked' : ''} aria-label="Выбрать элемент ${esc(item.item_key)}" /></td>
        <td><strong>${esc(item.label || item.item_key)}</strong><div class="muted">${esc(item.item_key)}</div></td>
        <td>${esc(humanizeSoftStatus(itemStatus))}</td>
        <td>${esc(String(item.sort_order ?? 0))}</td>
        <td>${payloadPreview !== '{}' ? `<details class="details-block"><summary>JSON</summary><div class="payload-preview">${esc(payloadPreview)}</div></details>` : '<span class="muted">—</span>'}</td>
        <td>
          <div class="row">
            <button class="btn ghost small" type="button" data-ref-edit="${esc(dataset.dataset_key)}::${esc(item.item_key)}">Редактировать</button>
            <button class="btn ghost small" type="button" data-ref-history="${esc(dataset.dataset_key)}::${esc(item.item_key)}">История</button>
          </div>
          ${historyBlock}
        </td>
      </tr>`;
  }).join('') || '<tr><td colspan="6" class="muted">Элементов пока нет.</td></tr>';
  els.adminReferenceDetail.innerHTML = `
    <div class="row" style="justify-content:space-between;align-items:flex-start;gap:12px;margin-bottom:12px;">
      <div>
        <strong>${esc(dataset.label || dataset.dataset_key)}</strong>
        <div class="muted">${esc(dataset.description || 'Без описания')}</div>
      </div>
      <span class="soft-chip">${esc(dataset.dataset_key)}</span>
    </div>
    <div class="row" style="justify-content:space-between;align-items:center;gap:12px;margin-bottom:12px;flex-wrap:wrap;">
      <div class="muted" data-ref-selection-status>Ничего не выбрано.</div>
      <div class="row" style="justify-content:flex-end;flex-wrap:wrap;">
        <button class="btn ghost small" type="button" data-ref-select-all="${esc(dataset.dataset_key)}">Выбрать всех</button>
        <button class="btn ghost small" type="button" data-ref-clear-selection="${esc(dataset.dataset_key)}">Снять выбор</button>
        <button class="btn ghost small" type="button" data-ref-bulk-inactive="${esc(dataset.dataset_key)}">Перевести в неактивные</button>
        <button class="btn ghost small" type="button" data-ref-bulk-delete="${esc(dataset.dataset_key)}">Удалить из выбора</button>
        <button class="btn ghost small" type="button" data-ref-create="${esc(dataset.dataset_key)}">+ Добавить элемент</button>
      </div>
    </div>
    <div class="files-table-wrap">
      <table class="data-table">
        <thead><tr><th><input type="checkbox" data-ref-pick-all="${esc(dataset.dataset_key)}" ${allSelected ? 'checked' : ''} aria-label="Выбрать все элементы ${esc(dataset.dataset_key)}" /></th><th>Элемент</th><th>Статус</th><th>Порядок</th><th>Доп. поля</th><th></th></tr></thead>
        <tbody>${items}</tbody>
      </table>
    </div>
  `;
  els.adminReferenceDetail.querySelector('[data-ref-pick-all]')?.addEventListener('change', event => {
    if (event.target.checked) setAdminReferenceSelection(datasetKey, allItemKeys);
    else setAdminReferenceSelection(datasetKey, []);
    renderReferenceDetail(datasetKey);
  });
  els.adminReferenceDetail.querySelectorAll('[data-ref-pick]').forEach(input => {
    input.addEventListener('change', event => {
      const [, itemKey] = (event.target.dataset.refPick || '').split('::');
      toggleAdminReferenceSelection(datasetKey, itemKey, event.target.checked);
    });
  });
  renderAdminReferenceSelectionStatus(datasetKey);
}

function renderAdmin() {
  if (state.user?.role !== 'admin') {
    els.adminMetrics.innerHTML = '<div class="card">Экран доступен только администратору.</div>';
    if (els.adminUsers) els.adminUsers.innerHTML = '<div class="muted">—</div>';
    if (els.adminThreads) els.adminThreads.innerHTML = '<div class="muted">—</div>';
    if (els.adminJobs) els.adminJobs.innerHTML = '<div class="muted">—</div>';
    els.adminEvents.innerHTML = '<div class="muted">—</div>';
    els.adminDbInfo.innerHTML = '<div class="muted">—</div>';
    els.adminSources.innerHTML = '<div class="muted">—</div>';
    els.adminReferenceData.innerHTML = '<div class="muted">—</div>';
    return;
  }
  const health = state.admin.health || {};
  const sources = state.admin.sources || {};
  const overviewTimeseries = state.admin.overviewTimeseries || { granularity: 'day', buckets: [] };
  const eventsFilter = state.admin.eventsFilter || { dateFrom: '', dateTo: '', limit: 100 };
  if (els.adminChartGranularity) {
    els.adminChartGranularity.value = overviewTimeseries.granularity || 'day';
  }
  if (els.adminEventsDateFrom) els.adminEventsDateFrom.value = toDatetimeLocalValue(eventsFilter.dateFrom);
  if (els.adminEventsDateTo) els.adminEventsDateTo.value = toDatetimeLocalValue(eventsFilter.dateTo);
  if (els.adminCharts) {
    const buckets = overviewTimeseries.buckets || [];
    els.adminCharts.innerHTML = [
      renderOverviewChartCard('Новые пользователи', 'users', 'Сколько профилей появилось в web-контуре за выбранный интервал.', buckets, overviewTimeseries.granularity || 'day'),
      renderOverviewChartCard('Новые чаты', 'threads', 'Сколько чатов создавалось по интервалам времени.', buckets, overviewTimeseries.granularity || 'day'),
      renderOverviewChartCard('Сообщения', 'messages', 'Плотность переписки в web-интерфейсе.', buckets, overviewTimeseries.granularity || 'day'),
      renderOverviewChartCard('Запуски задач', 'job_runs', 'Частота запусков задач в web-контуре и через связанный планировщик.', buckets, overviewTimeseries.granularity || 'day'),
      renderOverviewChartCard('Ошибки задач', 'job_errors', 'Сколько запусков задач завершалось ошибкой по периодам.', buckets, overviewTimeseries.granularity || 'day'),
    ].join('');
  }
  const db = sources.database || {};
  const importCfg = sources.import || {};
  const ldap = sources.ldap || {};
  const hermes = sources.hermes || {};
  els.adminMetrics.innerHTML = [
    ['Пользователи в web-контуре', formatNumber(health.users)],
    ['Чаты', formatNumber(health.threads)],
    ['Сообщения', formatNumber(health.messages)],
    ['Web-задачи', formatNumber(health.jobs)],
    ['Запуски задач', formatNumber(health.job_runs)],
    ['Ошибки задач за 7 дней', formatNumber(health.failed_job_runs_7d)],
    ['Активные пользователи за 7 дней', formatNumber(health.active_users_7d)],
    ['Prompt tokens', formatNumber(health.prompt_tokens)],
    ['Completion tokens', formatNumber(health.completion_tokens)],
    ['Всего токенов', formatNumber(health.total_tokens)],
  ].map(([title, value]) => `<div class="card metric"><div class="muted">${title}</div><strong>${value}</strong></div>`).join('');
  if (els.adminUsersTable) {
    syncAdminUserSelection();
    const sortedUsers = getSortedAdminUsers();
    const selectedIds = new Set(getSelectedAdminUserIds());
    const allUserIds = sortedUsers.map(user => Number(user.id)).filter(id => Number.isInteger(id) && id > 0);
    const allSelected = allUserIds.length > 0 && allUserIds.every(id => selectedIds.has(id));
    els.adminUsersTable.innerHTML = sortedUsers.length ? `
      <div class="files-table-wrap">
        <table class="data-table">
          <thead><tr><th><input type="checkbox" data-admin-user-pick-all ${allSelected ? 'checked' : ''} aria-label="Выбрать всех пользователей" /></th><th>${sortButtonLabel('Имя', 'name')}</th><th>${sortButtonLabel('Email', 'email')}</th><th>${sortButtonLabel('Роль', 'role')}</th><th>${sortButtonLabel('Статус', 'status')}</th><th>${sortButtonLabel('Чаты', 'thread_count')}</th><th>${sortButtonLabel('Задачи', 'job_count')}</th><th>Профиль</th><th></th></tr></thead>
          <tbody>
            ${sortedUsers.map(user => `<tr>
              <td><input type="checkbox" data-admin-user-pick="${user.id}" ${selectedIds.has(Number(user.id)) ? 'checked' : ''} aria-label="Выбрать пользователя ${esc(user.email)}" /></td>
              <td><strong>${esc(user.name || '—')}</strong><div class="muted">Версия ${esc(String(user.version ?? 1))}</div></td>
              <td>${esc(user.email)}</td>
              <td>${esc(user.role === 'admin' ? 'Администратор' : 'Пользователь')}</td>
              <td>${esc(humanizeUserStatus(user.status || (user.deleted_at ? 'deleted' : (user.is_active === false ? 'inactive' : 'active'))))}</td>
              <td><span class="soft-chip">${user.thread_count}</span></td>
              <td><span class="soft-chip">${user.job_count}</span></td>
              <td><div>${esc(user.team || '—')}</div><div class="muted">${esc(user.title || 'Без позиционирования')}</div></td>
              <td><button class="btn ghost small" type="button" data-user-edit="${user.id}">Редактировать</button></td>
            </tr>`).join('')}
          </tbody>
        </table>
      </div>
    ` : '<div class="muted">Нет данных.</div>';
    els.adminUsersTable.querySelectorAll('[data-admin-user-sort]').forEach(button => {
      button.addEventListener('click', () => setAdminUserSort(button.dataset.adminUserSort));
    });
    els.adminUsersTable.querySelector('[data-admin-user-pick-all]')?.addEventListener('change', event => {
      if (event.target.checked) setAdminUserSelection(sortedUsers.map(user => user.id));
      else setAdminUserSelection([]);
      renderAdmin();
    });
    els.adminUsersTable.querySelectorAll('[data-admin-user-pick]').forEach(input => {
      input.addEventListener('change', event => {
        toggleAdminUserSelection(event.target.dataset.adminUserPick, event.target.checked);
        const selectAll = els.adminUsersTable?.querySelector('[data-admin-user-pick-all]');
        if (selectAll) {
          const allIds = sortedUsers.map(user => Number(user.id)).filter(id => Number.isInteger(id) && id > 0);
          const selected = new Set(getSelectedAdminUserIds());
          selectAll.checked = allIds.length > 0 && allIds.every(id => selected.has(id));
        }
      });
    });
  }
  if (els.adminThreads) {
    els.adminThreads.innerHTML = state.admin.threads.length ? state.admin.threads.map(thread => `<div class="list-row"><strong>${esc(thread.title)}</strong><div class="muted">${esc(thread.email)} · сообщений: ${thread.message_count} · ${thread.archived ? 'архив' : 'активный'}</div></div>`).join('') : '<div class="muted">Нет данных.</div>';
  }
  if (els.adminEventsStatus) {
    const period = [
      eventsFilter.dateFrom ? `с ${formatTs(eventsFilter.dateFrom)}` : '',
      eventsFilter.dateTo ? `по ${formatTs(eventsFilter.dateTo)}` : '',
    ].filter(Boolean).join(' ');
    els.adminEventsStatus.textContent = state.admin.events.length
      ? `Показано событий: ${state.admin.events.length}${period ? ` · ${period}` : ''}`
      : `События не найдены${period ? ` · ${period}` : ''}`;
  }
  els.adminEvents.innerHTML = state.admin.events.length ? `
    <table class="data-table">
      <thead><tr><th>Когда</th><th>Пользователь</th><th>Событие</th><th>Объект</th><th>Кратко</th></tr></thead>
      <tbody>
        ${state.admin.events.map(event => `
          <tr>
            <td>${formatTs(event.created_at)}</td>
            <td>${esc(event.email || '—')}</td>
            <td>${esc(humanizeEventType(event.event_type))}</td>
            <td><strong>${esc(event.subject || '—')}</strong></td>
            <td>${esc(event.content_short || '—')}</td>
          </tr>
        `).join('')}
      </tbody>
    </table>
  ` : '<div class="muted">Нет данных.</div>';
  els.adminDbInfo.innerHTML = [
    `<div class="list-row"><strong>Текущая база</strong><div class="muted">${esc(db.current_path || '—')}</div></div>`,
    `<div class="list-row"><strong>Как сменить базу</strong><div class="muted">${esc((db.switch_flow || []).join(' ')) || 'Следовать инструкции backend-контура.'}</div></div>`,
    `<div class="list-row"><strong>TTL сессии</strong><div class="muted">${formatNumber(health.session_ttl_hours)} ч. бездействия до отзыва токена.</div></div>`,
  ].join('');
  els.adminSources.innerHTML = [
    `<div class="list-row"><strong>Рабочий контур</strong><div class="muted">${esc(state.mode || '—')} · frontend и backend отвечают в текущей web-сессии</div></div>`,
    `<div class="list-row"><strong>Hermes downstream</strong><div class="muted">${health.hermes_downstream?.configured ? 'подключён' : 'не настроен'} · модель: ${esc(health.hermes_downstream?.model || '—')}</div></div>`,
    `<div class="list-row"><strong>Планировщик Hermes</strong><div class="muted">${hermes.scheduler_enabled ? 'включён' : 'выключен'} · интервал опроса: ${esc(String(hermes.scheduler_poll_seconds ?? '—'))} сек.</div></div>`,
    `<div class="list-row"><strong>Импорт пользователей</strong><div class="muted">${(importCfg.formats || []).join(', ') || '—'} · колонок в шаблоне: ${(importCfg.template_columns || []).length || 0}</div></div>`,
    `<div class="list-row"><strong>LDAP-готовность</strong><div class="muted">${ldap.supported ? 'Библиотека доступна' : 'Нужно установить ldap3'} · ${ldap.configured ? 'конфигурация задана' : 'конфигурация не задана'}</div></div>`,
  ].join('');
  els.adminUserSelect.innerHTML = ['<option value="">— выбрать —</option>', ...state.admin.users.filter(user => !user.deleted_at && user.is_active !== false).map(user => `<option value="${user.id}">${esc(user.email)} · ${esc(user.role === 'admin' ? 'администратор' : 'пользователь')}</option>`)].join('');
  if (els.adminChatNoticeEnabled && els.adminChatNoticeText) {
    const notice = state.admin.chatNotice || state.bootstrap?.chat_notice || { enabled: true, text: '' };
    els.adminChatNoticeEnabled.value = notice.enabled ? '1' : '0';
    els.adminChatNoticeText.value = notice.text || '';
  }
  ensureAdminUserReferenceControls(state.admin.users.find(user => user.id === state.admin.editingUserId) || null);
  if (state.admin.editingUserId) {
    els.adminUserSelect.value = String(state.admin.editingUserId);
  }
  renderAdminUserHistory();
  renderReferenceData();
  setAdminSection(state.adminSection || 'overview');
  renderAdminUserSelectionStatus();
}

function switchScreen(name) {
  state.screen = name;
  const titles = {
    chat: ['Чаты', 'Рабочий диалог с учётом личных настроек ответа.'],
    jobs: ['Задачи', 'Регулярные задачи и история запусков.'],
    profile: ['Профиль', 'Личные настройки ответа и повторное использование файлов.'],
    admin: ['Управление', 'Пользователи, база, события и справочники.'],
  };
  els.mainTitle.textContent = titles[name][0];
  els.mainSubtitle.textContent = titles[name][1];
  els.screenChat.classList.toggle('hidden', name !== 'chat');
  els.screenJobs.classList.toggle('hidden', name !== 'jobs');
  els.screenProfile.classList.toggle('hidden', name !== 'profile');
  els.screenAdmin.classList.toggle('hidden', name !== 'admin');
  els.composer.classList.toggle('hidden', name !== 'chat');
  if (els.topbarProfileBtn) {
    els.topbarProfileBtn.classList.toggle('hidden', name === 'profile');
  }
  els.navButtons.forEach(button => button.classList.toggle('active', button.dataset.screen === name));
  if (name === 'profile') setProfileSection(state.profileSection || 'identity');
  if (name === 'chat') updateComposerState();
  renderChatPolicyBanner();
  updateChatScrollUi();
  pinChatIntroWithinScreen();
}

async function refreshServiceInfo() {
  const info = await fetch(SERVICE_INFO_PATH).then(res => res.json());
  state.mode = info.mode || '-';
  state.serviceStatus = info.status === 'ok' ? 'Готово к работе' : (info.status || 'Неизвестно');
  els.statusText.textContent = `${state.serviceStatus} · ${state.mode}`;
}

async function refreshPublicSetupStatus() {
  const data = await fetch(`${API_BASE}/setup/status`).then(res => res.json());
  state.setupRequired = Boolean(data.needs_setup);
  state.demoMode = Boolean(data.demo_mode);
  els.setupCard.classList.toggle('hidden', !state.setupRequired);
  if (state.setupRequired) {
    setLoginError('Сначала нужно создать первого администратора.');
  }
}

async function refreshBootstrap() {
  state.bootstrap = await api('/bootstrap');
  renderChatPolicyBanner();
}

async function refreshFeedbackReasons() {
  const data = await api('/feedback/reasons');
  state.feedbackReasons = data.reasons || [];
}

async function refreshProfile() {
  const data = await api('/me');
  state.user = data.user;
  state.profileSummary = data.profile_summary;
  state.personalization = data.personalization;
  ensureReferenceDrivenProfileControls();
  renderSidebarProfile();
  fillProfileForm();
  renderProfileSummary();
}

async function refreshUserFiles() {
  const data = await api('/files?limit=200');
  state.userFiles = data.files || [];
  renderProfileFiles();
}

async function refreshThreads() {
  if (state.isRefreshingThreads) return;
  state.isRefreshingThreads = true;
  try {
    const data = await api('/threads?include_archived=1');
    state.threads = data.threads || [];
    if (!state.activeThreadId && state.threads.length) state.activeThreadId = state.threads[0].id;
    if (state.activeThreadId && !state.threads.find(thread => thread.id === state.activeThreadId)) state.activeThreadId = state.threads[0]?.id || null;
    renderThreads();
  } finally {
    state.isRefreshingThreads = false;
  }
}

async function loadThread(threadId) {
  const requestSeq = ++state.threadLoadRequestSeq;
  state.activeThreadLoadSeq = requestSeq;
  const data = await api(`/threads/${threadId}`);
  if (state.activeThreadLoadSeq !== requestSeq) return;
  state.activeThreadId = data.thread.id;
  state.messages = data.messages || [];
  markThreadRead(data.thread.id, data.messages?.[data.messages.length - 1]?.created_at || data.thread.last_message_at || new Date().toISOString());
  renderThreads();
  renderThreadsModal();
  renderMessages('bottom');
  switchScreen('chat');
}

async function refreshJobsMeta() {
  state.jobsMeta = await api('/jobs/meta');
}

async function refreshJobs() {
  if (state.isRefreshingJobs) return;
  state.isRefreshingJobs = true;
  try {
    const data = await api(`/jobs?scope=${encodeURIComponent(state.jobScope)}`);
    state.jobs = data.jobs || [];
    closeJobNameEditor();
    if (!state.activeJobId && state.jobs.length) state.activeJobId = state.jobs[0].id;
    if (state.activeJobId && !state.jobs.find(job => job.id === state.activeJobId)) state.activeJobId = state.jobs[0]?.id || null;
    renderJobsList();
    if (state.activeJobId) await loadJob(state.activeJobId, false);
    else renderJobDetail();
  } finally {
    state.isRefreshingJobs = false;
  }
}

async function loadJob(jobId, setScreen = false) {
  const data = await api(`/jobs/${encodeURIComponent(jobId)}`);
  const idx = state.jobs.findIndex(job => String(job.id) === String(jobId));
  if (idx >= 0) state.jobs[idx] = data.job;
  else state.jobs.unshift(data.job);
  state.activeJobId = data.job?.id ?? jobId;
  closeJobNameEditor();
  renderJobsList();
  renderJobDetail();
  if (setScreen) switchScreen('jobs');
}

async function refreshAdmin() {
  if (state.user?.role !== 'admin') {
    renderAdmin();
    return;
  }
  if (state.isRefreshingAdmin) return;
  state.isRefreshingAdmin = true;
  try {
    const adminGranularity = state.admin.overviewTimeseries?.granularity || 'day';
    const eventQuery = adminEventsQueryParams();
    state.admin.health = await api('/admin/health');
    state.admin.users = (await api('/admin/users')).users || [];
    state.admin.threads = (await api('/admin/threads')).threads || [];
    state.admin.jobs = (await api('/admin/jobs')).jobs || [];
    state.admin.events = (await api(`/admin/events?${eventQuery.toString()}`)).events || [];
    state.admin.sources = await api('/admin/user-sources');
    state.admin.references = (await api('/admin/reference-data')).references || {};
    state.admin.chatNotice = (await api('/admin/chat-notice')).chat_notice || null;
    state.admin.overviewTimeseries = await loadAdminOverviewTimeseries(adminGranularity);
    renderAdmin();
  } finally {
    state.isRefreshingAdmin = false;
  }
}

async function applyAdminEventsFilter() {
  const dateFrom = datetimeLocalToIso(els.adminEventsDateFrom?.value || '');
  const dateTo = datetimeLocalToIso(els.adminEventsDateTo?.value || '', { endOfMinute: true });
  state.admin.eventsFilter = {
    ...(state.admin.eventsFilter || {}),
    dateFrom,
    dateTo,
    limit: 100,
  };
  await refreshAdmin();
}

async function resetAdminEventsFilter() {
  state.admin.eventsFilter = { dateFrom: '', dateTo: '', limit: 100 };
  await refreshAdmin();
}

async function exportAdminEvents(format) {
  const params = adminEventsQueryParams({ exportFormat: format });
  await apiDownload(`/admin/events?${params.toString()}`, `admin-events.${format}`);
  if (els.adminEventsStatus) {
    els.adminEventsStatus.textContent = `Выгрузка подготовлена: admin-events.${format}`;
  }
}

async function changePassword() {
  const currentPassword = els.profileCurrentPassword?.value || '';
  const newPassword = els.profileNewPassword?.value || '';
  if (!currentPassword || !newPassword) {
    throw new Error('Заполни текущий и новый пароль');
  }
  await api('/me/change-password', {
    method: 'POST',
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
  });
  if (els.profileCurrentPassword) els.profileCurrentPassword.value = '';
  if (els.profileNewPassword) els.profileNewPassword.value = '';
  if (els.profilePasswordHint) els.profilePasswordHint.textContent = 'Пароль обновлён. Остальные сессии пользователя отозваны.';
  showInfoBanner('Пароль обновлён.');
}

async function loadAdminOverviewTimeseries(granularity, options = {}) {
  const nextGranularity = granularity || 'day';
  if (options.renderImmediately) {
    state.admin.overviewTimeseries = {
      ...(state.admin.overviewTimeseries || {}),
      granularity: nextGranularity,
      buckets: options.keepBuckets ? (state.admin.overviewTimeseries?.buckets || []) : [],
    };
    renderAdmin();
  }
  return await api(`/admin/overview-timeseries?granularity=${encodeURIComponent(nextGranularity)}`);
}

async function bootAuthenticated() {
  state.threadReadMap = loadThreadReadMap();
  await refreshServiceInfo();
  await refreshBootstrap();
  await refreshFeedbackReasons();
  await refreshProfile();
  await refreshThreads();

  renderSelectedFiles();
  updateComposerState();
  els.adminNavBtn.classList.toggle('hidden', state.user?.role !== 'admin');
  els.loginScreen.classList.add('hidden');
  els.appShell.classList.remove('hidden');
  hideBanner();
  switchScreen(state.screen);
  startUiAutoRefresh();

  if (state.activeThreadId) {
    try {
      await loadThread(state.activeThreadId);
    } catch (error) {
      state.messages = [];
      renderMessages();
      showBanner(`Не удалось открыть последний чат: ${error.message}`, true);
    }
  } else {
    renderMessages();
  }

  const deferredTasks = [
    refreshJobsMeta(),
    refreshUserFiles(),
  ];
  if (state.screen === 'jobs' || state.activeJobId) deferredTasks.push(refreshJobs());
  if (state.user?.role === 'admin' && state.screen === 'admin') deferredTasks.push(refreshAdmin());
  const deferredResults = await Promise.allSettled(deferredTasks);

  ensureReferenceDrivenProfileControls();
  ensureAdminUserReferenceControls();
  fillProfileForm();
  renderProfileFiles();

  const failedDeferred = deferredResults.find(item => item.status === 'rejected');
  if (failedDeferred) {
    showBanner(`Часть данных не загрузилась: ${failedDeferred.reason?.message || 'неизвестная ошибка'}`, true);
  }
}

async function login() {
  setLoginError('');
  if (state.setupRequired) {
    throw new Error('Сначала создай первого администратора.');
  }
  const data = await api('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email: els.loginInput.value.trim(), password: els.passwordInput.value })
  });
  setToken(data.token);
  await bootAuthenticated();
}

async function bootstrapAdmin() {
  const payload = {
    name: els.setupNameInput.value.trim() || 'Administrator',
    email: els.setupEmailInput.value.trim(),
    password: els.setupPasswordInput.value,
  };
  await api('/setup/bootstrap-admin', { method: 'POST', body: JSON.stringify(payload) });
  els.loginInput.value = payload.email;
  els.passwordInput.value = payload.password;
  els.setupPasswordInput.value = '';
  await refreshPublicSetupStatus();
  setLoginError('Администратор создан. Теперь можно войти.');
}

async function restoreSession() {
  if (!state.token) return;
  try {
    await api('/auth/session');
    await bootAuthenticated();
  } catch {
    setToken(null);
  }
}

async function initializePublicScreen() {
  try {
    await Promise.all([refreshServiceInfo(), refreshPublicSetupStatus()]);
  } catch (error) {
    setLoginError(`Не удалось проверить сервис: ${error.message}`);
  }
}

async function logout() {
  try {
    if (state.token) await api('/auth/logout', { method: 'POST' });
  } catch (_) {}
  if (state.uiRefreshTimer) {
    clearInterval(state.uiRefreshTimer);
    state.uiRefreshTimer = null;
  }
  state.showAllThreads = false;
  setToken(null);
  state.user = null;
  state.threads = [];
  state.messages = [];
  state.pendingFiles = [];
  state.pendingExistingFiles = [];
  state.userFiles = [];
  state.activeThreadId = null;
  state.jobs = [];
  state.activeJobId = null;
  state.showArchived = false;
  state.screen = 'chat';
  els.appShell.classList.add('hidden');
  els.loginScreen.classList.remove('hidden');
  updateArchiveToggleLabel();
  hideBanner();
}

async function createThread() {
  const data = await api('/threads', { method: 'POST', body: JSON.stringify({ title: 'Новый чат', preview: 'Новый чат' }) });
  await refreshThreads();
  await loadThread(data.thread.id);
  hideBanner();
}

async function renameThread() {
  const thread = getActiveThread();
  if (!thread) return;
  const title = window.prompt('Новое имя чата', thread.title);
  if (!title) return;
  await api(`/threads/${thread.id}`, { method: 'PATCH', body: JSON.stringify({ title, version: thread.version ?? 1 }) });
  await refreshThreads();
  await loadThread(thread.id);
  showInfoBanner('Название чата обновлено.');
}

async function archiveThread() {
  const thread = getActiveThread();
  if (!thread) return;
  await api(`/threads/${thread.id}`, { method: 'PATCH', body: JSON.stringify({ archived: !thread.archived, version: thread.version ?? 1 }) });
  await refreshThreads();
  if (state.activeThreadId) await loadThread(state.activeThreadId);
  showInfoBanner(thread.archived ? 'Чат возвращён из архива.' : 'Чат отправлен в архив.');
}

async function sendMessage() {
  const textValue = els.promptInput.value.trim();
  const files = state.pendingFiles || [];
  const existingFiles = state.pendingExistingFiles || [];
  if (!textValue && !files.length && !existingFiles.length) return;
  if (!state.activeThreadId) await createThread();
  const optimisticAttachments = [
    ...files.map(file => ({ original_name: file.name, mime_type: file.type || 'file', size_bytes: file.size || 0 })),
    ...existingFiles.map(file => ({ original_name: file.original_name, mime_type: file.mime_type || 'file', size_bytes: file.size_bytes || 0, text_extracted: file.text_extracted, extraction_note: file.extraction_note, preview_excerpt: file.preview_text?.slice(0, 220), reused: true })),
  ];
  const pendingMeta = optimisticAttachments.length ? { attachments: optimisticAttachments, user_text: textValue } : {};
  state.messages.push({ role: 'user', content: textValue || 'Файлы добавлены без отдельного текста.', meta: pendingMeta, created_at: new Date().toISOString() });
  state.messages.push({ role: 'assistant', content: '', typing: true, created_at: new Date().toISOString() });
  renderMessages('bottom');
  els.promptInput.value = '';
  state.isSending = true;
  updateComposerState();
  try {
    if (files.length || existingFiles.length) {
      const form = new FormData();
      form.append('content', textValue);
      files.forEach(file => form.append('files', file));
      existingFiles.forEach(file => form.append('existing_file_ids', String(file.id)));
      await api(`/threads/${state.activeThreadId}/messages`, { method: 'POST', body: form });
    } else {
      await api(`/threads/${state.activeThreadId}/messages`, { method: 'POST', body: JSON.stringify({ content: textValue }) });
    }
    state.pendingFiles = [];
    state.pendingExistingFiles = [];
    renderSelectedFiles();
    await Promise.all([refreshThreads(), loadThread(state.activeThreadId), refreshUserFiles()]);
    if (!state.user.onboarding_completed) await saveProfile({ onboarding_completed: true }, false);
    hideBanner();
  } finally {
    state.isSending = false;
    updateComposerState();
  }
}

async function sendQuickFeedback(messageId, useful) {
  const reasons = useful ? [] : (state.feedbackReasons.length ? [state.feedbackReasons[0]] : []);
  await api(`/messages/${messageId}/feedback`, {
    method: 'POST',
    body: JSON.stringify({ useful, reasons, comment: '' })
  });
  showBanner(useful ? 'Спасибо, отметила ответ как полезный.' : 'Приняла, отметила ответ как требующий доработки.', false);
}

function collectProfilePayload() {
  return {
    version: state.user?.version ?? 1,
    name: els.profileName.value.trim(),
    timezone: els.profileTimezone.value.trim(),
    language: els.profileLanguage.value.trim(),
    team: els.profileTeam.value.trim(),
    title: els.profileTitle.value.trim(),
    goals: els.profileGoals.value.trim(),
    style: `${currentOptionText(els.profileTone)}, ${currentOptionText(els.profileDepth)}, ${currentOptionText(els.profileMode)}`,
    constraints: els.profileConstraints.value.trim(),
    pinned: els.profilePinned.value.split('\n').map(item => item.trim()).filter(Boolean),
    assistant_profile: {
      tone: els.profileTone.value,
      answer_depth: els.profileDepth.value,
      interaction_mode: els.profileMode.value,
      about_user: els.profileAbout.value.trim(),
    }
  };
}

async function saveAdminChatNotice() {
  const payload = {
    enabled: els.adminChatNoticeEnabled?.value === '1',
    text: els.adminChatNoticeText?.value?.trim() || '',
  };
  const result = await api('/admin/chat-notice', { method: 'PATCH', body: JSON.stringify(payload) });
  state.admin.chatNotice = result.chat_notice;
  if (!state.bootstrap) state.bootstrap = {};
  state.bootstrap.chat_notice = result.chat_notice;
  renderChatPolicyBanner();
  if (els.adminChatNoticeStatus) els.adminChatNoticeStatus.textContent = 'Объявление сохранено.';
  showBanner('Текст объявления обновлён.', false);
}

async function saveProfile(extraPayload = null, showHint = true) {
  const payload = extraPayload || collectProfilePayload();
  const data = await api('/me', { method: 'PATCH', body: JSON.stringify(payload) });
  state.user = data.user;
  state.profileSummary = data.profile_summary;
  state.personalization = data.personalization;
  renderSidebarProfile();
  fillProfileForm();
  renderChatWelcome();
  if (showHint) {
    els.profileSaveHint.textContent = 'Профиль сохранён.';
    showBanner('Профиль обновлён.', false);
  }
}

function defaultJobDraft() {
  return {
    name: '',
    version: null,
    description: '',
    prompt_template: '',
    job_type: state.jobsMeta?.templates_order?.[0] || 'daily_brief',
    visibility: 'private',
    status: 'active',
    source_of_truth: 'local_jobs',
    deliver: 'origin',
    self_subscribe_enabled: false,
    self_subscribe_scope: 'visible_users',
    schedule_kind: 'daily',
    time_of_day: '09:00',
    timezone: state.user?.timezone || 'UTC',
    start_date: new Date().toISOString().slice(0, 10),
    days_of_week: ['mon'],
    parameters: {},
    access: [],
    recipients: [],
  };
}

function renderJobMetaControls() {
  if (!state.jobsMeta) return;
  els.jobTypeSelect.innerHTML = Object.entries(state.jobsMeta.templates || {}).map(([key, value]) => `<option value="${key}">${esc(value.label)}</option>`).join('');
  renderWeeklyDaySelector();
}

function renderWeeklyDaySelector() {
  els.jobWeeklyDays.innerHTML = WEEKDAYS.map(day => `<button type="button" class="chip ${state.jobDraft?.days_of_week?.includes(day) ? 'active' : ''}" data-day="${day}">${WEEKDAY_LABELS[day]}</button>`).join('');
  els.jobWeeklyDays.querySelectorAll('[data-day]').forEach(button => {
    button.addEventListener('click', () => {
      const day = button.dataset.day;
      const current = new Set(state.jobDraft.days_of_week || []);
      if (current.has(day)) current.delete(day);
      else current.add(day);
      state.jobDraft.days_of_week = Array.from(current);
      renderWeeklyDaySelector();
      updateJobSchedulePreview();
    });
  });
}

function templateFieldsForType(type) {
  return (state.jobsMeta?.templates?.[type]?.fields || []);
}

function renderTemplateFields() {
  const fields = templateFieldsForType(state.jobDraft.job_type);
  const values = state.jobDraft.parameters || {};
  els.jobTemplateFields.innerHTML = fields.map(field => {
    if (field.type === 'select') {
      return `
        <label class="field">
          <span>${esc(field.label)}</span>
          <select data-param="${field.key}">${(field.options || []).map(option => `<option value="${esc(option)}" ${values[field.key] === option ? 'selected' : ''}>${esc(option)}</option>`).join('')}</select>
        </label>
      `;
    }
    const tag = field.type === 'textarea' ? 'textarea' : 'input';
    if (tag === 'textarea') {
      return `<label class="field"><span>${esc(field.label)}</span><textarea data-param="${field.key}" placeholder="${esc(field.placeholder || '')}">${esc(values[field.key] || '')}</textarea></label>`;
    }
    return `<label class="field"><span>${esc(field.label)}</span><input data-param="${field.key}" value="${esc(values[field.key] || '')}" placeholder="${esc(field.placeholder || '')}" /></label>`;
  }).join('');
  els.jobTemplateFields.querySelectorAll('[data-param]').forEach(input => {
    input.addEventListener('input', () => {
      state.jobDraft.parameters[input.dataset.param] = input.value;
    });
  });
}

function renderAccessRows() {
  els.jobAccessList.innerHTML = '';
  const rows = state.jobDraft.access || [];
  if (!rows.length) {
    els.jobAccessList.innerHTML = '<div class="muted">Дополнительные участники пока не назначены.</div>';
    return;
  }
  rows.forEach((row, index) => {
    const wrapper = document.createElement('div');
    wrapper.className = 'access-row';
    wrapper.innerHTML = `
      <select data-access-user="${index}">${(state.jobsMeta.users || []).map(user => `<option value="${user.id}" ${Number(row.user_id) === Number(user.id) ? 'selected' : ''}>${esc(user.name)} · ${esc(user.email)}</option>`).join('')}</select>
      <select data-access-role="${index}"><option value="viewer" ${row.role === 'viewer' ? 'selected' : ''}>читатель</option></select>
      <button type="button" class="btn ghost small" data-access-remove="${index}">Удалить</button>
    `;
    els.jobAccessList.appendChild(wrapper);
  });
  els.jobAccessList.querySelectorAll('[data-access-user]').forEach(select => {
    select.addEventListener('change', () => state.jobDraft.access[Number(select.dataset.accessUser)].user_id = Number(select.value));
  });
  els.jobAccessList.querySelectorAll('[data-access-role]').forEach(select => {
    select.addEventListener('change', () => state.jobDraft.access[Number(select.dataset.accessRole)].role = select.value);
  });
  els.jobAccessList.querySelectorAll('[data-access-remove]').forEach(button => {
    button.addEventListener('click', () => {
      state.jobDraft.access.splice(Number(button.dataset.accessRemove), 1);
      renderAccessRows();
    });
  });
}

function renderRecipientRows() {
  els.jobRecipientList.innerHTML = '';
  const users = (state.jobsMeta?.users || []).filter(user => Number(user.id) !== Number(state.user?.id));
  const threads = (state.jobsMeta?.threads || []).filter(thread => Number(thread.id) !== Number(state.activeThreadId));
  if (users.length) {
    const title = document.createElement('div');
    title.className = 'muted';
    title.textContent = 'Пользователи: для каждого выбранного пользователя создаётся отдельный чат задачи.';
    els.jobRecipientList.appendChild(title);
    users.forEach(user => {
      const checked = (state.jobDraft.recipients || []).some(item => item.recipient_type === 'fixed_user' && String(item.target_value) === String(user.id));
      const row = document.createElement('label');
      row.className = 'list-row';
      row.innerHTML = `
        <div style="display:flex;gap:10px;align-items:flex-start;">
          <input type="checkbox" ${checked ? 'checked' : ''} data-recipient-user="${user.id}" style="width:auto;margin-top:3px;" />
          <div>
            <strong>${esc(user.name || user.email)}</strong>
            <div class="muted">${esc(user.email || 'без email')} · для пользователя будет создан отдельный чат задачи</div>
          </div>
        </div>
      `;
      els.jobRecipientList.appendChild(row);
    });
  }
  if (threads.length) {
    const title = document.createElement('div');
    title.className = 'muted';
    title.style.marginTop = users.length ? '12px' : '0';
    title.textContent = 'Чаты: можно выбрать исходный чат, а рассылка всё равно придёт в отдельный чат задачи владельца этого чата.';
    els.jobRecipientList.appendChild(title);
  }
  if (!users.length && !threads.length) {
    els.jobRecipientList.innerHTML += '<div class="muted" style="margin-top:10px;">Пока нет других пользователей или чатов, которые можно подключить к этой задаче.</div>';
    return;
  }
  threads.forEach(thread => {
    const checked = (state.jobDraft.recipients || []).some(item => item.recipient_type === 'fixed_thread' && String(item.target_value) === String(thread.id));
    const row = document.createElement('label');
    row.className = 'list-row';
    row.innerHTML = `
      <div style="display:flex;gap:10px;align-items:flex-start;">
        <input type="checkbox" ${checked ? 'checked' : ''} data-recipient-thread="${thread.id}" style="width:auto;margin-top:3px;" />
        <div>
          <strong>${esc(compactThreadTitle(thread))}</strong>
          <div class="muted">${thread.archived ? 'архивный' : 'активный'} чат · ${esc(thread.email || 'без владельца')} · при включении создаётся отдельный чат задачи для владельца этого чата</div>
        </div>
      </div>
    `;
    els.jobRecipientList.appendChild(row);
  });
  els.jobRecipientList.querySelectorAll('[data-recipient-user]').forEach(input => {
    input.addEventListener('change', () => {
      const userId = String(input.dataset.recipientUser);
      const user = (state.jobsMeta?.users || []).find(item => String(item.id) === userId);
      const current = state.jobDraft.recipients || [];
      if (input.checked) {
        if (!current.some(item => item.recipient_type === 'fixed_user' && String(item.target_value) === userId)) {
          current.push({ recipient_type: 'fixed_user', target_value: userId, label: user?.name || user?.email || `user:${userId}` });
        }
      } else {
        state.jobDraft.recipients = current.filter(item => !(item.recipient_type === 'fixed_user' && String(item.target_value) === userId));
      }
      renderRecipientRows();
    });
  });
  els.jobRecipientList.querySelectorAll('[data-recipient-thread]').forEach(input => {
    input.addEventListener('change', () => {
      const threadId = String(input.dataset.recipientThread);
      const thread = (state.jobsMeta?.threads || []).find(item => String(item.id) === threadId);
      const current = state.jobDraft.recipients || [];
      if (input.checked) {
        if (!current.some(item => item.recipient_type === 'fixed_thread' && String(item.target_value) === threadId)) {
          current.push({ recipient_type: 'fixed_thread', target_value: threadId, label: thread?.title || `chat:${threadId}` });
        }
      } else {
        state.jobDraft.recipients = current.filter(item => !(item.recipient_type === 'fixed_thread' && String(item.target_value) === threadId));
      }
      renderRecipientRows();
    });
  });
}

function updateJobSchedulePreview() {
  const kindMap = { daily: 'Каждый день', weekdays: 'По будням', weekly: 'Еженедельно', monthly: 'Ежемесячно' };
  const kind = state.jobDraft.schedule_kind;
  const weeklyDays = (state.jobDraft.days_of_week || []).map(day => WEEKDAY_LABELS[day] || day).join(', ');
  const extra = kind === 'weekly' ? ` (${weeklyDays || 'день не выбран'})` : '';
  els.jobWeeklyDays.classList.toggle('hidden', kind !== 'weekly');
  if (els.jobSelfSubscribeScopeSelect) {
    const enabled = Boolean(state.jobDraft.self_subscribe_enabled);
    els.jobSelfSubscribeEnabledSelect.value = enabled ? 'enabled' : 'disabled';
    els.jobSelfSubscribeScopeSelect.value = state.jobDraft.self_subscribe_scope || 'visible_users';
    els.jobSelfSubscribeScopeSelect.disabled = !enabled;
    if (els.jobSelfSubscribeHint) {
      els.jobSelfSubscribeHint.textContent = enabled
        ? (state.jobDraft.self_subscribe_scope === 'workspace'
          ? 'Любой активный пользователь рабочей области сможет сам подключить себе отдельный чат задачи для этой задачи.'
          : 'Самоподписка доступна только тем, кто уже видит задачу. Ручное назначение получателей при этом остаётся отдельным.')
        : 'Самоподписка выключена. Получателей добавляет только создатель или администратор.';
    }
  }
  if (els.jobCronDeliverSelect) {
    els.jobCronDeliverSelect.value = state.jobDraft.deliver || 'origin';
  }
  els.jobSchedulePreview.textContent = `${kindMap[kind]}${extra} в ${state.jobDraft.time_of_day} (${state.jobDraft.timezone}), старт с ${state.jobDraft.start_date}.`;
}

function fillJobModal() {
  const draft = state.jobDraft;
  const canSeeParams = state.user?.role === 'admin';
  if (document.getElementById('jobParamsCard')) document.getElementById('jobParamsCard').classList.toggle('hidden', !canSeeParams);
  if (document.getElementById('jobVisibilityCard')) document.getElementById('jobVisibilityCard').classList.remove('hidden');
  if (document.getElementById('jobAccessCard')) document.getElementById('jobAccessCard').classList.remove('hidden');
  els.jobNameInput.value = draft.name || '';
  els.jobTypeSelect.value = draft.job_type || 'daily_brief';
  els.jobDescriptionInput.value = draft.description || '';
  els.jobPromptInput.value = draft.prompt_template || '';
  els.jobVisibilitySelect.value = draft.visibility || 'private';
  els.jobStatusSelect.value = draft.status || 'active';
  if (els.jobSelfSubscribeEnabledSelect) {
    els.jobSelfSubscribeEnabledSelect.value = draft.self_subscribe_enabled ? 'enabled' : 'disabled';
  }
  if (els.jobSelfSubscribeScopeSelect) {
    els.jobSelfSubscribeScopeSelect.value = draft.self_subscribe_scope || 'visible_users';
  }
  if (els.jobCronDeliverSelect) {
    els.jobCronDeliverSelect.value = draft.deliver || 'origin';
  }
  els.jobScheduleKindSelect.value = draft.schedule_kind || 'daily';
  els.jobTimeInput.value = draft.time_of_day || '09:00';
  els.jobTimezoneInput.value = draft.timezone || (state.user?.timezone || 'UTC');
  els.jobStartDateInput.value = draft.start_date || new Date().toISOString().slice(0, 10);
  renderWeeklyDaySelector();
  renderTemplateFields();
  renderAccessRows();
  renderRecipientRows();
  updateJobSchedulePreview();
  applyJobModalMode();
}

function collectJobDraftFromModal() {
  state.jobDraft.name = els.jobNameInput.value.trim();
  state.jobDraft.job_type = els.jobTypeSelect.value;
  state.jobDraft.description = els.jobDescriptionInput.value.trim();
  state.jobDraft.prompt_template = els.jobPromptInput.value.trim();
  state.jobDraft.visibility = els.jobVisibilitySelect.value;
  state.jobDraft.status = els.jobStatusSelect.value;
  state.jobDraft.deliver = els.jobCronDeliverSelect?.value || state.jobDraft.deliver || 'origin';
  state.jobDraft.self_subscribe_enabled = els.jobSelfSubscribeEnabledSelect?.value === 'enabled';
  state.jobDraft.self_subscribe_scope = els.jobSelfSubscribeScopeSelect?.value || 'visible_users';
  state.jobDraft.schedule_kind = els.jobScheduleKindSelect.value;
  state.jobDraft.time_of_day = els.jobTimeInput.value;
  state.jobDraft.timezone = els.jobTimezoneInput.value.trim();
  state.jobDraft.start_date = els.jobStartDateInput.value;
  if (state.user?.role !== 'admin') state.jobDraft.parameters = {};
}

function openCreateJobModal() {
  state.editingJobId = null;
  state.jobDraft = defaultJobDraft();
  els.jobModalTitle.textContent = 'Новая задача';
  fillJobModal();
  els.jobModalBackdrop.classList.remove('hidden');
}

function openEditJobModal() {
  const job = getActiveJob();
  if (!job) return;
  state.editingJobId = job.id;
  state.jobDraft = {
    name: job.name,
    version: job.version ?? 1,
    description: job.description,
    prompt_template: job.prompt_template || '',
    job_type: job.job_type,
    visibility: job.visibility,
    status: job.status,
    source_of_truth: job.source_of_truth || 'local_jobs',
    deliver: job.deliver || job.parameters?.deliver || 'origin',
    self_subscribe_enabled: Boolean(job.self_subscribe_enabled),
    self_subscribe_scope: job.self_subscribe_scope || 'visible_users',
    schedule_kind: job.schedule_kind,
    time_of_day: job.time_of_day,
    timezone: job.timezone,
    start_date: job.start_date,
    days_of_week: [...(job.days_of_week || [])],
    parameters: { ...(job.parameters || {}) },
    access: [...(job.access || []).map(item => ({ user_id: item.user_id, role: item.role }))],
    recipients: [...(job.recipients || []).map(item => ({ recipient_type: item.recipient_type, target_value: item.target_value, label: item.label }))],
  };
  els.jobModalTitle.textContent = isHermesCronJob(job) ? 'Настройка cron-задачи' : 'Редактирование задачи';
  fillJobModal();
  els.jobModalBackdrop.classList.remove('hidden');
}

function closeJobModal() {
  els.jobModalBackdrop.classList.add('hidden');
}

async function saveJob() {
  collectJobDraftFromModal();
  if (!state.jobDraft.name) throw new Error('Нужно указать название задачи.');
  if (state.jobDraft.source_of_truth !== 'hermes_cron' && !state.jobDraft.prompt_template) throw new Error('Нужно указать текст задачи.');
  const payload = {
    name: state.jobDraft.name,
    version: state.jobDraft.version,
    description: state.jobDraft.description,
    prompt_template: state.jobDraft.prompt_template,
    job_type: state.jobDraft.job_type,
    visibility: state.jobDraft.visibility,
    status: state.jobDraft.status,
    self_subscribe_enabled: state.jobDraft.self_subscribe_enabled,
    self_subscribe_scope: state.jobDraft.self_subscribe_enabled ? state.jobDraft.self_subscribe_scope : 'disabled',
    schedule_kind: state.jobDraft.schedule_kind,
    time_of_day: state.jobDraft.time_of_day,
    timezone: state.jobDraft.timezone,
    start_date: state.jobDraft.start_date,
    days_of_week: state.jobDraft.days_of_week,
    parameters: state.jobDraft.parameters || {},
    access: state.jobDraft.access || [],
    recipients: state.jobDraft.recipients || [],
  };
  if (state.jobDraft.source_of_truth === 'hermes_cron') {
    payload.deliver = state.jobDraft.deliver || 'origin';
  }
  const path = state.editingJobId ? `/jobs/${state.editingJobId}` : '/jobs';
  const method = state.editingJobId ? 'PATCH' : 'POST';
  const data = await api(path, { method, body: JSON.stringify(payload) });
  closeJobModal();
  await refreshJobs();
  if (data.job?.id) await loadJob(data.job.id, true);
  if (state.user?.role === 'admin') await refreshAdmin();
}

async function runActiveJob() {
  const job = getActiveJob();
  if (!job) return;
  await api(`/jobs/${job.id}/run`, { method: 'POST' });
  await loadJob(job.id, false);
  if (state.user?.role === 'admin') await refreshAdmin();
  showInfoBanner('Запуск задачи отправлен.');
}

async function toggleActiveJobStatus() {
  const job = getActiveJob();
  if (!job) return;
  const nextStatus = job.status === 'paused' ? 'active' : 'paused';
  await api(`/jobs/${job.id}`, { method: 'PATCH', body: JSON.stringify({ status: nextStatus, version: job.version ?? 1 }) });
  await loadJob(job.id, false);
  if (state.user?.role === 'admin') await refreshAdmin();
  showInfoBanner(nextStatus === 'paused' ? 'Задача поставлена на паузу.' : 'Задача возобновлена.');
}

async function toggleSubscription() {
  const job = getActiveJob();
  if (!job) return;
  const subscribed = Boolean(job.is_subscribed);
  await api(`/jobs/${job.id}/${subscribed ? 'unsubscribe' : 'subscribe'}`, { method: 'POST' });
  await loadJob(job.id, false);
  if (state.user?.role === 'admin') await refreshAdmin();
  showInfoBanner(subscribed ? 'Рассылка отключена.' : 'Рассылка подключена.');
}

async function guarded(fn) {
  try {
    hideBanner();
    await fn();
  } catch (error) {
    showBanner(`Ошибка: ${error.message}`, true);
  }
}

els.navButtons.forEach(button => {
  button.addEventListener('click', () => {
    switchScreen(button.dataset.screen);
    if (button.dataset.screen === 'admin') guarded(refreshAdmin);
    if (button.dataset.screen === 'jobs') guarded(refreshJobs);
    if (button.dataset.screen === 'profile') setProfileSection(state.profileSection || 'identity');
  });
});

els.adminSelectAllUsersBtn?.addEventListener('click', () => {
  setAdminUserSelection(state.admin.users.map(user => user.id));
  renderAdmin();
});
els.adminClearUserSelectionBtn?.addEventListener('click', () => {
  setAdminUserSelection([]);
  renderAdmin();
});
els.adminBulkInactiveUsersBtn?.addEventListener('click', () => guarded(() => bulkUpdateAdminUsers('inactive')));
els.adminBulkDeleteUsersBtn?.addEventListener('click', () => guarded(() => bulkUpdateAdminUsers('deleted')));

els.loginBtn.addEventListener('click', () => guarded(login));

async function fillAdminImportTemplate() {
  const template = state.admin.sources?.import?.template_csv || '';
  els.adminImportCsv.value = template;
  els.adminImportStatus.textContent = 'Шаблон подставлен.';
}

async function loadAdminUserDetail(userId) {
  if (!userId) {
    resetAdminUserForm();
    state.admin.userHistory = [];
    renderAdminUserHistory();
    return;
  }
  const [userData, historyData] = await Promise.all([
    api(`/admin/users/${userId}`),
    api(`/admin/users/${userId}/history`),
  ]);
  state.admin.userHistory = historyData.history || [];
  fillAdminUserForm(userData.user);
  renderAdminUserHistory();
}

async function saveAdminUser() {
  const payload = collectAdminUserPayload();
  const isEdit = els.adminUserFormMode.value === 'edit' && state.admin.editingUserId;
  const path = isEdit ? `/admin/users/${state.admin.editingUserId}` : '/admin/users';
  const method = isEdit ? 'PATCH' : 'POST';
  const result = await api(path, { method, body: JSON.stringify(payload) });
  els.adminUserStatus.textContent = isEdit
    ? `Пользователь обновлён: ${result.user.email} · версия ${result.user.version ?? 1}`
    : `Пользователь создан: ${result.user.email} · версия ${result.user.version ?? 1}`;
  await refreshAdmin();
  await loadAdminUserDetail(String(result.user.id));
  showBanner(isEdit ? 'Пользователь обновлён.' : 'Пользователь создан.', false);
}

async function loadReferenceItemHistory(datasetKey, itemKey) {
  const historyData = await api(`/admin/reference-data/${datasetKey}/items/${encodeURIComponent(itemKey)}/history`);
  state.admin.referenceHistory[`${datasetKey}::${itemKey}`] = historyData.history || [];
  if (els.adminReferenceStatus) {
    els.adminReferenceStatus.textContent = `История загружена: ${datasetKey} / ${itemKey}`;
  }
  renderReferenceDetail(datasetKey);
}

async function saveReferenceItem(datasetKey) {
  const itemKey = normalizeText(els.adminReferenceItemKeyInput?.value || '');
  const label = normalizeText(els.adminReferenceItemLabelInput?.value || '');
  const sortOrder = Number(els.adminReferenceItemSortOrderInput?.value || 0);
  const status = els.adminReferenceItemStatusSelect?.value || 'active';
  if (!itemKey || !label) {
    throw new Error('Нужны ключ элемента и название');
  }
  const dataset = state.admin.references?.[datasetKey] || {};
  const existing = (dataset.items || []).find(item => item.item_key === itemKey);
  const payload = buildReferenceExtraPayload(datasetKey, itemKey, label, existing);
  payload.label = label;
  payload.sort_order = sortOrder;
  payload.status = status;
  payload.is_active = status === 'active';
  payload.deleted_at = status === 'deleted' ? '1' : null;
  if (!existing) payload.item_key = itemKey;
  const path = existing ? `/admin/reference-data/${datasetKey}/items/${encodeURIComponent(itemKey)}` : `/admin/reference-data/${datasetKey}/items`;
  const method = existing ? 'PATCH' : 'POST';
  const result = await api(path, { method, body: JSON.stringify(payload) });
  state.admin.references[datasetKey] = result.dataset;
  renderReferenceData();
  renderReferenceDetail(datasetKey);
  if (itemKey) await loadReferenceItemHistory(datasetKey, itemKey);
  const datasetLabel = referenceDatasetLabel(datasetKey);
  if (els.adminReferenceStatus) {
    els.adminReferenceStatus.textContent = existing ? `Элемент обновлён: ${datasetLabel} / ${label}` : `Элемент создан: ${datasetLabel} / ${label}`;
  }
  if (els.adminReferenceItemStatus) {
    els.adminReferenceItemStatus.textContent = existing ? `Элемент обновлён: ${label}` : `Элемент создан: ${label}`;
  }
  closeAdminReferenceItemCard();
  showBanner(existing ? `Справочник «${datasetLabel}» обновлён.` : `Элемент «${label}» добавлен.`, false);
}

async function importUsersFromCsv() {
  const csvText = els.adminImportCsv.value.trim();
  if (!csvText) {
    els.adminImportStatus.textContent = 'Сначала вставь CSV.';
    return;
  }
  const result = await api('/admin/users/import', {
    method: 'POST',
    body: JSON.stringify({ csv_text: csvText, default_password: 'temporary-pass-123' })
  });
  els.adminImportStatus.textContent = `Импорт завершён: создано ${result.created || 0}, обновлено ${result.updated || 0}.`;
  await refreshAdmin();
  showBanner('Импорт пользователей завершён.', false);
}
els.setupBtn.addEventListener('click', () => guarded(bootstrapAdmin));
els.logoutBtn.addEventListener('click', () => guarded(logout));
els.topbarProfileBtn?.addEventListener('click', () => switchScreen('profile'));
els.adminTemplateBtn?.addEventListener('click', () => guarded(fillAdminImportTemplate));
els.adminImportBtn?.addEventListener('click', () => guarded(importUsersFromCsv));
els.adminChatNoticeSaveBtn?.addEventListener('click', () => guarded(saveAdminChatNotice));
els.adminEventsApplyBtn?.addEventListener('click', () => guarded(applyAdminEventsFilter));
els.adminEventsResetBtn?.addEventListener('click', () => guarded(resetAdminEventsFilter));
els.adminEventsExportCsvBtn?.addEventListener('click', () => guarded(() => exportAdminEvents('csv')));
els.adminEventsExportJsonBtn?.addEventListener('click', () => guarded(() => exportAdminEvents('json')));
els.changePasswordBtn?.addEventListener('click', () => guarded(changePassword));
els.adminUserResetBtn?.addEventListener('click', resetAdminUserForm);
els.adminUserSaveBtn?.addEventListener('click', () => guarded(saveAdminUser));
els.adminUserFormMode?.addEventListener('change', () => {
  if (els.adminUserFormMode.value === 'create') resetAdminUserForm();
});
els.adminUserSelect?.addEventListener('change', () => guarded(() => loadAdminUserDetail(els.adminUserSelect.value)));
[els.adminUserTone, els.adminUserDepth, els.adminUserMode, els.adminUserAbout].forEach(el => el?.addEventListener('input', () => {
  els.adminUserStylePreview.textContent = adminStylePreviewText();
}));
document.addEventListener('click', event => {
  const createUserBtn = event.target.closest('#adminOpenCreateUserBtn');
  if (createUserBtn) {
    setAdminSection('users');
    resetAdminUserForm();
    openAdminUserCard('create');
    return;
  }
  const userEditBtn = event.target.closest('[data-user-edit]');
  if (userEditBtn) {
    setAdminSection('users');
    guarded(() => loadAdminUserDetail(userEditBtn.dataset.userEdit));
    return;
  }
  const refOpenBtn = event.target.closest('[data-ref-open]');
  if (refOpenBtn) {
    setAdminSection('references');
    renderReferenceDetail(refOpenBtn.dataset.refOpen);
    return;
  }
  const refCreateBtn = event.target.closest('[data-ref-create]');
  if (refCreateBtn) {
    setAdminSection('references');
    openAdminReferenceItemCard(refCreateBtn.dataset.refCreate);
    return;
  }
  const refSelectAllBtn = event.target.closest('[data-ref-select-all]');
  if (refSelectAllBtn) {
    const datasetKey = refSelectAllBtn.dataset.refSelectAll;
    const dataset = state.admin.references?.[datasetKey] || {};
    setAdminReferenceSelection(datasetKey, (dataset.items || []).map(item => item.item_key));
    renderReferenceDetail(datasetKey);
    return;
  }
  const refClearSelectionBtn = event.target.closest('[data-ref-clear-selection]');
  if (refClearSelectionBtn) {
    const datasetKey = refClearSelectionBtn.dataset.refClearSelection;
    setAdminReferenceSelection(datasetKey, []);
    renderReferenceDetail(datasetKey);
    return;
  }
  const refBulkInactiveBtn = event.target.closest('[data-ref-bulk-inactive]');
  if (refBulkInactiveBtn) {
    guarded(() => bulkUpdateReferenceItems(refBulkInactiveBtn.dataset.refBulkInactive, 'inactive'));
    return;
  }
  const refBulkDeleteBtn = event.target.closest('[data-ref-bulk-delete]');
  if (refBulkDeleteBtn) {
    guarded(() => bulkUpdateReferenceItems(refBulkDeleteBtn.dataset.refBulkDelete, 'deleted'));
    return;
  }
  const refEditBtn = event.target.closest('[data-ref-edit]');
  if (refEditBtn) {
    const [datasetKey, itemKey] = (refEditBtn.dataset.refEdit || '').split('::');
    const dataset = state.admin.references?.[datasetKey] || {};
    const item = (dataset.items || []).find(entry => entry.item_key === itemKey);
    if (!item) return;
    openAdminReferenceItemCard(datasetKey, item);
    if (els.adminReferenceStatus) {
      els.adminReferenceStatus.textContent = `Редактируется элемент: ${datasetKey} / ${itemKey}`;
    }
    return;
  }
  const refHistoryBtn = event.target.closest('[data-ref-history]');
  if (refHistoryBtn) {
    const [datasetKey, itemKey] = (refHistoryBtn.dataset.refHistory || '').split('::');
    guarded(() => loadReferenceItemHistory(datasetKey, itemKey));
    return;
  }
  const refSaveBtn = event.target.closest('[data-ref-save]');
  if (refSaveBtn) {
    guarded(() => saveReferenceItem(refSaveBtn.dataset.refSave));
    return;
  }
  const fileReuseBtn = event.target.closest('[data-file-reuse]');
  if (fileReuseBtn) queueExistingFile(fileReuseBtn.dataset.fileReuse);
});
els.newThreadBtn.addEventListener('click', () => guarded(createThread));
els.allThreadsBtn?.addEventListener('click', openThreadsModal);
els.refreshBtn.addEventListener('click', () => guarded(async () => {
  await refreshThreads();
  if (state.activeThreadId) await loadThread(state.activeThreadId);
  await refreshUserFiles();
  await refreshJobs();
  await refreshAdmin();
}));
els.closeThreadsModalBtn?.addEventListener('click', closeThreadsModal);
els.threadsModalBackdrop?.addEventListener('click', event => {
  if (event.target === els.threadsModalBackdrop) closeThreadsModal();
});
els.sendBtn.addEventListener('click', () => guarded(sendMessage));
els.attachFileBtn?.addEventListener('click', () => els.fileInput?.click());
els.fileInput?.addEventListener('change', () => {
  const incoming = Array.from(els.fileInput.files || []);
  const slotsLeft = Math.max(0, 5 - state.pendingExistingFiles.length);
  state.pendingFiles = [...state.pendingFiles, ...incoming].slice(0, slotsLeft);
  els.fileInput.value = '';
  renderSelectedFiles();
  updateComposerState();
});
els.promptInput?.addEventListener('input', updateComposerState);
els.promptInput?.addEventListener('keydown', event => {
  if (event.key !== 'Enter' || event.shiftKey) return;
  event.preventDefault();
  guarded(sendMessage);
});
els.profileFileSearch?.addEventListener('input', () => { state.fileFilterQuery = els.profileFileSearch.value; renderProfileFiles(); });
els.profileFileScopeFilter?.addEventListener('change', () => { state.fileFilterScope = els.profileFileScopeFilter.value; renderProfileFiles(); });
els.profileFileTypeFilter?.addEventListener('change', () => { state.fileFilterType = els.profileFileTypeFilter.value; renderProfileFiles(); });
els.adminChartGranularity?.addEventListener('change', () => guarded(async () => {
  const granularity = els.adminChartGranularity.value || 'day';
  state.admin.overviewTimeseries = await loadAdminOverviewTimeseries(granularity, { renderImmediately: true, keepBuckets: false });
  renderAdmin();
}));
els.profileTabs.forEach(button => button.addEventListener('click', () => setProfileSection(button.dataset.profileSection)));
els.scrollTopButtons.forEach(button => button.addEventListener('click', scrollMainToTop));
const contentScrollHost = els.appContent || window;
contentScrollHost.addEventListener('scroll', () => {
  updateChatScrollUi();
  pinChatIntroWithinScreen();
});
els.chatConversationScroll?.addEventListener('scroll', updateChatScrollUi);
window.addEventListener('resize', () => {
  updateChatScrollUi();
  pinChatIntroWithinScreen();
});
els.adminSectionTabs.forEach(button => button.addEventListener('click', () => setAdminSection(button.dataset.adminSection)));
els.adminOpenCreateUserBtn?.addEventListener('click', () => {
  resetAdminUserForm();
  openAdminUserCard('create');
});
els.adminCloseUserCardBtn?.addEventListener('click', closeAdminUserCard);
els.adminUserCard?.addEventListener('click', event => {
  if (event.target === els.adminUserCard) closeAdminUserCard();
});
els.adminCloseReferenceCardBtn?.addEventListener('click', closeAdminReferenceCard);
els.adminReferenceCard?.addEventListener('click', event => {
  if (event.target === els.adminReferenceCard) closeAdminReferenceCard();
});
els.adminCloseReferenceItemCardBtn?.addEventListener('click', closeAdminReferenceItemCard);
els.adminReferenceItemCard?.addEventListener('click', event => {
  if (event.target === els.adminReferenceItemCard) closeAdminReferenceItemCard();
});
els.adminReferenceItemSaveBtn?.addEventListener('click', () => guarded(() => saveReferenceItem(els.adminReferenceItemDatasetKey?.value || '')));
els.renameThreadBtn.addEventListener('click', () => guarded(renameThread));
els.archiveThreadBtn.addEventListener('click', () => guarded(archiveThread));
els.saveProfileBtn.addEventListener('click', () => guarded(() => saveProfile()));
[els.profileTone, els.profileDepth, els.profileMode, els.profileAbout].forEach(el => el.addEventListener('input', updateProfilePreview));

els.jobScopeFilter.addEventListener('change', () => guarded(async () => {
  state.jobScope = els.jobScopeFilter.value;
  await refreshJobs();
}));
els.jobSearchInput?.addEventListener('input', () => {
  state.jobSearchQuery = els.jobSearchInput.value || '';
  renderJobsList();
});
els.newJobBtn.addEventListener('click', openCreateJobModal);
els.closeJobModalBtn.addEventListener('click', closeJobModal);
els.saveJobBtn.addEventListener('click', () => guarded(saveJob));
els.jobTypeSelect.addEventListener('change', () => {
  state.jobDraft.job_type = els.jobTypeSelect.value;
  state.jobDraft.parameters = {};
  renderTemplateFields();
});
els.jobScheduleKindSelect.addEventListener('change', () => {
  state.jobDraft.schedule_kind = els.jobScheduleKindSelect.value;
  updateJobSchedulePreview();
});
els.jobSelfSubscribeEnabledSelect?.addEventListener('change', () => {
  state.jobDraft.self_subscribe_enabled = els.jobSelfSubscribeEnabledSelect.value === 'enabled';
  if (!state.jobDraft.self_subscribe_enabled) {
    state.jobDraft.self_subscribe_scope = 'disabled';
  } else if (!state.jobDraft.self_subscribe_scope || state.jobDraft.self_subscribe_scope === 'disabled') {
    state.jobDraft.self_subscribe_scope = 'visible_users';
  }
  updateJobSchedulePreview();
});
els.jobSelfSubscribeScopeSelect?.addEventListener('change', () => {
  state.jobDraft.self_subscribe_scope = els.jobSelfSubscribeScopeSelect.value || 'visible_users';
  updateJobSchedulePreview();
});
[els.jobTimeInput, els.jobTimezoneInput, els.jobStartDateInput].forEach(el => el.addEventListener('input', () => {
  collectJobDraftFromModal();
  updateJobSchedulePreview();
}));
els.addAccessBtn.addEventListener('click', () => {
  const firstUser = state.jobsMeta?.users?.[0];
  if (!firstUser) return;
  state.jobDraft.access.push({ user_id: firstUser.id, role: 'viewer' });
  renderAccessRows();
});

async function startApp() {
  await initializePublicScreen();
  await restoreSession();
}

guarded(startApp);
