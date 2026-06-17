import os
import json
import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from flask import Flask, request, jsonify
import requests
from telethon import TelegramClient
from telethon.tl.types import Message, MessageEntityTextUrl, MessageEntityUrl
import yaml
from telegram_web_auth import register_telegram_web_auth

BASEDIR = os.path.dirname(os.path.abspath(__file__))
SESSION_DIR = os.path.join(BASEDIR, 'session')
os.makedirs(SESSION_DIR, exist_ok=True)
LEGACY_SESSION_ROOTS = [
    BASEDIR,
    os.path.join(os.path.dirname(BASEDIR), 'workspace', 'TG-API'),
]

def resolve_session_path(session_name: str) -> str:
    canonical_path = os.path.join(SESSION_DIR, f'{session_name}.session')
    if os.path.exists(canonical_path):
        return canonical_path
    for root in LEGACY_SESSION_ROOTS:
        candidate = os.path.join(root, f'{session_name}.session')
        if os.path.exists(candidate):
            return canonical_path
        nested_candidate = os.path.join(root, 'session', f'{session_name}.session')
        if os.path.exists(nested_candidate):
            return nested_candidate if nested_candidate == canonical_path else canonical_path
    return canonical_path

def cleanup_legacy_session_files(session_name: str) -> None:
    canonical_path = os.path.join(SESSION_DIR, f'{session_name}.session')
    archive_dir = os.path.join(SESSION_DIR, '_archive_legacy')
    os.makedirs(archive_dir, exist_ok=True)
    seen = set()
    for root in LEGACY_SESSION_ROOTS:
        for candidate in [
            os.path.join(root, f'{session_name}.session'),
            os.path.join(root, 'session', f'{session_name}.session'),
        ]:
            if candidate in seen:
                continue
            seen.add(candidate)
            if not os.path.exists(candidate) or os.path.abspath(candidate) == os.path.abspath(canonical_path):
                continue
            archived = os.path.join(archive_dir, f"{os.path.basename(os.path.dirname(candidate)) or 'root'}__{os.path.basename(candidate)}")
            if not os.path.exists(archived):
                os.replace(candidate, archived)

# Теперь CONFIG_PATH будет динамическим, убираем хардкод
# CONFIG_PATH = os.path.join(BASEDIR, 'channels.yml')  # старое

def load_telegram_credentials() -> Tuple[int, str]:
    """
    Загружает Telegram API credentials.

    Основной путь — переменные окружения TG_API_ID / TG_API_HASH.
    Для совместимости с текущим переносом на облачный сервер поддержан
    fallback на значения, уже заданные в login.py.
    """
    api_id_raw = os.getenv('TG_API_ID')
    api_hash = os.getenv('TG_API_HASH')

    if api_id_raw and api_hash:
        return int(api_id_raw), api_hash

    try:
        from login import API_ID as LOGIN_API_ID, API_HASH as LOGIN_API_HASH
        return int(LOGIN_API_ID), str(LOGIN_API_HASH)
    except Exception:
        return 0, ''


API_ID, API_HASH = load_telegram_credentials()

if not API_ID or not API_HASH:
    raise RuntimeError("TG_API_ID и TG_API_HASH must be set in environment")

app = Flask(__name__)
register_telegram_web_auth(app, API_ID, API_HASH)


def remote_export_base_url() -> str:
    for key in ('TG_API_REMOTE_BASE_URL', 'TELEGRAM_API_BASE_URL'):
        value = os.getenv(key, '').strip()
        if value:
            return value.rstrip('/')
    return ''


def remote_export_headers() -> Dict[str, str]:
    headers: Dict[str, str] = {}
    token = os.getenv('TG_AUTH_ADMIN_TOKEN', '').strip()
    if token:
        headers['X-Auth-Token'] = token
    return headers


def parse_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    if value == 'now':
        return datetime.now()
    return datetime.fromisoformat(value)


def load_config(config_name: str = 'channels') -> Dict[str, Any]:
    """
    Загружает конфиг по имени.
    Для локального запуска Hermes сначала ищет файлы рядом с app.py,
    затем сохраняет совместимость со старым Docker-путем /data/tg-history.
    """
    candidates = [
        os.path.join(BASEDIR, f"channels_{config_name}.yml"),
        os.path.join(BASEDIR, "channels.yml"),
        f"/data/tg-history/channels_{config_name}.yml",
        "/data/tg-history/channels.yml",
    ]

    config_path = next((path for path in candidates if os.path.exists(path)), None)
    if not config_path:
        raise FileNotFoundError(f"Config file not found. Checked: {candidates}")

    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f) or {}


def extract_message_links(msg: Message) -> List[str]:
    """Extract visible and hidden links from Telegram message entities."""
    text = msg.message or ''
    links: List[str] = []
    for entity in msg.entities or []:
        if isinstance(entity, MessageEntityTextUrl) and entity.url:
            links.append(entity.url)
        elif isinstance(entity, MessageEntityUrl):
            links.append(text[entity.offset:entity.offset + entity.length])

    result: List[str] = []
    seen = set()
    for link in links:
        clean = link.strip()
        if clean and clean not in seen:
            seen.add(clean)
            result.append(clean)
    return result


