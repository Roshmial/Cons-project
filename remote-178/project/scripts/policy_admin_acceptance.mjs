import { chromium } from 'playwright';

const FRONTEND = process.env.HERMES_WEB_FRONTEND_URL || `http://${process.env.HERMES_WEB_FRONTEND_HOST || process.env.HERMES_WEB_BIND_HOST || '127.0.0.1'}:${process.env.HERMES_WEB_FRONTEND_PORT || 8793}/`;
const BACKEND = process.env.HERMES_WEB_BACKEND_API || `${process.env.HERMES_WEB_FRONTEND_BACKEND_BASE || `http://${process.env.HERMES_WEB_BACKEND_HOST || process.env.HERMES_WEB_BIND_HOST || '127.0.0.1'}:${process.env.HERMES_WEB_BACKEND_PORT || 8791}`}/api`;
const LOGIN_EMAIL = process.env.HERMES_WEB_SMOKE_EMAIL || 'admin@demo.local';
const LOGIN_PASSWORD = process.env.HERMES_WEB_SMOKE_PASSWORD || 'demo123';
const SCREENSHOT = process.env.POLICY_ADMIN_SCREENSHOT || '/tmp/policy-admin-overview.png';

function assert(cond, message) {
  if (!cond) throw new Error(message);
}

