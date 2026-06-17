import { chromium } from 'playwright';
import fs from 'node:fs';

const FRONTEND = process.env.HERMES_WEB_FRONTEND_URL || `http://${process.env.HERMES_WEB_FRONTEND_HOST || process.env.HERMES_WEB_BIND_HOST || '127.0.0.1'}:${process.env.HERMES_WEB_FRONTEND_PORT || 8793}/`;
const BACKEND = process.env.HERMES_WEB_BACKEND_API || `${process.env.HERMES_WEB_FRONTEND_BACKEND_BASE || `http://${process.env.HERMES_WEB_BACKEND_HOST || process.env.HERMES_WEB_BIND_HOST || '127.0.0.1'}:${process.env.HERMES_WEB_BACKEND_PORT || 8791}`}/api`;
const FILE_PATH = process.env.HERMES_WEB_SMOKE_FILE || '/home/hermes/workspace/hermes-web-mvp-react-8793/tmp/smoke-note.txt';
const LOGIN_EMAIL = process.env.HERMES_WEB_SMOKE_EMAIL || 'acceptance@demo.local';
const LOGIN_PASSWORD = process.env.HERMES_WEB_SMOKE_PASSWORD || 'acceptance-pass-123';
const unique = `react-smoke-${Date.now()}`;
const uniqueEmail = `${unique}@demo.local`;
const uniqueJob = `${unique}-job`;
const uniqueJobDisplay = `React smoke job ${Date.now()}`;

if (!fs.existsSync(FILE_PATH)) {
  fs.mkdirSync(FILE_PATH.split('/').slice(0, -1).join('/'), { recursive: true });
  fs.writeFileSync(FILE_PATH, 'Smoke file for Hermes Web MVP UI verification.\nThis file is attached during browser smoke to verify local upload and profile file contour.\n');
}

function assert(cond, message) {
  if (!cond) throw new Error(message);
}

async function api(path, options = {}, token = '') {
  const headers = { ...(options.headers || {}) };
  if (!(options.body instanceof FormData) && !headers['Content-Type']) headers['Content-Type'] = 'application/json';
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(`${BACKEND}${path}`, { ...options, headers });
  const text = await res.text();
  let body = {};
  if (text) body = JSON.parse(text);
  if (!res.ok) throw new Error(`API ${path} failed: ${res.status} ${text.slice(0, 300)}`);
  return body;
}

async function ensureNoModal(page) {
  await page.evaluate(() => {
    const buttons = [...document.querySelectorAll('button')];
    const later = buttons.find((el) => (el.textContent || '').trim() === 'Позже');
    if (later) later.click();
    const close = buttons.find((el) => /Закрыть|Отмена|Понятно|OK|Ок/.test((el.textContent || '').trim()));
    if (close) close.click();
    const backdrop = document.querySelector('.modal-backdrop-react');
    if (backdrop && backdrop instanceof HTMLElement) backdrop.click();
  });
  await page.waitForTimeout(500);
}

async function clickButtonByText(page, text) {
  await page.waitForFunction((label) => [...document.querySelectorAll('button')].some((el) => (el.textContent || '').trim() === label), text, { timeout: 30000 });
  await page.evaluate((label) => {
    const btn = [...document.querySelectorAll('button')].find((el) => (el.textContent || '').trim() === label);
    if (btn) btn.click();
  }, text);
  await page.waitForTimeout(250);
}

async function waitForScreenText(page, text, timeout = 15000) {
  await page.waitForFunction((expected) => (document.querySelector('main')?.innerText || '').includes(expected), text, { timeout });
}

async function openAdminSection(page, section, expectedText) {
  await page.waitForFunction((target) => Boolean(document.querySelector(`[data-admin-section="${target}"]`)), section, { timeout: 15000 });
  await page.locator(`[data-admin-section="${section}"]`).click();
  await page.waitForFunction((target) => document.querySelector(`[data-admin-section="${target}"]`)?.classList.contains('active') || false, section, { timeout: 15000 });
  if (expectedText) {
    await waitForScreenText(page, expectedText, 15000);
  }
}

async function waitForJobStatus(jobId, token, expected, timeoutMs = 8000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    const state = await api(`/jobs/${jobId}`, {}, token);
    if (state?.job?.status === expected) return state.job;
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  const finalState = await api(`/jobs/${jobId}`, {}, token);
  return finalState.job;
}

const login = await api('/auth/login', { method: 'POST', body: JSON.stringify({ email: LOGIN_EMAIL, password: LOGIN_PASSWORD }) });
const token = login.token;