def serialize_message_reactions(msg: Message) -> List[Dict[str, Any]]:
    """Return compact reaction counters from Telegram message, if available."""
    reactions = getattr(msg, 'reactions', None)
    results = getattr(reactions, 'results', None) or []
    serialized: List[Dict[str, Any]] = []

    for item in results:
        reaction = getattr(item, 'reaction', None)
        label = getattr(reaction, 'emoticon', None)
        if label is None:
            document_id = getattr(reaction, 'document_id', None)
            label = f"custom:{document_id}" if document_id else str(reaction)

        serialized.append({
            'reaction': label,
            'count': getattr(item, 'count', None),
        })

    return serialized


def serialize_message_stats(msg: Message) -> Dict[str, Any]:
    """Return Telegram message metadata useful for monitoring and filtering."""
    replies = getattr(msg, 'replies', None)
    edit_date = getattr(msg, 'edit_date', None)
    return {
        'views': getattr(msg, 'views', None),
        'forwards': getattr(msg, 'forwards', None),
        'replies_count': getattr(replies, 'replies', None) if replies else None,
        'comments_enabled': getattr(replies, 'comments', None) if replies else None,
        'reactions': serialize_message_reactions(msg),
        'edit_date': edit_date.isoformat() if edit_date else None,
        'grouped_id': getattr(msg, 'grouped_id', None),
        'post_author': getattr(msg, 'post_author', None),
        'media_type': type(msg.media).__name__ if getattr(msg, 'media', None) else None,
    }


async def export_profile_async(
    profile_name: str,
    config_name: str = 'channels',  # новый параметр
    since: Optional[Dict[str, int]] = None,
    until_id: Optional[int] = None,
) -> Tuple[Dict[str, Any], int]:

    # Загружаем нужный конфиг
    CONFIG = load_config(config_name)
    
    profiles = CONFIG.get('profiles') or {}
    profile_cfg = profiles.get(profile_name)
    
    if not profile_cfg:
        return {'error': f'Unknown profile {profile_name} in config {config_name}'}, 400

    session_name = profile_cfg.get('session_name', profile_name)
    session_path = resolve_session_path(session_name)
    cleanup_legacy_session_files(session_name)
    
    client = TelegramClient(session_path, API_ID, API_HASH)

    date_from = parse_date(profile_cfg.get('date_from'))
    date_to = parse_date(profile_cfg.get('date_to', 'now'))
    limit_per_channel = int(profile_cfg.get('limit_per_channel', 0)) or None
    global_limit = int(profile_cfg.get('global_limit', 0)) or None
    channels = profile_cfg.get('channels') or []

    await client.connect()
    if not await client.is_user_authorized():
        await client.disconnect()
        return {'error': 'Session not authorized. Run interactive login first.'}, 403

    all_messages: List[Dict[str, Any]] = []
    total_count = 0

    is_incremental = isinstance(since, dict) and len(since) > 0

    for ch in channels:
        username = ch.get('username')
        if not username:
            continue

        ch_date_from = parse_date(ch.get('date_from')) or date_from
        ch_date_to = parse_date(ch.get('date_to')) or date_to
        ch_limit = int(ch.get('limit', 0)) or limit_per_channel

        ch_since_id: Optional[int] = None
        if since and username in since:
            ch_since_id = since[username]

        kwargs: Dict[str, Any] = {'reverse': False}
        if ch_limit:
            kwargs['limit'] = ch_limit

        if is_incremental and ch_since_id is not None:
            kwargs['min_id'] = ch_since_id

        async for msg in client.iter_messages(username, **kwargs):
            if not isinstance(msg, Message):
                continue

            msg_dt = msg.date.replace(tzinfo=None)
            if ch_date_from and msg_dt < ch_date_from:
                continue
            if ch_date_to and msg_dt > ch_date_to:
                continue

            if ch_since_id is not None and msg.id <= ch_since_id:
                continue
            if until_id is not None and msg.id >= until_id:
                continue

            all_messages.append({
                'id': msg.id,
                'date': msg.date.isoformat(),
                'chat': username,
                'message': msg.message,
                'from_id': msg.sender_id,
                'original_url': f'https://t.me/{username}/{msg.id}',
                'external_links': extract_message_links(msg),
                **serialize_message_stats(msg),
            })

            total_count += 1
            if global_limit and total_count >= global_limit:
                break

        if global_limit and total_count >= global_limit:
            break

    await client.disconnect()
    return {
        'profile': profile_name,
        'config': config_name,
        'messages': all_messages,
        'count': total_count
    }, 200


@app.get('/export')
def export() -> Any:
    remote_base = remote_export_base_url()
    if remote_base:
        try:
            response = requests.get(f"{remote_base}/export", params=request.args, headers=remote_export_headers(), timeout=120)
            return jsonify(response.json()), response.status_code
        except Exception as e:
            return jsonify({'error': f'remote_export_failed: {e}'}), 502
    profile = request.args.get('profile', 'profile1')
    config_name = request.args.get('config', 'channels')
    since_raw = request.args.get('since')
    since: Optional[Dict[str, int]] = None
    if since_raw:
        try:
            since = json.loads(since_raw)
        except Exception:
            since = None

    until_id = request.args.get('until_id', type=int)

    try:
        data, status = asyncio.run(
            export_profile_async(profile, config_name, since, until_id)
        )
        return jsonify(data), status
    except FileNotFoundError as e:
        print("FileNotFoundError in /export:", e, flush=True)
        return jsonify({'error': str(e)}), 404
    except Exception as e:
        print("Exception in /export:", repr(e), flush=True)
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    host = os.getenv('TG_API_HOST', '127.0.0.1')
    port = int(os.getenv('TG_API_PORT', '8001'))
    app.run(host=host, port=port)