async function loginApi() {
  const res = await fetch(`${BACKEND}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: LOGIN_EMAIL, password: LOGIN_PASSWORD }),
  });
  const body = await res.json();
  if (!res.ok || !body.token) throw new Error(`API login failed: ${res.status} ${JSON.stringify(body)}`);
  return body.token;
}

async function fetchPolicy(token) {
  const res = await fetch(`${BACKEND}/admin/dashboard-policy`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  const body = await res.json();
  if (!res.ok) throw new Error(`fetchPolicy failed: ${res.status} ${JSON.stringify(body)}`);
  return body;
}

async function savePolicy(token, payload) {
  const res = await fetch(`${BACKEND}/admin/dashboard-policy`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify(payload),
  });
  const body = await res.json();
  if (!res.ok) throw new Error(`savePolicy failed: ${res.status} ${JSON.stringify(body)}`);
  return body;
}

const token = await loginApi();
const initial = await fetchPolicy(token);
const initialPolicy = initial.dashboard_policy;

const browser = await chromium.launch({ headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage'] });
const page = await browser.newPage({ viewport: { width: 1440, height: 1400 } });
const events = [];
const responses = [];
page.on('console', (msg) => {
  const text = msg.text();
  if (/\[vite\] (connecting|connected)/.test(text)) return;
  if (/React DevTools/.test(text)) return;
  events.push(`console:${msg.type()}:${text}`);
});
page.on('pageerror', (err) => events.push(`pageerror:${err.message}`));
page.on('response', async (res) => {
  const url = res.url();
  if (!url.includes('/api/')) return;
  if (res.status() >= 400) {
    let body = '';
    try { body = (await res.text()).slice(0, 200); } catch {}
    responses.push(`http:${res.status()}:${url}:${body.replace(/\s+/g, ' ').trim()}`);
  }
});

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
  await page.keyboard.press('Escape').catch(() => {});
  await page.waitForTimeout(250);
}

try {
  await page.addInitScript(({ token }) => {
    window.localStorage.setItem('hermes_web_mvp_token', token);
    window.localStorage.setItem('hermes_web_mvp_ui_state', JSON.stringify({ screen: 'admin', adminSection: 'overview' }));
  }, { token });
  await page.goto(FRONTEND, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForFunction(() => !!document.querySelector('.app-layout'), { timeout: 60000 });

  await ensureNoModal(page);
  const adminNav = page.getByRole('button', { name: 'Управление' });
  await adminNav.click().catch(async () => {
    await page.evaluate(() => {
      const btn = [...document.querySelectorAll('button')].find((el) => (el.textContent || '').trim() === 'Управление');
      if (btn) btn.click();
    });
  });
  await page.waitForFunction(() => (document.body.textContent || '').includes('Административный обзор'), { timeout: 30000 });
  await ensureNoModal(page);
  await page.waitForFunction(() => !!document.querySelector('#adminDashboardSourceModeReact'), { timeout: 30000 });

  const beforeUi = await page.evaluate(() => {
    const mode = document.querySelector('#adminDashboardSourceModeReact')?.value || null;
    const defaultGlobal = document.querySelector('#adminDashboardDefaultGlobalSourceReact')?.value || null;
    const checkboxes = [...document.querySelectorAll('[data-source-key]')].map((input) => ({
      key: input.getAttribute('data-source-key'),
      checked: input.checked,
      label: input.closest('label')?.innerText?.replace(/\s+/g, ' ').trim() || '',
    }));
    const selectedCount = checkboxes.filter((item) => item.checked).length;
    const card = [...document.querySelectorAll('.panel-card')].find((el) => (el.textContent || '').includes('Политика источников'));
    const neighborTitles = [...document.querySelectorAll('.panel-card h3')].map((el) => (el.textContent || '').trim());
    const cardBox = card?.getBoundingClientRect();
    const sectionCards = [...document.querySelectorAll('.panel-card')].slice(0, 6).map((el) => ({
      title: el.querySelector('h3')?.textContent?.trim() || null,
      classes: el.className,
      box: el.getBoundingClientRect ? {
        width: Math.round(el.getBoundingClientRect().width),
        height: Math.round(el.getBoundingClientRect().height),
      } : null,
    }));
    const labels = [...document.querySelectorAll('.panel-card label')].map((el) => el.textContent?.replace(/\s+/g, ' ').trim() || '');
    return {
      mode,
      defaultGlobal,
      selectedCount,
      totalSources: checkboxes.length,
      selectedKeys: checkboxes.filter((item) => item.checked).map((item) => item.key),
      labels,
      neighborTitles,
      sectionCards,
      cardBox: cardBox ? { width: Math.round(cardBox.width), height: Math.round(cardBox.height) } : null,
      hasSaveButton: !![...document.querySelectorAll('button')].find((el) => {
        const text = (el.textContent || '').trim();
        return text.includes('Сохранить');
      }),
      hasPolicySection: (document.body.textContent || '').includes('Политика источников'),
      bodyText: (document.body.textContent || '').slice(0, 4000),
    };
  });

  assert(beforeUi.hasSaveButton, 'в UI нет кнопки сохранения policy');
  assert(beforeUi.hasPolicySection, 'в UI не виден блок политики источников');
  const emptyInventoryVisible = beforeUi.bodyText.includes('Источники пока не настроены') || beforeUi.bodyText.includes('нет коннекторов');
  assert(beforeUi.totalSources > 0 || emptyInventoryVisible, 'в UI нет ни источников, ни честного empty state для inventory');

  const targetMode = initialPolicy.source_mode === 'global_only' ? 'local_first' : 'global_only';
  await page.selectOption('#adminDashboardSourceModeReact', targetMode);
  await ensureNoModal(page);
  const savePolicyBtn = page.getByRole('button', { name: 'Сохранить настройки источников', exact: true });
  await savePolicyBtn.click().catch(async () => {
    await page.evaluate(() => {
      const btn = [...document.querySelectorAll('button')].find((el) => (el.textContent || '').trim() === 'Сохранить настройки источников');
      if (btn) btn.click();
    });
  });
  await page.waitForTimeout(1200);

  const afterSaveUi = await page.evaluate(() => ({
    notice: [...document.querySelectorAll('.global-banner, .muted, .small, .status-chip, .panel-card')].map((el) => el.textContent || '').join(' | ').slice(0, 4000),
    bodyText: (document.body.textContent || '').slice(0, 5000),
    mode: document.querySelector('#adminDashboardSourceModeReact')?.value || null,
    defaultGlobal: document.querySelector('#adminDashboardDefaultGlobalSourceReact')?.value || null,
    selectedKeys: [...document.querySelectorAll('[data-source-key]')].filter((input) => input.checked).map((input) => input.getAttribute('data-source-key')),
  }));

  const apiAfterSave = await fetchPolicy(token);
  assert(apiAfterSave.dashboard_policy.source_mode === targetMode, `backend не сохранил mode=${targetMode}`);
  assert(Array.isArray(apiAfterSave.dashboard_policy.allowed_sources) && apiAfterSave.dashboard_policy.allowed_sources.length > 0, 'backend вернул пустой allowed_sources после save');

  await page.reload({ waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForFunction(() => !!document.querySelector('.app-layout'), { timeout: 30000 });
  await page.getByRole('button', { name: 'Управление' }).click();
  await page.waitForFunction(() => (document.body.textContent || '').includes('Административный обзор'), { timeout: 30000 });
  await ensureNoModal(page);
  await page.waitForFunction(() => !!document.querySelector('#adminDashboardSourceModeReact'), { timeout: 30000 });

  const afterReloadUi = await page.evaluate(() => ({
    mode: document.querySelector('#adminDashboardSourceModeReact')?.value || null,
    selectedKeys: [...document.querySelectorAll('[data-source-key]')].filter((input) => input.checked).map((input) => input.getAttribute('data-source-key')),
    titleVisible: (document.body.textContent || '').includes('Политика источников'),
  }));
  assert(afterReloadUi.mode === targetMode, 'после reload UI не показал сохранённый mode');

  await savePolicy(token, initialPolicy);
  await page.reload({ waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForFunction(() => !!document.querySelector('.app-layout'), { timeout: 30000 });
  await ensureNoModal(page);
  const adminNavRestore = page.getByRole('button', { name: 'Управление' });
  await adminNavRestore.click().catch(async () => {
    await page.evaluate(() => {
      const btn = [...document.querySelectorAll('button')].find((el) => (el.textContent || '').trim() === 'Управление');
      if (btn) btn.click();
    });
  });
  await page.waitForFunction(() => (document.body.textContent || '').includes('Административный обзор'), { timeout: 30000 });
  await ensureNoModal(page);
  await page.waitForFunction(() => !!document.querySelector('#adminDashboardSourceModeReact'), { timeout: 30000 });

  const finalUi = await page.evaluate(() => {
    const card = [...document.querySelectorAll('.panel-card')].find((el) => (el.textContent || '').includes('Политика источников'));
    if (card) card.scrollIntoView({ block: 'center' });
    return {
      mode: document.querySelector('#adminDashboardSourceModeReact')?.value || null,
      defaultGlobal: document.querySelector('#adminDashboardDefaultGlobalSourceReact')?.value || null,
      selectedKeys: [...document.querySelectorAll('[data-source-key]')].filter((input) => input.checked).map((input) => input.getAttribute('data-source-key')),
      saveButtonText: [...document.querySelectorAll('button')].find((el) => (el.textContent || '').includes('Сохранить'))?.textContent?.trim() || null,
      cardHtml: card?.outerHTML?.slice(0, 8000) || null,
    };
  });

  await page.screenshot({ path: SCREENSHOT, fullPage: true });

  const finalApi = await fetchPolicy(token);
  assert(finalApi.dashboard_policy.source_mode === initialPolicy.source_mode, 'restore не вернул исходный source_mode');
  assert(JSON.stringify([...finalApi.dashboard_policy.allowed_sources].sort()) === JSON.stringify([...initialPolicy.allowed_sources].sort()), 'restore не вернул исходный набор allowed_sources');

  const hardErrors = [...events, ...responses.filter((item) => !item.includes('favicon'))];
  assert(!hardErrors.some((item) => item.startsWith('pageerror:')), `pageerror during acceptance: ${hardErrors.join(' | ')}`);
  assert(!hardErrors.some((item) => item.startsWith('http:5')), `5xx during acceptance: ${hardErrors.join(' | ')}`);

  console.log(JSON.stringify({
    ok: true,
    screenshot: SCREENSHOT,
    initialPolicy,
    beforeUi,
    changedTo: targetMode,
    toggledKey,
    afterSaveUi,
    afterReloadUi,
    finalUi,
    finalApiPolicy: finalApi.dashboard_policy,
    events,
    responses,
  }, null, 2));
} finally {
  await browser.close();
}
