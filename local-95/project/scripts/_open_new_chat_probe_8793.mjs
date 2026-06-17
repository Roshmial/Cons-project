import { chromium } from 'playwright';
const browser = await chromium.launch({ headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage'] });
const FRONTEND = process.env.HERMES_WEB_FRONTEND_URL || `http://${process.env.HERMES_WEB_FRONTEND_HOST || process.env.HERMES_WEB_BIND_HOST || '127.0.0.1'}:${process.env.HERMES_WEB_FRONTEND_PORT || 8793}/`;
const page = await browser.newPage();
await page.goto(FRONTEND, { waitUntil: 'domcontentloaded', timeout: 60000 });
await page.locator('input[name="email"]').fill('admin@demo.local');
await page.locator('input[name="password"]').fill('demo123');
await page.getByRole('button', { name: 'Войти' }).click();
await page.waitForFunction(() => document.querySelector('.app-layout') && !document.querySelector('.auth-layout'), { timeout: 60000 });
await page.getByRole('button', { name: '+ Новый чат' }).click();
await page.waitForTimeout(1500);
const state = await page.evaluate(() => ({
  writeButtons: Array.from(document.querySelectorAll('button')).map(el => (el.textContent||'').trim()).filter(Boolean).filter(t => /Написать сообщение|Новый чат|Отправить/.test(t)),
  textareas: Array.from(document.querySelectorAll('textarea')).map(el => ({placeholder: el.getAttribute('placeholder'), value: el.value, rows: el.getAttribute('rows'), visible: !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length)})),
  activeThread: document.querySelector('.thread-item.active strong')?.textContent || null,
  body: document.body.textContent?.slice(0,2500) || ''
}));
console.log(JSON.stringify(state, null, 2));
await browser.close();
