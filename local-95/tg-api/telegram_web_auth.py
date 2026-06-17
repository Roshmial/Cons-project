import asyncio
import hashlib
import json
import os
import secrets
from urllib.parse import urljoin
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import requests
from flask import Blueprint, Response, jsonify, request
from telethon import TelegramClient
from telethon.errors import (
    PasswordHashInvalidError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    SessionPasswordNeededError,
)


SESSION_DIR = Path(__file__).resolve().parent / 'session'
STATE_PATH = Path(__file__).resolve().parent / 'auth_link_state.json'
DEFAULT_TTL_MINUTES = 20
MAX_TTL_MINUTES = 180


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _normalize_profile(profile: str) -> str:
    cleaned = ''.join(ch for ch in (profile or '').strip() if ch.isalnum() or ch in ('_', '-'))
    if not cleaned:
        raise ValueError('profile is required')
    return cleaned


def _resolve_session_path(profile: str) -> Path:
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    return SESSION_DIR / f'{profile}.session'


def _hash_phone(phone: str) -> str:
    return hashlib.sha256(phone.encode('utf-8')).hexdigest()[:12]


def _base_url() -> str:
    explicit = os.getenv('TG_AUTH_PUBLIC_BASE_URL', '').strip()
    if explicit:
        return explicit.rstrip('/')
    host = os.getenv('TG_API_HOST', '127.0.0.1')
    port = int(os.getenv('TG_API_PORT', '8001'))
    scheme = 'https' if host not in ('127.0.0.1', 'localhost') else 'http'
    return f'{scheme}://{host}:{port}'


def _is_loopback(remote_addr: Optional[str]) -> bool:
    return remote_addr in {'127.0.0.1', '::1', 'localhost'}


def _admin_request_allowed(req) -> bool:
    expected = os.getenv('TG_AUTH_ADMIN_TOKEN', '').strip()
    if expected:
        candidates = [
            req.headers.get('X-Auth-Token', ''),
            req.headers.get('Authorization', '').removeprefix('Bearer ').strip(),
        ]
        return expected in candidates
    return _is_loopback(req.remote_addr)


def _remote_base_url() -> str:
    for key in ('TG_AUTH_REMOTE_BASE_URL', 'TG_API_REMOTE_BASE_URL', 'TELEGRAM_API_BASE_URL'):
        value = os.getenv(key, '').strip()
        if value:
            return value.rstrip('/')
    return ''


def _remote_auth_enabled() -> bool:
    return bool(_remote_base_url())


def _remote_headers() -> Dict[str, str]:
    headers: Dict[str, str] = {'Content-Type': 'application/json'}
    token = os.getenv('TG_AUTH_ADMIN_TOKEN', '').strip()
    if token:
        headers['X-Auth-Token'] = token
    return headers


def _remote_request(method: str, path: str, payload: Optional[Dict[str, Any]] = None) -> tuple[Dict[str, Any], int]:
    base = _remote_base_url()
    if not base:
        raise RuntimeError('Remote Telegram auth base URL is not configured')
    url = urljoin(f'{base}/', path.lstrip('/'))
    response = requests.request(method.upper(), url, json=payload, headers=_remote_headers(), timeout=60)
    try:
        data = response.json()
    except Exception:
        data = {'error': response.text or 'remote_request_failed'}
    return data, response.status_code


