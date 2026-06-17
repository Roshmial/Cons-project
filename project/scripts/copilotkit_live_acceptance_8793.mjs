import { chromium } from 'playwright';

const BACKEND = process.env.HERMES_WEB_BACKEND_API || `${process.env.HERMES_WEB_FRONTEND_BACKEND_BASE || `http://${process.env.HERMES_WEB_BACKEND_HOST || process.env.HERMES_WEB_BIND_HOST || '127.0.0.1'}:${process.env.HERMES_WEB_BACKEND_PORT || 8791}`}/api`;
const FRONTEND = process.env.HERMES_WEB_FRONTEND_URL || `http://${process.env.HERMES_WEB_FRONTEND_HOST || process.env.HERMES_WEB_BIND_HOST || '127.0.0.1'}:${process.env.HERMES_WEB_FRONTEND_PORT || 8793}/`;

function assert(cond, message) {
  if (!cond) throw new Error(message);
}

async function login() {
  const res = await fetch(`${BACKEND}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: 'admin@demo.local', password: 'demo123' }),
  });
  const body = await res.json();
  if (!res.ok || !body.token) throw new Error(`login failed: ${res.status} ${JSON.stringify(body)}`);
  return body.token;
}

async function waitForAssistantTurn(page, previousCount, timeout = 90000) {
  await page.waitForFunction(
    (count) => document.querySelectorAll('.copilotKitAssistantMessage').length > count,
    previousCount,
    { timeout }
  );
  await page.waitForTimeout(1200);
}

const token = await login();
const browser = await chromium.launch({ headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage'] });
const page = await browser.newPage();
const events = [];
page.on('console', msg => events.push(`console:${msg.type()}:${msg.text()}`));
page.on('pageerror', err => events.push(`pageerror:${err.message}`));
page.on('requestfailed', req => events.push(`requestfailed:${req.method()} ${req.url()} :: ${req.failure()?.errorText || 'failed'}`));
page.on('response', async (res) => {
  if (res.status() >= 400) {
    let body = '';
    try { body = (await res.text()).slice(0, 250).replace(/\s+/g, ' '); } catch {}
    events.push(`http:${res.status()}:${res.url()}:${body}`);
  }
});

await page.addInitScript((t) => localStorage.setItem('hermes_web_mvp_token', t), token);
await page.goto(FRONTEND, { waitUntil: 'networkidle', timeout: 30000 });
await page.waitForTimeout(2000);

const openBtn = page.locator('button[aria-label="Open Chat"]');
if (await openBtn.count()) {
  await openBtn.click();
  await page.waitForTimeout(1000);
}

const chatInput = page.locator('.copilotKitWindow textarea[placeholder="Type a message..."]');
const sendBtn = page.locator('.copilotKitWindow button[aria-label="Send"]');
assert(await chatInput.count(), 'copilot sidebar input not found');
assert(await sendBtn.count(), 'copilot sidebar send button not found');

async function ask(prompt) {
  const prev = await page.locator('.copilotKitAssistantMessage').count();
  await chatInput.fill(prompt);
  await sendBtn.click();
  await waitForAssistantTurn(page, prev, 120000);
}

await ask('Открой экран profile через доступное действие и кратко подтверди, что экран открыт.');
await page.waitForFunction(() => document.querySelector('#screenProfile') && !document.querySelector('#screenProfile').classList.contains('hidden'), { timeout: 30000 });

await ask('Вернись на экран chat и через действие prepare_chat_message подготовь в основном composer текст: Черновик сообщения от CopilotKit для smoke test. Не отправляй его.');
await page.waitForFunction(() => {
  const chat = document.querySelector('#screenChat');
  const composer = chat?.querySelector('textarea');
  return chat && !chat.classList.contains('hidden') && composer && composer.value.includes('Черновик сообщения от CopilotKit для smoke test.');
}, { timeout: 30000 });

const result = await page.evaluate(() => {
  const activeScreen = [...document.querySelectorAll('.screen')].find((el) => !el.classList.contains('hidden'))?.id || null;
  const composer = document.querySelector('#screenChat textarea');
  const assistantMessages = Array.from(document.querySelectorAll('.copilotKitAssistantMessage')).map((el) => (el.textContent || '').trim()).slice(-4);
  const userMessages = Array.from(document.querySelectorAll('.copilotKitUserMessage')).map((el) => (el.textContent || '').trim()).slice(-4);
  return {
    activeScreen,
    composerValue: composer?.value || '',
    assistantMessages,
    userMessages,
    sidebarTitle: document.querySelector('.copilotKitHeader div')?.textContent?.trim() || null,
  };
});

assert(result.activeScreen === 'screenChat', `expected active screenChat, got ${result.activeScreen}`);
assert(result.composerValue.includes('Черновик сообщения от CopilotKit для smoke test.'), 'composer text was not prepared by Copilot action');
assert(!events.length, `browser/runtime errors: ${events.join(' | ')}`);

console.log(JSON.stringify({ ok: true, result }, null, 2));
await browser.close();
