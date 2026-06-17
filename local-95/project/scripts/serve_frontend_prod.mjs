import http from 'node:http';
import { readFile, stat } from 'node:fs/promises';
import { createReadStream, existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const projectRoot = path.resolve(__dirname, '..');
const distRoot = path.join(projectRoot, 'dist', 'frontend-react');
const host = process.env.HERMES_WEB_FRONTEND_HOST || process.env.HERMES_WEB_BIND_HOST || '127.0.0.1';
const port = Number(process.env.HERMES_WEB_FRONTEND_PORT || 8803);
const backendBase = (process.env.HERMES_WEB_FRONTEND_BACKEND_BASE || `http://${process.env.HERMES_WEB_BACKEND_HOST || process.env.HERMES_WEB_BIND_HOST || '127.0.0.1'}:${process.env.HERMES_WEB_BACKEND_PORT || 8791}`).replace(/\/$/, '');

if (!existsSync(path.join(distRoot, 'index.html'))) {
  console.error(`Build artifact missing: ${path.join(distRoot, 'index.html')}`);
  process.exit(1);
}

const MIME = new Map([
  ['.html', 'text/html; charset=utf-8'],
  ['.js', 'application/javascript; charset=utf-8'],
  ['.css', 'text/css; charset=utf-8'],
  ['.json', 'application/json; charset=utf-8'],
  ['.svg', 'image/svg+xml'],
  ['.png', 'image/png'],
  ['.jpg', 'image/jpeg'],
  ['.jpeg', 'image/jpeg'],
  ['.webp', 'image/webp'],
  ['.woff', 'font/woff'],
  ['.woff2', 'font/woff2'],
  ['.ttf', 'font/ttf'],
]);

function sendJson(res, status, payload) {
  const body = JSON.stringify(payload);
  res.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Cache-Control': 'no-store',
    'Content-Length': Buffer.byteLength(body),
  });
  res.end(body);
}

async function collectBody(req) {
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  return Buffer.concat(chunks);
}

function copyHeaders(headers) {
  const result = {};
  for (const [key, value] of headers.entries()) {
    if (key.toLowerCase() === 'transfer-encoding') continue;
    result[key] = value;
  }
  return result;
}

async function proxyApi(req, res) {
  const targetUrl = `${backendBase}${req.url}`;
  const headers = { ...req.headers };
  delete headers.host;
  let body;
  if (!['GET', 'HEAD'].includes(req.method || 'GET')) {
    body = await collectBody(req);
  }
  try {
    const upstream = await fetch(targetUrl, {
      method: req.method,
      headers,
      body,
      redirect: 'manual',
    });
    const responseHeaders = copyHeaders(upstream.headers);
    const arrayBuffer = await upstream.arrayBuffer();
    const payload = Buffer.from(arrayBuffer);
    res.writeHead(upstream.status, responseHeaders);
    res.end(payload);
  } catch (error) {
    sendJson(res, 502, {
      error: 'frontend_proxy_upstream_unavailable',
      detail: 'Frontend proxy did not receive a valid API response from backend.',
    });
  }
}

function resolveAsset(urlPath) {
  const normalized = decodeURIComponent((urlPath || '/').split('?')[0]);
  const candidate = normalized === '/' ? '/index.html' : normalized;
  const resolved = path.resolve(distRoot, `.${candidate}`);
  if (!resolved.startsWith(distRoot)) return null;
  return resolved;
}

async function serveStatic(req, res) {
  const assetPath = resolveAsset(req.url || '/');
  const indexPath = path.join(distRoot, 'index.html');
  let finalPath = assetPath;
  try {
    if (!finalPath) throw new Error('bad path');
    const meta = await stat(finalPath);
    if (meta.isDirectory()) finalPath = indexPath;
  } catch {
    finalPath = indexPath;
  }

  try {
    const meta = await stat(finalPath);
    const ext = path.extname(finalPath).toLowerCase();
    const headers = {
      'Content-Type': MIME.get(ext) || 'application/octet-stream',
      'Content-Length': meta.size,
      'Cache-Control': finalPath.includes('/assets/') ? 'public, max-age=31536000, immutable' : 'no-cache',
    };
    if (req.method === 'HEAD') {
      res.writeHead(200, headers);
      res.end();
      return;
    }
    res.writeHead(200, headers);
    createReadStream(finalPath).pipe(res);
  } catch {
    sendJson(res, 404, { error: 'frontend_asset_not_found' });
  }
}

const server = http.createServer(async (req, res) => {
  if ((req.url || '').startsWith('/api')) {
    await proxyApi(req, res);
    return;
  }
  if (!['GET', 'HEAD'].includes(req.method || 'GET')) {
    sendJson(res, 405, { error: 'method_not_allowed' });
    return;
  }
  await serveStatic(req, res);
});

server.listen(port, host, () => {
  console.log(`Hermes Web prod frontend listening on http://${host}:${port} -> ${backendBase}`);
});