@dataclass
class AuthSessionStore:
    path: Path

    def load(self) -> Dict[str, Dict[str, Any]]:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding='utf-8'))
        except json.JSONDecodeError:
            return {}

    def save(self, data: Dict[str, Dict[str, Any]]) -> None:
        _ensure_parent(self.path)
        tmp = self.path.with_suffix('.tmp')
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(tmp, self.path)
        os.chmod(self.path, 0o600)

    def cleanup(self, data: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        now = _now_utc()
        changed = False
        result: Dict[str, Dict[str, Any]] = {}
        for token, payload in data.items():
            expires_at = payload.get('expires_at')
            finished = payload.get('status') in {'authorized', 'expired', 'cancelled'}
            if expires_at and _parse_iso(expires_at) < now:
                payload['status'] = 'expired'
                finished = True
            if finished:
                finished_at = payload.get('finished_at') or payload.get('updated_at') or payload.get('created_at')
                if finished_at and _parse_iso(finished_at) < now - timedelta(days=1):
                    changed = True
                    continue
            result[token] = payload
        if changed:
            self.save(result)
        return result

    def list(self) -> Dict[str, Dict[str, Any]]:
        return self.cleanup(self.load())

    def get(self, token: str) -> Optional[Dict[str, Any]]:
        return self.list().get(token)

    def put(self, token: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        data = self.list()
        payload['updated_at'] = _iso(_now_utc())
        data[token] = payload
        self.save(data)
        return payload


store = AuthSessionStore(STATE_PATH)
auth_blueprint = Blueprint('telegram_web_auth', __name__)


HTML_PAGE = """<!doctype html>
<html lang='ru'>
<head>
  <meta charset='utf-8'>
  <meta name='viewport' content='width=device-width, initial-scale=1'>
  <title>Авторизация Telegram API</title>
  <style>
    body { font-family: system-ui, -apple-system, sans-serif; background:#f5f7fb; color:#1f2937; margin:0; }
    .wrap { max-width: 520px; margin: 0 auto; padding: 24px 16px 40px; }
    .card { background:#fff; border-radius:16px; padding:20px; box-shadow:0 8px 24px rgba(15,23,42,.08); }
    h1 { font-size: 24px; margin: 0 0 8px; }
    p { line-height: 1.45; }
    .muted { color:#6b7280; font-size:14px; }
    label { display:block; margin:14px 0 6px; font-weight:600; }
    input { width:100%; box-sizing:border-box; padding:12px 14px; border:1px solid #d1d5db; border-radius:10px; font-size:16px; }
    button { margin-top:16px; width:100%; border:0; border-radius:10px; padding:12px 14px; background:#2563eb; color:#fff; font-size:16px; font-weight:600; }
    button[disabled] { background:#93c5fd; }
    .box { margin-top:16px; padding:12px 14px; border-radius:10px; background:#eff6ff; color:#1d4ed8; }
    .error { background:#fef2f2; color:#b91c1c; }
    .ok { background:#ecfdf5; color:#047857; }
    .hidden { display:none; }
    .profile { font-weight:600; }
  </style>
</head>
<body>
  <div class='wrap'>
    <div class='card'>
      <h1>Авторизация Telegram API</h1>
      <p class='muted'>Авторизация в Telegram API для доступа к информации из закрытых чатов, в которых вы состоите.</p>
      <div id='statusBox' class='box hidden'></div>
      <div id='successBox' class='box ok hidden'>Спасибо. Авторизация пройдена, доступ через Telegram API подключён. Эту страницу можно закрыть.</div>
      <form id='phoneForm' class='hidden'>
        <label for='phone'>Номер телефона</label>
        <input id='phone' name='phone' placeholder='+79991234567' autocomplete='tel' />
        <button type='submit'>Получить код</button>
      </form>
      <form id='codeForm' class='hidden'>
        <label for='code'>Код из Telegram</label>
        <input id='code' name='code' placeholder='12345' inputmode='numeric' autocomplete='one-time-code' />
        <button type='submit'>Подтвердить код</button>
      </form>
      <form id='passwordForm' class='hidden'>
        <label for='password'>Пароль 2FA</label>
        <input id='password' name='password' type='password' placeholder='Пароль двухфакторной защиты' autocomplete='current-password' />
        <button type='submit'>Завершить вход</button>
      </form>
      <p class='muted'>Данные кода и пароля не показываются в ссылке и не возвращаются в браузер после успешного входа.</p>
    </div>
  </div>
<script>
const token = window.location.pathname.split('/').filter(Boolean).pop();
const statusBox = document.getElementById('statusBox');
const successBox = document.getElementById('successBox');
const phoneForm = document.getElementById('phoneForm');
const codeForm = document.getElementById('codeForm');
const passwordForm = document.getElementById('passwordForm');

function setMessage(text, kind='info') {
  successBox.classList.add('hidden');
  statusBox.textContent = text;
  statusBox.className = 'box ' + (kind === 'error' ? 'error' : kind === 'ok' ? 'ok' : '');
  statusBox.classList.remove('hidden');
}

function showStep(step) {
  statusBox.classList.remove('hidden');
  successBox.classList.add('hidden');
  phoneForm.classList.add('hidden');
  codeForm.classList.add('hidden');
  passwordForm.classList.add('hidden');
  if (step === 'phone') phoneForm.classList.remove('hidden');
  if (step === 'code') codeForm.classList.remove('hidden');
  if (step === 'password') passwordForm.classList.remove('hidden');
}

function showSuccess() {
  phoneForm.classList.add('hidden');
  codeForm.classList.add('hidden');
  passwordForm.classList.add('hidden');
  statusBox.classList.add('hidden');
  successBox.classList.remove('hidden');
}

async function api(path, payload) {
  const res = await fetch(path, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload || {})
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || 'request_failed');
  return data;
}

async function refresh() {
  const res = await fetch(`/auth/telegram/${token}/status`);
  const data = await res.json();
  if (!res.ok) {
    setMessage(data.error || 'Ссылка недоступна', 'error');
    return;
  }
  if (data.status === 'ready') {
    setMessage('Введите номер телефона, к которому привязан Telegram.', 'info');
    showStep('phone');
  } else if (data.status === 'code_sent') {
    setMessage('Код отправлен. Введите его из Telegram.', 'info');
    showStep('code');
  } else if (data.status === 'password_required') {
    setMessage('Нужен пароль двухфакторной защиты.', 'info');
    showStep('password');
  } else if (data.status === 'authorized') {
    showSuccess();
  } else {
    setMessage('Ссылка больше недоступна.', 'error');
  }
}

phoneForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  try {
    await api(`/auth/telegram/${token}/send_phone`, {phone: document.getElementById('phone').value.trim()});
    await refresh();
  } catch (err) {
    setMessage(err.message, 'error');
  }
});

codeForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  try {
    await api(`/auth/telegram/${token}/verify_code`, {code: document.getElementById('code').value.trim()});
    await refresh();
  } catch (err) {
    setMessage(err.message, 'error');
  }
});

passwordForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  try {
    await api(`/auth/telegram/${token}/verify_password`, {password: document.getElementById('password').value});
    await refresh();
  } catch (err) {
    setMessage(err.message, 'error');
  }
});

refresh();
</script>
</body>
</html>
"""


def _public_view(token: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    view = {
        'token': token,
        'profile': payload['profile'],
        'status': payload['status'],
        'expires_at': payload['expires_at'],
        'created_at': payload['created_at'],
        'updated_at': payload['updated_at'],
        'auth_url': f"{_base_url()}/auth/telegram/{token}",
    }
    if payload.get('proxy_mode'):
        view['proxy_mode'] = payload['proxy_mode']
    return view


def _bridge_payload(token: str, remote_payload: Dict[str, Any], remote_token: str) -> Dict[str, Any]:
    now_iso = _iso(_now_utc())
    return {
        'profile': remote_payload.get('profile', 'profile_private'),
        'status': remote_payload.get('status', 'ready'),
        'created_at': remote_payload.get('created_at', now_iso),
        'updated_at': remote_payload.get('updated_at', now_iso),
        'expires_at': remote_payload.get('expires_at', now_iso),
        'remote_token': remote_token,
        'proxy_mode': 'remote_auth',
    }


def _refresh_remote_status(token: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    remote_token = payload.get('remote_token')
    if not remote_token:
        return payload
    remote_payload, status = _remote_request('GET', f'/auth/telegram/{remote_token}/status')
    if status not in {200, 410}:
        raise ValueError(remote_payload.get('error') or 'Не удалось получить статус удалённой авторизации')
    refreshed = _bridge_payload(token, remote_payload, remote_token)
    if status == 410 and remote_payload.get('error'):
        refreshed['error'] = remote_payload.get('error')
    store.put(token, refreshed)
    return refreshed


def _proxy_auth_step(token: str, action: str, body: Dict[str, Any]) -> tuple[Dict[str, Any], int]:
    payload = _require_active_token(token)
    remote_token = payload.get('remote_token')
    if not remote_token:
        raise ValueError('Удалённый токен авторизации не найден')
    remote_payload, status = _remote_request('POST', f'/auth/telegram/{remote_token}/{action}', body)
    merged = _bridge_payload(token, remote_payload if isinstance(remote_payload, dict) else {}, remote_token)
    if isinstance(remote_payload, dict) and remote_payload.get('error'):
        merged['error'] = remote_payload['error']
    store.put(token, merged)
    response = _public_view(token, merged)
    if isinstance(remote_payload, dict) and remote_payload.get('error'):
        response['error'] = remote_payload['error']
    return response, status


def _require_active_token(token: str) -> Dict[str, Any]:
    payload = store.get(token)
    if not payload:
        raise ValueError('Ссылка не найдена')
    if payload.get('status') in {'expired', 'cancelled'}:
        raise ValueError('Ссылка больше недоступна')
    expires_at = payload.get('expires_at')
    if expires_at and _parse_iso(expires_at) < _now_utc():
        payload['status'] = 'expired'
        payload['finished_at'] = _iso(_now_utc())
        store.put(token, payload)
        raise ValueError('Срок действия ссылки истёк')
    return payload


async def _send_phone_async(payload: Dict[str, Any], phone: str, api_id: int, api_hash: str) -> Dict[str, Any]:
    client = TelegramClient(str(_resolve_session_path(payload['profile'])), api_id, api_hash)
    await client.connect()
    try:
        sent = await client.send_code_request(phone)
    finally:
        await client.disconnect()
    payload['status'] = 'code_sent'
    payload['phone'] = phone
    payload['phone_hash'] = _hash_phone(phone)
    payload['phone_code_hash'] = sent.phone_code_hash
    payload['code_sent_at'] = _iso(_now_utc())
    return payload


async def _verify_code_async(payload: Dict[str, Any], code: str, api_id: int, api_hash: str) -> Dict[str, Any]:
    client = TelegramClient(str(_resolve_session_path(payload['profile'])), api_id, api_hash)
    await client.connect()
    try:
        try:
            await client.sign_in(
                phone=payload['phone'],
                code=code,
                phone_code_hash=payload['phone_code_hash'],
            )
        except SessionPasswordNeededError:
            payload['status'] = 'password_required'
            return payload
    finally:
        await client.disconnect()
    payload['status'] = 'authorized'
    payload['finished_at'] = _iso(_now_utc())
    payload.pop('phone_code_hash', None)
    return payload


async def _verify_password_async(payload: Dict[str, Any], password: str, api_id: int, api_hash: str) -> Dict[str, Any]:
    client = TelegramClient(str(_resolve_session_path(payload['profile'])), api_id, api_hash)
    await client.connect()
    try:
        await client.sign_in(password=password)
    finally:
        await client.disconnect()
    payload['status'] = 'authorized'
    payload['finished_at'] = _iso(_now_utc())
    payload.pop('phone_code_hash', None)
    return payload


def register_telegram_web_auth(app, api_id: int, api_hash: str) -> None:
    @auth_blueprint.get('/auth/telegram/<token>')
    def auth_page(token: str) -> Response:
        payload = store.get(token)
        if not payload:
            return Response('Ссылка не найдена', status=404)
        return Response(HTML_PAGE, mimetype='text/html; charset=utf-8')

    @auth_blueprint.get('/auth/telegram/<token>/status')
    def auth_status(token: str):
        try:
            payload = store.get(token)
            if payload and payload.get('proxy_mode') == 'remote_auth':
                payload = _refresh_remote_status(token, payload)
                response = _public_view(token, payload)
                if payload.get('error'):
                    return jsonify(response | {'error': payload['error']}), 410
                return jsonify(response), 200
            payload = _require_active_token(token)
            return jsonify(_public_view(token, payload)), 200
        except ValueError as exc:
            payload = store.get(token)
            if payload:
                return jsonify(_public_view(token, payload) | {'error': str(exc)}), 410
            return jsonify({'error': str(exc)}), 404

    @auth_blueprint.post('/auth/telegram/admin/create_link')
    def create_link():
        if not _admin_request_allowed(request):
            return jsonify({'error': 'Недостаточно прав для создания ссылки'}), 403
        body = request.get_json(silent=True) or {}
        profile = _normalize_profile(body.get('profile', 'profile_private'))
        ttl_minutes = int(body.get('ttl_minutes', DEFAULT_TTL_MINUTES))
        ttl_minutes = max(1, min(ttl_minutes, MAX_TTL_MINUTES))
        if _remote_auth_enabled():
            remote_payload, status = _remote_request('POST', '/auth/telegram/admin/create_link', {'profile': profile, 'ttl_minutes': ttl_minutes})
            if status != 201:
                return jsonify(remote_payload), status
            remote_auth_url = str(remote_payload.get('auth_url', ''))
            remote_token = remote_auth_url.rstrip('/').split('/')[-1] if remote_auth_url else ''
            if not remote_token:
                return jsonify({'error': 'Удалённый сервис не вернул токен авторизации'}), 502
            token = secrets.token_urlsafe(24)
            payload = _bridge_payload(token, remote_payload, remote_token)
            store.put(token, payload)
            return jsonify(_public_view(token, payload)), 201
        token = secrets.token_urlsafe(24)
        now = _now_utc()
        payload = {
            'profile': profile,
            'status': 'ready',
            'created_at': _iso(now),
            'updated_at': _iso(now),
            'expires_at': _iso(now + timedelta(minutes=ttl_minutes)),
        }
        store.put(token, payload)
        return jsonify(_public_view(token, payload)), 201

    @auth_blueprint.post('/auth/telegram/<token>/send_phone')
    def send_phone(token: str):
        body = request.get_json(silent=True) or {}
        phone = str(body.get('phone', '')).strip()
        if not phone:
            return jsonify({'error': 'Нужен номер телефона'}), 400
        try:
            payload = store.get(token)
            if payload and payload.get('proxy_mode') == 'remote_auth':
                data, status = _proxy_auth_step(token, 'send_phone', {'phone': phone})
                return jsonify(data), status
            payload = _require_active_token(token)
            if payload.get('status') == 'authorized':
                return jsonify({'error': 'Эта ссылка уже использована. Создайте новую для повторной авторизации.'}), 409
            updated = asyncio.run(_send_phone_async(payload, phone, api_id, api_hash))
            store.put(token, updated)
            return jsonify(_public_view(token, updated)), 200
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400
        except Exception as exc:
            return jsonify({'error': f'Не удалось отправить код: {exc}'}), 500

    @auth_blueprint.post('/auth/telegram/<token>/verify_code')
    def verify_code(token: str):
        body = request.get_json(silent=True) or {}
        code = str(body.get('code', '')).strip()
        if not code:
            return jsonify({'error': 'Нужен код из Telegram'}), 400
        try:
            payload = store.get(token)
            if payload and payload.get('proxy_mode') == 'remote_auth':
                data, status = _proxy_auth_step(token, 'verify_code', {'code': code})
                return jsonify(data), status
            payload = _require_active_token(token)
            if payload.get('status') not in {'code_sent', 'password_required'}:
                return jsonify({'error': 'Сначала запросите код'}), 409
            updated = asyncio.run(_verify_code_async(payload, code, api_id, api_hash))
            store.put(token, updated)
            return jsonify(_public_view(token, updated)), 200
        except PhoneCodeInvalidError:
            return jsonify({'error': 'Неверный код'}), 400
        except PhoneCodeExpiredError:
            return jsonify({'error': 'Код истёк, запросите новый'}), 400
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400
        except Exception as exc:
            return jsonify({'error': f'Не удалось проверить код: {exc}'}), 500

    @auth_blueprint.post('/auth/telegram/<token>/verify_password')
    def verify_password(token: str):
        body = request.get_json(silent=True) or {}
        password = str(body.get('password', ''))
        if not password:
            return jsonify({'error': 'Нужен пароль 2FA'}), 400
        try:
            payload = store.get(token)
            if payload and payload.get('proxy_mode') == 'remote_auth':
                data, status = _proxy_auth_step(token, 'verify_password', {'password': password})
                return jsonify(data), status
            payload = _require_active_token(token)
            if payload.get('status') != 'password_required':
                return jsonify({'error': 'Пароль 2FA сейчас не требуется'}), 409
            updated = asyncio.run(_verify_password_async(payload, password, api_id, api_hash))
            store.put(token, updated)
            return jsonify(_public_view(token, updated)), 200
        except PasswordHashInvalidError:
            return jsonify({'error': 'Неверный пароль 2FA'}), 400
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400
        except Exception as exc:
            return jsonify({'error': f'Не удалось завершить вход: {exc}'}), 500

    @auth_blueprint.post('/auth/telegram/<token>/cancel')
    def cancel_link(token: str):
        payload = store.get(token)
        if not payload:
            return jsonify({'error': 'Ссылка не найдена'}), 404
        payload['status'] = 'cancelled'
        payload['finished_at'] = _iso(_now_utc())
        store.put(token, payload)
        return jsonify(_public_view(token, payload)), 200

    app.register_blueprint(auth_blueprint)
