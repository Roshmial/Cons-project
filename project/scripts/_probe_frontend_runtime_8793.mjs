import { chromium } from 'playwright';
const browser = await chromium.launch({ headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage'] });
const page = await browser.newPage();
const logs = [];
page.on('console', msg => logs.push({ type: msg.type(), text: msg.text() }));
page.on('pageerror', err => logs.push({ type: 'pageerror', text: String(err && err.stack || err) }));
page.on('response', async res => {
  const u = res.url();
  if (u.includes('/api/') || u.includes('/copilotkit')) logs.push({ type:'response', text: `${res.status()} ${u}` });
});
const FRONTEND = process.env.HERMES_WEB_FRONTEND_URL || `http://${process.env.HERMES_WEB_FRONTEND_HOST || process.env.HERMES_WEB_BIND_HOST || '127.0.0.1'}:${process.env.HERMES_WEB_FRONTEND_PORT || 8793}/`;
await page.goto(FRONTEND, { waitUntil: 'networkidle', timeout: 60000 });
await page.waitForTimeout(3000);
const data = await page.evaluate(() => ({
  href: location.href,
  title: document.title,
  rootHtml: (document.querySelector('#root')?.innerHTML || '').slice(0,8000),
  bodyText: (document.body?.textContent || '').slice(0,2000),
  inputs: Array.from(document.querySelectorAll('input,textarea,button')).slice(0,50).map(el => ({tag:el.tagName, type:el.getAttribute('type'), name:el.getAttribute('name'), text:(el.textContent||'').trim(), placeholder:el.getAttribute('placeholder'), cls:el.className||''})),
}));
console.log(JSON.stringify({ data, logs }, null, 2));
await browser.close();
