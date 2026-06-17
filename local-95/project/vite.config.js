import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const FRONTEND_HOST = process.env.HERMES_WEB_FRONTEND_HOST || process.env.HERMES_WEB_BIND_HOST || '127.0.0.1';
const FRONTEND_PORT = Number(process.env.HERMES_WEB_FRONTEND_PORT || 8793);
const BACKEND_BASE = process.env.HERMES_WEB_FRONTEND_BACKEND_BASE || `http://${process.env.HERMES_WEB_BACKEND_HOST || process.env.HERMES_WEB_BIND_HOST || '127.0.0.1'}:${process.env.HERMES_WEB_BACKEND_PORT || 8791}`;

function configureApiProxy(proxy) {
  proxy.on('error', (err, req, res) => {
    if (!res || res.headersSent) return;
    const body = JSON.stringify({
      error: 'frontend_proxy_upstream_unavailable',
      detail: 'Frontend proxy did not receive a valid API response from backend.',
    });
    res.writeHead(502, {
      'Content-Type': 'application/json; charset=utf-8',
      'Cache-Control': 'no-store',
      'Content-Length': Buffer.byteLength(body),
    });
    res.end(body);
  });
}

export default defineConfig({
  root: 'services/frontend-react',
  plugins: [react()],
  server: {
    host: FRONTEND_HOST,
    port: FRONTEND_PORT,
    strictPort: true,
    allowedHosts: true,
    proxy: {
      '/api': {
        target: BACKEND_BASE,
        changeOrigin: true,
        configure: configureApiProxy,
      },
    },
  },
  preview: {
    host: FRONTEND_HOST,
    port: FRONTEND_PORT,
    strictPort: true,
  },
  build: {
    outDir: '../../dist/frontend-react',
    emptyOutDir: true,
  },
});