const browser = await chromium.launch({ headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage'] });
const page = await browser.newPage();
const events = [];
page.on('console', msg => events.push(`console:${msg.type()}:${msg.text()}`));
page.on('pageerror', err => events.push(`pageerror:${err.message}`));
page.on('response', async res => {
  if (res.status() >= 400) {
    let body = '';
    try { body = (await res.text()).slice(0, 200); } catch {}
    events.push(`http:${res.status()}:${res.url()}:${body.replace(/\s+/g, ' ').trim()}`);
  }
});

await page.addInitScript((t) => {
  localStorage.setItem('hermes_web_mvp_token', t);
  localStorage.setItem('hermes_web_mvp_ui_state', JSON.stringify({
    screen: 'chat',
    activeThreadId: null,
    activeJobId: null,
    adminSection: 'overview',
    profileSection: 'summary',
  }));
}, token);
await page.goto(FRONTEND, { waitUntil: 'domcontentloaded', timeout: 30000 });
await page.waitForLoadState('networkidle', { timeout: 30000 }).catch(() => {});
await ensureNoModal(page);

await clickButtonByText(page, 'Чаты');
await page.setInputFiles('input[type="file"]', FILE_PATH);
await page.getByPlaceholder('Напишите сообщение для текущего чата…').fill('Проверь React smoke и ответь коротко.');
await page.getByRole('button', { name: 'Отправить' }).click();
await page.waitForFunction(() => document.querySelector('main')?.innerText.includes('Проверь React smoke и ответь коротко.'), null, { timeout: 15000 });
const chatText = await page.locator('main').innerText();
assert(chatText.includes('Проверь React smoke и ответь коротко.'), 'react chat message not visible');
assert(chatText.includes('smoke-note.txt'), 'react uploaded file not visible in chat');

await clickButtonByText(page, 'Профиль');
await page.waitForTimeout(800);
let profileText = await page.locator('main').innerText();
assert(profileText.includes('Профиль пользователя'), 'react profile screen did not render');
await page.getByRole('button', { name: 'Файлы', exact: true }).click();
await page.waitForTimeout(800);
profileText = await page.locator('main').innerText();
assert(profileText.includes('smoke-note.txt'), 'react profile files list missing uploaded file');

await clickButtonByText(page, 'Задачи');
await page.waitForTimeout(1000);
await page.getByRole('button', { name: '+ Новая задача' }).click();
await page.getByRole('textbox', { name: 'Название', exact: true }).fill(uniqueJob);
await page.getByLabel('Описание').fill('Smoke-created React job');
const prompts = page.getByLabel('Текст задачи');
await prompts.last().fill('Скажи коротко, что это React smoke job.');
await page.getByRole('button', { name: 'Сохранить задачу' }).click();
await page.waitForFunction((jobName) => document.querySelector('main')?.innerText.includes(jobName), uniqueJob, { timeout: 15000 });
const jobsText = await page.locator('main').innerText();
assert(jobsText.includes(uniqueJob), 'created react job not visible');

const createdJob = await api('/jobs?scope=all', {}, token);
const created = (createdJob.jobs || []).find((job) => job.name === uniqueJob);
assert(created, 'created job missing in backend after react create');

const jobCard = page.locator('.job-card', { hasText: uniqueJob }).first();
await jobCard.scrollIntoViewIfNeeded();
await jobCard.click();
await page.waitForFunction((jobName) => {
  const cards = [...document.querySelectorAll('.job-card')];
  return cards.some((el) => (el.textContent || '').includes(jobName) && el.classList.contains('active'));
}, uniqueJob, { timeout: 15000 });
const activeJobCardClass = await jobCard.getAttribute('class');
assert((activeJobCardClass || '').includes('active'), 'react job card did not become active');
await page.evaluate(() => {
  const detailButtons = [...document.querySelectorAll('main button')];
  const btn = detailButtons.find((el) => (el.textContent || '').trim() === 'Приостановить задачу');
  if (btn) btn.click();
});
const paused = await waitForJobStatus(created.id, token, 'paused', 12000);
assert(paused.status === 'paused', `react pause failed: ${paused.status}`);
await page.waitForFunction(() => (document.querySelector('main')?.innerText || '').includes('Возобновить задачу'), { timeout: 12000 });

await page.evaluate(() => {
  const detailButtons = [...document.querySelectorAll('main button')];
  const btn = detailButtons.find((el) => (el.textContent || '').trim() === 'Возобновить задачу');
  if (btn) btn.click();
});
const resumed = await waitForJobStatus(created.id, token, 'active', 12000);
assert(resumed.status === 'active', `react resume failed: ${resumed.status}`);

await ensureNoModal(page);
await clickButtonByText(page, 'Управление');
await page.waitForTimeout(1200);
let adminText = await page.locator('main').innerText();
assert(adminText.includes('Административный обзор'), 'react admin screen missing');
assert(adminText.includes('Объявление в чате'), 'react admin overview incomplete');

await openAdminSection(page, 'users', 'Новый пользователь');
await page.evaluate(() => {
  const btn = [...document.querySelectorAll('main button')].find((el) => (el.textContent || '').trim() === 'Новый пользователь');
  if (btn) btn.click();
});
await page.waitForFunction(() => Boolean(document.querySelector('.modal-react')), { timeout: 15000 });
await page.getByLabel('Email').last().fill(uniqueEmail);
await page.getByLabel('Пароль').last().fill('temporary-pass-123');
await page.getByLabel('Имя').last().fill('React Smoke User');
await page.evaluate(() => {
  const btn = [...document.querySelectorAll('button')].find((el) => {
    const text = (el.textContent || '').trim();
    return text === 'Создать пользователя' || text === 'Сохранить пользователя';
  });
  if (btn) btn.click();
});
await waitForScreenText(page, uniqueEmail, 15000);
adminText = await page.locator('main').innerText();
assert(adminText.includes(uniqueEmail), 'react created admin user not visible');
const users = await api('/admin/users', {}, token);
const createdUser = (users.users || []).find((user) => user.email === uniqueEmail);
assert(createdUser, 'react created user missing in backend');

await openAdminSection(page, 'operations', 'Операции');
const operationsText = await page.locator('main').innerText();
assert(operationsText.includes('Последние операции') || operationsText.includes('Операции'), 'react operations tab did not open');

await openAdminSection(page, 'references', 'Справочники');
const refsText = await page.locator('main').innerText();
assert(refsText.includes('Справочники'), 'react references tab did not open');

await browser.close();
console.log(JSON.stringify({
  frontend: FRONTEND,
  login_email: LOGIN_EMAIL,
  created_user: uniqueEmail,
  created_job: uniqueJob,
  created_job_id: created.id,
  events,
  checks: {
    chat: true,
    profile: true,
    jobs_create: true,
    jobs_pause_resume: true,
    admin_user_create: true,
    admin_operations_tab: true,
    admin_references_tab: true
  }
}, null, 2));
