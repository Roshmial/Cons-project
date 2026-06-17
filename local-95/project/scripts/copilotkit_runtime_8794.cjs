#!/usr/bin/env node
const express = require('express');
const OpenAI = require('openai');
const {
  CopilotRuntime,
  OpenAIAdapter,
  copilotRuntimeNodeExpressEndpoint,
} = require('@copilotkit/runtime');

const HOST = process.env.COPILOTKIT_RUNTIME_HOST || process.env.HERMES_WEB_BIND_HOST || '127.0.0.1';
const PORT = Number(process.env.COPILOTKIT_RUNTIME_PORT || 8794);
const MODEL = process.env.COPILOTKIT_RUNTIME_MODEL || 'hermes-agent';
const API_KEY = process.env.COPILOTKIT_RUNTIME_API_KEY || process.env.API_SERVER_KEY || '';
const BASE_URL = process.env.COPILOTKIT_RUNTIME_BASE_URL || process.env.HERMES_WEB_HERMES_API_BASE_URL || 'http://127.0.0.1:8642/v1';

if (!API_KEY) {
  console.error('Missing COPILOTKIT_RUNTIME_API_KEY/API_SERVER_KEY');
  process.exit(1);
}

const openai = new OpenAI({ apiKey: API_KEY, baseURL: BASE_URL });
const runtime = new CopilotRuntime();
const serviceAdapter = new OpenAIAdapter({ openai, model: MODEL });

const ALLOWED_ORIGINS = (process.env.COPILOTKIT_RUNTIME_ALLOWED_ORIGINS || '').split(',').map((item) => item.trim()).filter(Boolean);
const handler = copilotRuntimeNodeExpressEndpoint({
  endpoint: '/copilotkit',
  runtime,
  serviceAdapter,
  cors: { origin: ALLOWED_ORIGINS.length ? ALLOWED_ORIGINS : true },
});

const runtimeInfo = {
  version: `local-preview-${PORT}`,
  mode: 'sse',
  agents: {
    default: {
      description: `Локальный CopilotKit runtime preview для Hermes Web ${process.env.HERMES_WEB_FRONTEND_PORT || 'frontend'}`,
      capabilities: {},
    },
  },
  audioFileTranscriptionEnabled: false,
  a2uiEnabled: false,
  openGenerativeUIEnabled: false,
  telemetryDisabled: true,
};

const app = express();
app.use(express.json({ limit: '4mb' }));
app.use(express.urlencoded({ extended: true }));
app.get('/health', (_req, res) => {
  res.json({ status: 'ok', service: `copilotkit-runtime-${PORT}`, host: HOST, model: MODEL, base_url: BASE_URL });
});
app.get('/copilotkit/info', (_req, res) => {
  res.json(runtimeInfo);
});
app.use(handler);
app.listen(PORT, HOST, () => {
  console.log(`CopilotKit runtime listening on http://${HOST}:${PORT}/copilotkit`);
});
