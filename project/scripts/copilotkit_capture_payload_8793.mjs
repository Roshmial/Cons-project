import { chromium } from 'playwright';

const BACKEND = process.env.HERMES_WEB_BACKEND_API || `${process.env.HERMES_WEB_FRONTEND_BACKEND_BASE || `http://${process.env.HERMES_WEB_BACKEND_HOST || process.env.HERMES_WEB_BIND_HOST || '127.0.0.1'}:${process.env.HERMES_WEB_BACKEND_PORT || 8791}`}/api`;
const FRONTEND = process.env.HERMES_WEB_FRONTEND_URL || `http://${process.env.HERMES_WEB_FRONTEND_HOST || process.env.HERMES_WEB_BIND_HOST || '127.0.0.1'}:${process.env.HERMES_WEB_FRONTEND_PORT || 8793}/`;

const login = await fetch(`${BACKEND}/auth/login`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ email: 'admin@demo.local', password: 'demo123' }),
});
const body = await login.json();
if (!login.ok || !body.token) throw new Error(`login failed: ${login.status} ${JSON.stringify(body)}`);

const browser = await chromium.launch({ headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage'] });
const page = await browser.newPage();
const events = [];
page.on('request', req => {
  if ((req.url().includes('/api/copilotkit') || req.url().includes('/copilotkit')) && req.method() === 'POST') {
    events.push({ type: 'request', url: req.url(), postData: req.postData() });
  }
});
page.on('response', async res => {
  if (res.url().includes('/api/copilotkit') || res.url().includes('/copilotkit')) {
    let text = '';
    try { text = (await res.text()).slice(0, 500).replace(/\s+/g, ' '); } catch {}
    events.push({ type: 'response', url: res.url(), status: res.status(), text });
  }
});
await page.addInitScript((t) => localStorage.setItem('hermes_web_mvp_token', t), body.token);
await page.goto(FRONTEND, { waitUntil: 'networkidle', timeout: 30000 });
await page.waitForTimeout(1500);
const openBtn = page.locator('button[aria-label="Open Chat"]');
if (await openBtn.count()) {
  await openBtn.click();
  await page.waitForTimeout(1000);
}
await page.locator('.copilotKitWindow textarea[placeholder="Type a message..."]').fill('Открой экран profile через доступное действие и кратко подтверди, что экран открыт.');
await page.evaluate(() => document.querySelector('.copilotKitWindow button[aria-label="Send"]')?.click());
await page.waitForTimeout(10000);
console.log(JSON.stringify(events, null, 2));
await browser.close();
