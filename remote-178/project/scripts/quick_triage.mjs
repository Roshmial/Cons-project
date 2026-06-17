import { chromium } from 'playwright';

const FRONTEND = process.env.HERMES_WEB_FRONTEND_URL || `http://${process.env.HERMES_WEB_FRONTEND_HOST || process.env.HERMES_WEB_BIND_HOST || '127.0.0.1'}:${process.env.HERMES_WEB_FRONTEND_PORT || 8793}/`;
const BACKEND = process.env.HERMES_WEB_BACKEND_API || `${process.env.HERMES_WEB_FRONTEND_BACKEND_BASE || `http://${process.env.HERMES_WEB_BACKEND_HOST || process.env.HERMES_WEB_BIND_HOST || '127.0.0.1'}:${process.env.HERMES_WEB_BACKEND_PORT || 8791}`}/api`;
const LOGIN = {
  email: process.env.HERMES_WEB_SMOKE_EMAIL || 'admin@demo.local',
  password: process.env.HERMES_WEB_SMOKE_PASSWORD || 'demo123',
};

async function fetchJson(url, options = {}) {
  const res = await fetch(url, options);
  const text = await res.text();
  let json = null;
  try { json = text ? JSON.parse(text) : null; } catch {}
  return { ok: res.ok, status: res.status, json, text };
}

async function main() {
  const report = {
    started_at: new Date().toISOString(),
    frontend: {},
    backend: {},
    auth: {},
    bootstrap: {},
    browser_probe: {},
  };

  const frontendRes = await fetch(FRONTEND);
  report.frontend = {
    ok: frontendRes.ok,
    status: frontendRes.status,
    url: FRONTEND,
  };

  const health = await fetchJson(`${BACKEND}/health`);
  report.backend = {
    ok: health.ok,
    status: health.status,
    service_status: health.json?.status || null,
  };

  const login = await fetchJson(`${BACKEND}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(LOGIN),
  });
  const token = login.json?.token || null;
  report.auth = {
    ok: login.ok,
    status: login.status,
    token_received: Boolean(token),
    user_role: login.json?.user?.role || null,
  };

  const headers = token ? { Authorization: `Bearer ${token}` } : {};
  const bootstrap = token ? await fetchJson(`${BACKEND}/bootstrap`, { headers }) : { ok: false, status: 0, json: null };
  const me = token ? await fetchJson(`${BACKEND}/me`, { headers }) : { ok: false, status: 0, json: null };
  report.bootstrap = {
    ok: bootstrap.ok,
    status: bootstrap.status,
    help_articles: bootstrap.json?.help?.length || 0,
    reference_sets: Object.keys(bootstrap.json?.references || {}).length,
  };
  report.profile = {
    ok: me.ok,
    status: me.status,
    email: me.json?.user?.email || null,
    has_style_summary: Boolean(me.json?.user?.style_summary),
  };

  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  const events = [];
  page.on('console', msg => {
    if (msg.type() === 'error') events.push(`console:${msg.text()}`);
  });
  page.on('pageerror', err => events.push(`pageerror:${err.message}`));
  page.on('requestfailed', req => events.push(`requestfailed:${req.method()} ${req.url()} :: ${req.failure()?.errorText || 'failed'}`));
  await page.goto(FRONTEND, { waitUntil: 'networkidle' });
  const loginVisible = await page.locator('#loginScreen').isVisible();
  const title = await page.title();
  const topText = await page.locator('body').textContent();
  report.browser_probe = {
    ok: true,
    title,
    login_visible: loginVisible,
    has_login_copy: /Войти|Создать первого администратора|Hermes Web/i.test(topText || ''),
    events,
  };
  await browser.close();

  report.ok = [
    report.frontend.ok,
    report.backend.ok,
    report.auth.ok,
    report.bootstrap.ok,
    report.profile.ok,
    report.browser_probe.ok,
    report.browser_probe.events.length === 0,
  ].every(Boolean);

  console.log(JSON.stringify(report, null, 2));
}

main().catch(err => {
  console.error(JSON.stringify({ ok: false, error: err.message, stack: err.stack }, null, 2));
  process.exit(1);
});
