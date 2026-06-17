import { chromium } from 'playwright';

const BACKEND = process.env.HERMES_WEB_BACKEND_API || `${process.env.HERMES_WEB_FRONTEND_BACKEND_BASE || `http://${process.env.HERMES_WEB_BACKEND_HOST || process.env.HERMES_WEB_BIND_HOST || '127.0.0.1'}:${process.env.HERMES_WEB_BACKEND_PORT || 8791}`}/api`;
const FRONTEND = process.env.HERMES_WEB_FRONTEND_URL || `http://${process.env.HERMES_WEB_FRONTEND_HOST || process.env.HERMES_WEB_BIND_HOST || '127.0.0.1'}:${process.env.HERMES_WEB_FRONTEND_PORT || 8793}/`;

const login = await fetch(`${BACKEND}/auth/login`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ email: 'admin@demo.local', password: 'demo123' }),
});
const body = await login.json();
if (!login.ok || !body.token) throw new Error(`login failed ${login.status} ${JSON.stringify(body)}`);

const browser = await chromium.launch({ headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage'] });
const page = await browser.newPage();
await page.addInitScript((t) => localStorage.setItem('hermes_web_mvp_token', t), body.token);
await page.goto(FRONTEND, { waitUntil: 'networkidle', timeout: 30000 });
await page.waitForTimeout(1500);

const openBtn = page.locator('button[aria-label="Open Chat"]');
if (await openBtn.count()) {
  await openBtn.click();
  await page.waitForTimeout(1200);
}

const snapshot = await page.evaluate(() => {
  const els = Array.from(document.querySelectorAll('input, textarea, button, [contenteditable="true"]'));
  return {
    body: document.body.innerText.slice(0, 2000),
    formEls: els.map((el) => ({
      tag: el.tagName,
      type: el.getAttribute('type'),
      cls: el.className,
      id: el.id,
      name: el.getAttribute('name'),
      placeholder: el.getAttribute('placeholder'),
      aria: el.getAttribute('aria-label'),
      text: (el.textContent || '').trim().slice(0, 120),
      value: 'value' in el ? String(el.value).slice(0, 120) : null,
    })).slice(0, 120),
    sidebarHtml: document.querySelector('.hermes-copilot-sidebar')?.innerHTML?.slice(0, 4000) || '',
  };
});
console.log(JSON.stringify(snapshot, null, 2));
await browser.close();
