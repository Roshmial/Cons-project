import { chromium } from 'playwright';

const FRONTEND = process.env.HERMES_WEB_FRONTEND_URL || `http://${process.env.HERMES_WEB_FRONTEND_HOST || process.env.HERMES_WEB_BIND_HOST || '127.0.0.1'}:${process.env.HERMES_WEB_FRONTEND_PORT || 8793}/`;
const BACKEND = process.env.HERMES_WEB_BACKEND_API || `${process.env.HERMES_WEB_FRONTEND_BACKEND_BASE || `http://${process.env.HERMES_WEB_BACKEND_HOST || process.env.HERMES_WEB_BIND_HOST || '127.0.0.1'}:${process.env.HERMES_WEB_BACKEND_PORT || 8791}`}/api`;
const FILE_PATH = '/home/hermes/workspace/hermes-web-mvp/tmp/smoke-note.txt';
const stamp = Date.now();
const chatTextUnique = `react-targeted-chat-${stamp}`;
const userEmail = `react-targeted-${stamp}@demo.local`;
const jobName = `react-targeted-job-${stamp}`;
const jobAlias = `React targeted alias ${stamp}`;

async function api(path, options = {}, token = '') {
  const headers = { ...(options.headers || {}) };
  if (!(options.body instanceof FormData) && !headers['Content-Type']) headers['Content-Type'] = 'application/json';
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(`${BACKEND}${path}`, { ...options, headers });
  const text = await res.text();
  const body = text ? JSON.parse(text) : {};
  if (!res.ok) throw new Error(`${path} -> ${res.status} ${text.slice(0, 300)}`);
  return body;
}

const login = await api('/auth/login', { method: 'POST', body: JSON.stringify({ email: 'admin@demo.local', password: 'demo123' }) });
const token = login.token;
const browser = await chromium.launch({ headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage'] });
const page = await browser.newPage();
const issues = [];
page.on('console', msg => { if (msg.type() === 'error') issues.push(`console:${msg.text()}`); });
page.on('pageerror', err => issues.push(`pageerror:${err.message}`));
page.on('response', async res => {
  if (res.status() >= 400) {
    let body = '';
    try { body = (await res.text()).slice(0, 200); } catch {}
    issues.push(`http:${res.status()}:${res.url()}:${body.replace(/\s+/g,' ').trim()}`);
  }
});

await page.addInitScript((t) => localStorage.setItem('hermes_web_mvp_token', t), token);
await page.goto(FRONTEND, { waitUntil: 'domcontentloaded', timeout: 30000 });
await page.waitForLoadState('networkidle').catch(() => {});

const results = {};

await page.getByRole('button', { name: 'Чаты' }).click();
await page.getByPlaceholder('Напишите сообщение для Hermes…').fill(chatTextUnique);
await page.setInputFiles('input[type="file"]', FILE_PATH);
await page.locator('button:has-text("Отправить")').click();
await page.waitForTimeout(3000);
const mainAfterChat = await page.locator('main').innerText();
results.chat = {
  user_message_visible: mainAfterChat.includes(chatTextUnique),
  file_visible: mainAfterChat.includes('smoke-note.txt')
};

await page.getByRole('button', { name: 'Профиль' }).click();
await page.waitForTimeout(1200);
const profileText = await page.locator('main').innerText();
results.profile = {
  title_visible: profileText.includes('Профиль пользователя'),
  file_present: profileText.includes('smoke-note.txt')
};

await page.getByRole('button', { name: 'Задачи' }).click();
await page.waitForTimeout(1200);
await page.getByRole('button', { name: '+ Новая задача' }).click();
await page.getByRole('textbox', { name: 'Название', exact: true }).fill(jobName);
await page.getByLabel('Описание').fill('Targeted React acceptance job');
await page.getByLabel('Текст задачи').last().fill('Reply with a short note.');
await page.getByRole('button', { name: 'Сохранить задачу' }).click();
await page.waitForTimeout(2200);
const jobsText = await page.locator('main').innerText();
const jobsApi = await api('/jobs?scope=all', {}, token);
const createdJob = (jobsApi.jobs || []).find((job) => job.name === jobName);
results.jobs_create = {
  visible_in_ui: jobsText.includes(jobName),
  visible_in_backend: Boolean(createdJob)
};
if (createdJob) {
  await page.getByRole('button', { name: jobName }).click();
  await page.waitForTimeout(700);
  await page.locator('#jobAliasInputReact').fill(jobAlias);
  await page.getByRole('button', { name: 'Сохранить название' }).click();
  await page.waitForTimeout(1200);
  const afterAlias = await api(`/jobs/${createdJob.id}`, {}, token);
  await page.getByRole('button', { name: 'Поставить на паузу' }).click();
  await page.waitForTimeout(1200);
  const paused = await api(`/jobs/${createdJob.id}`, {}, token);
  await page.getByRole('button', { name: 'Возобновить задачу' }).click();
  await page.waitForTimeout(1200);
  const resumed = await api(`/jobs/${createdJob.id}`, {}, token);
  results.jobs_update = {
    alias_saved: afterAlias.job.display_name === jobAlias,
    paused: paused.job.status === 'paused',
    resumed: resumed.job.status === 'active'
  };
}

await page.getByRole('button', { name: 'Управление' }).click();
await page.waitForTimeout(800);
await page.getByRole('button', { name: 'Пользователи' }).click();
await page.waitForTimeout(1200);
await page.getByLabel('Email').fill(userEmail);
await page.getByLabel('Пароль').fill('temporary-pass-123');
await page.getByLabel('Имя').fill('React Targeted User');
await page.getByRole('button', { name: 'Создать пользователя' }).last().click();
await page.waitForTimeout(2000);
const usersText = await page.locator('main').innerText();
const usersApi = await api('/admin/users', {}, token);
results.admin_users = {
  visible_in_ui: usersText.includes(userEmail),
  visible_in_backend: Boolean((usersApi.users || []).find((user) => user.email === userEmail))
};

await page.getByRole('button', { name: 'Операции' }).click();
await page.waitForTimeout(1200);
const operationsText = await page.locator('main').innerText();
results.admin_operations = {
  tab_opened: operationsText.includes('Операции') || operationsText.includes('Последние операции'),
  controls_visible: operationsText.includes('CSV') || operationsText.includes('JSON') || operationsText.includes('Применить')
};

await page.getByRole('button', { name: 'Справочники' }).click();
await page.waitForTimeout(1200);
const refsText = await page.locator('main').innerText();
results.admin_references = {
  tab_opened: refsText.includes('Справочники'),
  datasets_visible: refsText.includes('assistant_answer_depths') || refsText.includes('Параметры ответа')
};

console.log(JSON.stringify({ frontend: FRONTEND, results, issues }, null, 2));
await browser.close();
