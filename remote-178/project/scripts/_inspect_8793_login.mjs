import { chromium } from 'playwright';
const browser = await chromium.launch({ headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage'] });
const FRONTEND = process.env.HERMES_WEB_FRONTEND_URL || `http://${process.env.HERMES_WEB_FRONTEND_HOST || process.env.HERMES_WEB_BIND_HOST || '127.0.0.1'}:${process.env.HERMES_WEB_FRONTEND_PORT || 8793}/`;
const page = await browser.newPage();
await page.goto(FRONTEND, { waitUntil: 'domcontentloaded', timeout: 30000 });
await page.locator('input[name="email"]').fill('admin@demo.local');
await page.locator('input[name="password"]').fill('demo123');
await page.getByRole('button', { name: 'Войти' }).click();
await page.waitForTimeout(5000);
const data = await page.evaluate(() => ({
  body: document.body.textContent?.slice(0,3000) || '',
  rootHtml: document.querySelector('#root')?.innerHTML?.slice(0,8000) || '',
  classes: Array.from(document.querySelectorAll('*')).slice(0,200).map(el => ({tag:el.tagName, cls:el.className || '', id:el.id || ''})).filter(x=>x.cls||x.id),
  buttons: Array.from(document.querySelectorAll('button')).slice(0,50).map(el => ({text:(el.textContent||'').trim(), cls:el.className || ''})),
  errors: window.__lastError || null,
}));
console.log(JSON.stringify(data, null, 2));
await browser.close();
