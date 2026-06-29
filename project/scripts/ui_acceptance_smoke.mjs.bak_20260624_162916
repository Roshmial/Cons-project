import { chromium } from 'playwright';
import fs from 'node:fs';

const FRONTEND = process.env.HERMES_WEB_FRONTEND_URL || `http://${process.env.HERMES_WEB_FRONTEND_HOST || process.env.HERMES_WEB_BIND_HOST || '127.0.0.1'}:${process.env.HERMES_WEB_FRONTEND_PORT || 8793}/`;
const FILE_PATH = process.env.HERMES_WEB_SMOKE_FILE || '/home/hermes/workspace/hermes-web-mvp/tmp/smoke-note.txt';
const LOGIN_EMAIL = process.env.HERMES_WEB_SMOKE_EMAIL || 'admin@demo.local';
const LOGIN_PASSWORD = process.env.HERMES_WEB_SMOKE_PASSWORD || 'demo123';
const STRUCTURED_PROMPT = 'Построй дашборд по локальной аналитике.';
const FILE_PROMPT = 'Проверь прикреплённый smoke-файл и ответь коротко.';

if (!fs.existsSync(FILE_PATH)) {
  fs.mkdirSync(FILE_PATH.split('/').slice(0, -1).join('/'), { recursive: true });
  fs.writeFileSync(FILE_PATH, 'Smoke file for Hermes Web MVP UI verification.\nAttached during browser smoke.\n');
}

function assert(cond, message) {
  if (!cond) throw new Error(message);
}

async function waitForApp(page) {
  await page.waitForLoadState('networkidle', { timeout: 60000 });
  await page.waitForFunction(() => !!document.querySelector('.app-layout'), { timeout: 60000 });
}

async function waitForNoPending(page, timeout = 120000) {
  await page.waitForFunction(() => !document.querySelector('.message-bubble.pending'), { timeout });
}

async function openNewChat(page) {
  await page.getByRole('button', { name: '+ Новый чат' }).click();
  await page.waitForTimeout(1000);
  const writeBtn = page.getByRole('button', { name: 'Написать сообщение' });
  if (await writeBtn.count()) {
    await writeBtn.click();
  }
  await page.waitForFunction(() => !!document.querySelector('textarea[placeholder="Напишите сообщение для текущего чата…"]'), { timeout: 30000 });
}

