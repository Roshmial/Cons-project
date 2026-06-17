import { chromium } from 'playwright';
const browser = await chromium.launch({ headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage'] });
const page = await browser.newPage();
const logs=[];
page.on('console', m => logs.push({type:m.type(), text:m.text()}));
page.on('pageerror', e => logs.push({type:'pageerror', text:String(e && e.stack || e)}));
const FRONTEND = process.env.HERMES_WEB_FRONTEND_URL || `http://${process.env.HERMES_WEB_FRONTEND_HOST || process.env.HERMES_WEB_BIND_HOST || '127.0.0.1'}:${process.env.HERMES_WEB_FRONTEND_PORT || 8793}/`;
await page.goto(FRONTEND, { waitUntil:'domcontentloaded', timeout:60000 });
await page.locator('input[name="email"]').fill('admin@demo.local');
await page.locator('input[name="password"]').fill('demo123');
await page.getByRole('button', { name: 'Войти' }).click();
await page.waitForLoadState('networkidle', { timeout: 60000 });
await page.waitForTimeout(2000);
const composer = page.locator('textarea, input[placeholder*="сообщ" i], textarea[placeholder*="сообщ" i]').first();
await composer.fill('Построй дашборд по локальной аналитике.');
await page.getByRole('button', { name: /отправить/i }).click();
await page.waitForTimeout(4000);
const before = await page.evaluate(() => ({
  clarificationCount: document.querySelectorAll('.clarification-action-btn').length,
  dashboardCount: document.querySelectorAll('.dashboard-artifact').length,
  body: document.body.textContent?.slice(0,4000) || '',
  root: document.querySelector('#root')?.innerHTML?.slice(0,10000) || ''
}));
if (before.clarificationCount > 0) {
  await page.locator('.clarification-action-btn').first().click();
  await page.waitForTimeout(5000);
}
const after = await page.evaluate(() => ({
  clarificationCount: document.querySelectorAll('.clarification-action-btn').length,
  dashboardCount: document.querySelectorAll('.dashboard-artifact').length,
  dashboardTitles: Array.from(document.querySelectorAll('.dashboard-artifact h3')).map(n => n.textContent?.trim()),
  body: document.body.textContent?.slice(0,5000) || ''
}));
console.log(JSON.stringify({ before, after, logs }, null, 2));
await browser.close();