async function login(page) {
  await page.goto(FRONTEND, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.locator('input[name="email"]').fill(LOGIN_EMAIL);
  await page.locator('input[name="password"]').fill(LOGIN_PASSWORD);
  await page.getByRole('button', { name: 'Войти' }).click();
  await waitForApp(page);
}

const browser = await chromium.launch({ headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage'] });
const page = await browser.newPage();
const events = [];
const requestLog = [];
page.on('console', (msg) => {
  const text = msg.text();
  if (/\[vite\] (connecting|connected)/.test(text)) return;
  if (/React DevTools/.test(text)) return;
  events.push(`console:${msg.type()}:${text}`);
});
page.on('pageerror', (err) => events.push(`pageerror:${err.message}`));
page.on('response', async (res) => {
  if (/\/api\/threads\/\d+\/messages$/.test(res.url()) && res.request().method() === 'POST') {
    requestLog.push(`message-post:${res.status()}:${res.url()}`);
  }
  if (res.status() >= 400) {
    let body = '';
    try { body = (await res.text()).slice(0, 200); } catch {}
    requestLog.push(`http:${res.status()}:${res.url()}:${body.replace(/\s+/g, ' ').trim()}`);
  }
});

await login(page);

await openNewChat(page);
await page.locator('textarea[placeholder="Напишите сообщение для текущего чата…"]').fill(STRUCTURED_PROMPT);
await page.getByRole('button', { name: 'Отправить' }).click();
await page.waitForFunction(() => {
  const pending = document.querySelector('.message-bubble.pending');
  const clarifications = document.querySelectorAll('.clarification-action-btn').length;
  const dashboards = document.querySelectorAll('.dashboard-artifact').length;
  return !pending && (clarifications > 0 || dashboards > 0);
}, { timeout: 60000 });

const clarificationState = await page.evaluate(() => ({
  clarificationButtons: [...document.querySelectorAll('.clarification-action-btn')].map((el) => (el.textContent || '').trim()),
  dashboardCount: document.querySelectorAll('.dashboard-artifact').length,
  messageKinds: [...document.querySelectorAll('.message-bubble')].map((el) => el.className),
  bodyText: (document.body.textContent || '').slice(0, 3000),
}));
assert(clarificationState.clarificationButtons.length > 0 || clarificationState.dashboardCount > 0, 'structured dashboard flow не появился');

if (clarificationState.clarificationButtons.length > 0) {
  await page.locator('.clarification-action-btn').last().click();
  await page.waitForFunction(() => {
    const pending = document.querySelector('.message-bubble.pending');
    const dashboards = document.querySelectorAll('.dashboard-artifact').length;
    return !pending && dashboards > 0;
  }, { timeout: 60000 });
}

const dashboardState = await page.evaluate(() => ({
  dashboardCount: document.querySelectorAll('.dashboard-artifact').length,
  summaryBoxes: document.querySelectorAll('.dashboard-artifact .summary-box').length,
  sectionTitles: [...document.querySelectorAll('.dashboard-artifact h3, .dashboard-artifact h4, .dashboard-artifact .eyebrow')].map((el) => (el.textContent || '').trim()),
}));
assert(dashboardState.dashboardCount > 0, 'dashboard artifact не появился после structured reply');
assert(dashboardState.summaryBoxes > 0, 'в dashboard artifact нет summary-карточек');

await openNewChat(page);
await page.locator('textarea[placeholder="Напишите сообщение для текущего чата…"]').fill(FILE_PROMPT);
await page.locator('input[type="file"]').setInputFiles(FILE_PATH);
await page.waitForFunction(() => {
  const summary = document.querySelector('.composer-selection-summary')?.textContent || '';
  const filesLine = Array.from(document.querySelectorAll('.chat-composer-card .muted.small')).map((el) => el.textContent || '').join(' | ');
  return summary.includes('новых файлов 1') || filesLine.includes('smoke-note.txt');
}, { timeout: 10000 });
await page.getByRole('button', { name: 'Отправить' }).click();
await waitForNoPending(page);

const uploadState = await page.evaluate(() => ({
  bodyText: (document.body.textContent || '').slice(0, 2500),
  messageCount: document.querySelectorAll('.message-bubble').length,
}));
assert(uploadState.messageCount >= 2, 'чат после отправки файла не обновился');

await page.getByRole('button', { name: 'Профиль' }).click();
await page.waitForFunction(() => (document.body.textContent || '').includes('Профиль пользователя'), { timeout: 30000 });
await page.getByRole('button', { name: 'Файлы' }).click();
await page.waitForFunction(() => (document.body.textContent || '').includes('Файлы и повторное использование'), { timeout: 30000 });
const profileState = await page.evaluate(() => ({
  text: (document.body.textContent || '').slice(0, 2500),
  fileRows: document.querySelectorAll('.profile-file-row').length,
}));
assert(profileState.text.includes('smoke-note.txt'), 'загруженный файл не виден в разделе профиля');

await page.getByRole('button', { name: 'Управление' }).click();
await page.waitForFunction(() => (document.body.textContent || '').includes('Административный обзор'), { timeout: 30000 });
await page.getByRole('button', { name: 'Пользователи' }).click();
await page.waitForFunction(() => (document.body.textContent || '').includes('Пользователи'), { timeout: 30000 });
const adminState = await page.evaluate(() => ({
  usersTableRows: document.querySelectorAll('.table-row-users').length,
  text: (document.body.textContent || '').slice(0, 2500),
}));
assert(adminState.usersTableRows > 0, 'в админке не отрисовался список пользователей');

await page.getByRole('button', { name: 'Задачи' }).click();
await page.waitForFunction(() => (document.body.textContent || '').includes('Задачи Hermes'), { timeout: 30000 });
const jobsState = await page.evaluate(() => ({
  jobCards: document.querySelectorAll('.job-card').length,
  text: (document.body.textContent || '').slice(0, 2500),
}));
assert(jobsState.jobCards > 0, 'список задач пуст или не отрисовался');

const hardErrors = [...events, ...requestLog.filter((item) => /^http:(?!404:.*favicon)/.test(item) && !/^message-post:201:/.test(item))];
assert(requestLog.filter((item) => /^message-post:201:/.test(item)).length >= 3, 'ожидалось минимум 3 успешных POST /messages в smoke');
assert(!hardErrors.some((item) => item.startsWith('pageerror:')), `pageerror во время smoke: ${hardErrors.join(' | ')}`);
assert(!hardErrors.some((item) => item.startsWith('http:5')), `runtime вернул 5xx во время smoke: ${hardErrors.join(' | ')}`);

console.log(JSON.stringify({
  smoke: 'ok',
  clarificationState,
  dashboardState,
  uploadState: { messageCount: uploadState.messageCount },
  profileState: { fileRows: profileState.fileRows },
  adminState: { usersTableRows: adminState.usersTableRows },
  jobsState: { jobCards: jobsState.jobCards },
  requestLog,
  events,
}, null, 2));

await browser.close();
