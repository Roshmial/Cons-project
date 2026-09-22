from __future__ import annotations

import hashlib
import mimetypes
import os
import shutil
import sqlite3
import subprocess
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from PIL import Image

try:
    from faster_whisper import WhisperModel
except Exception:
    WhisperModel = None

try:
    import imageio_ffmpeg
except Exception:
    imageio_ffmpeg = None

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("MEMORY_ARCHIVE_DATA_DIR", BASE_DIR / "data"))
ORIGINALS_DIR = DATA_DIR / "originals"
DERIVED_DIR = DATA_DIR / "derived"
THUMBS_DIR = DERIVED_DIR / "thumbnails"
AUDIO_DIR = DERIVED_DIR / "audio"
DB_DIR = DATA_DIR / "db"
DB_PATH = DB_DIR / "memory_archive.db"
UI_DIR = BASE_DIR / "static"
WHISPER_CACHE_DIR = DATA_DIR / "models"

_WHISPER_MODEL: Any | None = None


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ensure_dirs() -> None:
    for path in [DATA_DIR, ORIGINALS_DIR, DERIVED_DIR, THUMBS_DIR, AUDIO_DIR, DB_DIR, UI_DIR, WHISPER_CACHE_DIR]:
        path.mkdir(parents=True, exist_ok=True)


@contextmanager
def db_conn():
    ensure_dirs()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    ensure_dirs()
    with db_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS people (
                id TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                notes TEXT DEFAULT '',
                is_confirmed INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS episodes (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                start_at TEXT,
                end_at TEXT,
                location_text TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'draft',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS media_items (
                id TEXT PRIMARY KEY,
                original_filename TEXT NOT NULL,
                stored_filename TEXT NOT NULL,
                relative_path TEXT NOT NULL,
                media_type TEXT NOT NULL,
                mime_type TEXT DEFAULT '',
                sha256 TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                source_note TEXT DEFAULT '',
                transcript_text TEXT DEFAULT '',
                ai_summary TEXT DEFAULT '',
                processing_status TEXT NOT NULL DEFAULT 'stored',
                created_at_estimated TEXT,
                imported_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS episode_media (
                episode_id TEXT NOT NULL,
                media_id TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'supporting',
                PRIMARY KEY (episode_id, media_id),
                FOREIGN KEY (episode_id) REFERENCES episodes(id) ON DELETE CASCADE,
                FOREIGN KEY (media_id) REFERENCES media_items(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS episode_people (
                episode_id TEXT NOT NULL,
                person_id TEXT NOT NULL,
                role_in_episode TEXT DEFAULT '',
                confirmed INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (episode_id, person_id),
                FOREIGN KEY (episode_id) REFERENCES episodes(id) ON DELETE CASCADE,
                FOREIGN KEY (person_id) REFERENCES people(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS person_media_matches (
                id TEXT PRIMARY KEY,
                person_id TEXT NOT NULL,
                media_id TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 1.0,
                source TEXT NOT NULL DEFAULT 'user',
                confirmed INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                FOREIGN KEY (person_id) REFERENCES people(id) ON DELETE CASCADE,
                FOREIGN KEY (media_id) REFERENCES media_items(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                job_type TEXT NOT NULL,
                status TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                result_json TEXT DEFAULT '',
                error_text TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT
            );

            CREATE TABLE IF NOT EXISTS review_candidates (
                id TEXT PRIMARY KEY,
                candidate_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                title TEXT NOT NULL,
                details_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                source_type TEXT NOT NULL DEFAULT 'json',
                source_format TEXT NOT NULL DEFAULT 'generic_json',
                source_path TEXT DEFAULT '',
                source_sha256 TEXT NOT NULL DEFAULT '',
                participants_json TEXT NOT NULL DEFAULT '[]',
                imported_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS conversation_messages (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                external_id TEXT DEFAULT '',
                sender_name TEXT NOT NULL,
                sent_at TEXT DEFAULT '',
                text_content TEXT DEFAULT '',
                raw_json TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS episode_messages (
                episode_id TEXT NOT NULL,
                message_id TEXT NOT NULL,
                PRIMARY KEY (episode_id, message_id),
                FOREIGN KEY (episode_id) REFERENCES episodes(id) ON DELETE CASCADE,
                FOREIGN KEY (message_id) REFERENCES conversation_messages(id) ON DELETE CASCADE
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS media_fts USING fts5(
                media_id UNINDEXED,
                original_filename,
                source_note,
                transcript_text,
                ai_summary,
                content=''
            );
            """
        )
        conversation_cols = {row[1] for row in conn.execute("PRAGMA table_info(conversations)").fetchall()}
        if "source_format" not in conversation_cols:
            conn.execute("ALTER TABLE conversations ADD COLUMN source_format TEXT NOT NULL DEFAULT 'generic_json'")
        if "source_sha256" not in conversation_cols:
            conn.execute("ALTER TABLE conversations ADD COLUMN source_sha256 TEXT NOT NULL DEFAULT ''")
        reconcile_conversation_dedup(conn)


def detect_media_type(filename: str, mime_type: str) -> str:
    lower = filename.lower()
    mime = (mime_type or "").lower()
    if mime.startswith("image/") or lower.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif")):
        return "photo"
    if mime.startswith("video/") or lower.endswith((".mp4", ".mov", ".mkv", ".avi", ".webm")):
        return "video"
    if mime.startswith("audio/") or lower.endswith((".mp3", ".wav", ".m4a", ".ogg", ".flac")):
        return "audio"
    return "other"


def file_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def build_ai_summary(filename: str, media_type: str, note: str) -> str:
    parts = [f"Тип: {media_type}", f"Файл: {filename}"]
    if note:
        parts.append(f"Заметка: {note.strip()}")
    return "; ".join(parts)


def store_fts(conn: sqlite3.Connection, media_id: str, filename: str, note: str, transcript: str, summary: str) -> None:
    conn.execute("DELETE FROM media_fts WHERE media_id = ?", (media_id,))
    conn.execute(
        "INSERT INTO media_fts(media_id, original_filename, source_note, transcript_text, ai_summary) VALUES (?, ?, ?, ?, ?)",
        (media_id, filename, note, transcript, summary),
    )


def generate_thumbnail(src: Path, media_id: str) -> str | None:
    try:
        with Image.open(src) as image:
            image.thumbnail((640, 640))
            dest = THUMBS_DIR / f"{media_id}.jpg"
            image.convert("RGB").save(dest, format="JPEG", quality=88)
            return str(dest.relative_to(DATA_DIR))
    except Exception:
        return None


def ffmpeg_executable() -> str | None:
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg
    if imageio_ffmpeg is not None:
        try:
            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            return None
    return None


def extract_audio(src: Path, media_id: str, media_type: str) -> Path | None:
    ffmpeg = ffmpeg_executable()
    if not ffmpeg or media_type not in {"audio", "video"}:
        return None
    dest = AUDIO_DIR / f"{media_id}.wav"
    command = [ffmpeg, "-y"]
    if media_type == "video":
        command += ["-i", str(src), "-vn"]
    else:
        command += ["-i", str(src)]
    command += ["-ac", "1", "-ar", "16000", str(dest)]
    try:
        subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=180)
    except Exception:
        return None
    return dest if dest.exists() else None


def load_whisper_model() -> Any | None:
    global _WHISPER_MODEL
    if _WHISPER_MODEL is not None:
        return _WHISPER_MODEL
    if WhisperModel is None:
        return None
    try:
        _WHISPER_MODEL = WhisperModel("tiny", device="cpu", compute_type="int8", download_root=str(WHISPER_CACHE_DIR))
        return _WHISPER_MODEL
    except Exception:
        return None


def read_text_content(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def transcribe_media_path(item: dict[str, Any], src: Path) -> tuple[str, str]:
    media_type = item["media_type"]
    note = item["source_note"].strip()
    if src.suffix.lower() in {".txt", ".md"}:
        text = read_text_content(src)
        if text:
            return text, "text-file"
    if media_type == "photo":
        return (note or f"Фото «{item['original_filename']}» без отдельной расшифровки."), "photo-note"
    audio_path = extract_audio(src, item["id"], media_type)
    model = load_whisper_model()
    if audio_path and model is not None:
        try:
            segments, info = model.transcribe(str(audio_path), vad_filter=True, beam_size=1)
            text = " ".join(segment.text.strip() for segment in segments).strip()
            if not text:
                segments, info = model.transcribe(str(audio_path), vad_filter=False, beam_size=1)
                text = " ".join(segment.text.strip() for segment in segments).strip()
            if text:
                lang = getattr(info, "language", "unknown")
                return text, f"whisper:{lang}"
        except Exception:
            pass
    return build_transcript(item), "fallback"


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def normalize_sent_at(value: Any) -> str:
    if value is None:
        return ""
    raw = str(value).strip()
    if not raw:
        return ""
    if raw.isdigit():
        try:
            return datetime.fromtimestamp(int(raw), tz=timezone.utc).replace(microsecond=0).isoformat()
        except Exception:
            return raw
    return raw


def detect_conversation_format(payload: Any) -> str:
    if isinstance(payload, dict):
        messages = payload.get("messages") or payload.get("chat_messages") or payload.get("items") or []
        if payload.get("name") and isinstance(messages, list) and any(isinstance(m, dict) and ("from" in m or "date" in m or "date_unixtime" in m) for m in messages[:5]):
            return "telegram_json"
        if payload.get("conversation") or payload.get("chat"):
            return "structured_json"
    elif isinstance(payload, list):
        if any(isinstance(m, dict) and ("author" in m or "message_id" in m or "timestamp" in m) for m in payload[:5]):
            return "whatsapp_json"
    return "generic_json"


def parse_conversation_json(payload: Any, source_path: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    source_format = detect_conversation_format(payload)
    if isinstance(payload, dict):
        conversation = payload.get("conversation") or payload.get("chat") or {}
        if payload.get("name") and not conversation.get("title"):
            conversation = {**conversation, "title": payload.get("name")}
        messages = payload.get("messages") or payload.get("items") or payload.get("chat_messages") or []
    elif isinstance(payload, list):
        conversation = {}
        messages = payload
    else:
        raise HTTPException(status_code=400, detail="Unsupported JSON shape")
    if not isinstance(messages, list):
        raise HTTPException(status_code=400, detail="messages must be a list")
    title = str(conversation.get("title") or conversation.get("name") or Path(source_path).stem or "Conversation").strip()
    participants = conversation.get("participants") or []
    normalized = []
    for item in messages:
        if not isinstance(item, dict):
            continue
        sender = str(item.get("sender_name") or item.get("from") or item.get("author") or item.get("sender") or item.get("actor") or "Unknown").strip()
        text = item.get("text_content") or item.get("text") or item.get("message") or item.get("body") or item.get("content") or ""
        if isinstance(text, list):
            parts = []
            for part in text:
                if isinstance(part, str):
                    parts.append(part)
                elif isinstance(part, dict):
                    parts.append(str(part.get("text") or part.get("href") or ""))
                elif part:
                    parts.append(str(part))
            text = " ".join(p for p in parts if p)
        text = str(text).strip()
        normalized.append({
            "external_id": str(item.get("id") or item.get("message_id") or ""),
            "sender_name": sender,
            "sent_at": normalize_sent_at(item.get("sent_at") or item.get("date") or item.get("date_unixtime") or item.get("timestamp") or item.get("created_at")),
            "text_content": text,
            "raw_json": item,
        })
        if sender and sender not in participants:
            participants.append(sender)
    return {"title": title, "participants": participants, "source_format": source_format}, normalized


def import_conversation_json(json_path: str) -> dict[str, Any]:
    src = Path(json_path).expanduser().resolve()
    if not src.exists() or not src.is_file():
        raise HTTPException(status_code=400, detail="JSON file does not exist")
    import json
    raw_text = src.read_text(encoding="utf-8")
    source_sha256 = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
    payload = json.loads(raw_text)
    convo, messages = parse_conversation_json(payload, str(src))
    now = utc_now()
    with db_conn() as conn:
        existing = conn.execute("SELECT * FROM conversations WHERE source_sha256=? LIMIT 1", (source_sha256,)).fetchone()
        if existing:
            existing_id = existing["id"]
            existing_count = conn.execute("SELECT COUNT(*) AS c FROM conversation_messages WHERE conversation_id=?", (existing_id,)).fetchone()["c"]
            return {"ok": True, "conversation_id": existing_id, "title": existing["title"], "participants": json_loads(existing["participants_json"]), "message_count": existing_count, "source_format": existing["source_format"], "deduplicated": True}
        conversation_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO conversations(id, title, source_type, source_format, source_path, source_sha256, participants_json, imported_at, updated_at) VALUES (?, ?, 'json', ?, ?, ?, ?, ?, ?)",
            (conversation_id, convo["title"], convo["source_format"], str(src), source_sha256, json_dumps(convo["participants"]), now, now),
        )
        for msg in messages:
            conn.execute(
                "INSERT INTO conversation_messages(id, conversation_id, external_id, sender_name, sent_at, text_content, raw_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), conversation_id, msg["external_id"], msg["sender_name"], msg["sent_at"], msg["text_content"], json_dumps(msg["raw_json"])),
            )
    return {"ok": True, "conversation_id": conversation_id, "title": convo["title"], "participants": convo["participants"], "message_count": len(messages), "source_format": convo["source_format"], "deduplicated": False}


def import_media_folder_internal(folder_path: str, source_note: str = "") -> dict[str, Any]:
    src = Path(folder_path).expanduser().resolve()
    if not src.exists() or not src.is_dir():
        raise HTTPException(status_code=400, detail="Folder does not exist")
    imported = []
    for path in sorted(src.iterdir()):
        if not path.is_file():
            continue
        if path.suffix.lower() in {'.json'}:
            continue
        media_id = str(uuid.uuid4())
        stored_name = f"{media_id}{path.suffix.lower()}"
        dest = ORIGINALS_DIR / stored_name
        shutil.copy2(path, dest)
        mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        media_type = detect_media_type(path.name, mime_type)
        summary = build_ai_summary(path.name, media_type, source_note)
        if media_type == "photo":
            generate_thumbnail(dest, media_id)
        now = utc_now()
        with db_conn() as conn:
            conn.execute(
                "INSERT INTO media_items(id, original_filename, stored_filename, relative_path, media_type, mime_type, sha256, size_bytes, source_note, transcript_text, ai_summary, processing_status, created_at_estimated, imported_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?, 'stored', NULL, ?, ?)",
                (media_id, path.name, stored_name, str(Path("originals") / stored_name), media_type, mime_type, file_sha256(dest), dest.stat().st_size, source_note, summary, now, now),
            )
            store_fts(conn, media_id, path.name, source_note, "", summary)
        imported.append({"id": media_id, "filename": path.name, "media_type": media_type})
    return {"ok": True, "imported_count": len(imported), "items": imported[:50]}


def import_archive_bundle(root_path: str, source_note: str = "") -> dict[str, Any]:
    root = Path(root_path).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise HTTPException(status_code=400, detail="Bundle root does not exist")
    media_dirs = [p for p in [root / 'media', root / 'photos', root / 'videos', root / 'audio'] if p.exists() and p.is_dir()]
    chat_files = [p for p in sorted(root.rglob('*.json')) if p.is_file() and ('chat' in p.name.lower() or 'telegram' in p.name.lower() or 'whatsapp' in p.name.lower() or p.parent.name.lower() in {'chats', 'chat', 'messages'})]
    note_files = [p for p in sorted(root.rglob('*')) if p.is_file() and p.suffix.lower() in {'.txt', '.md'} and ('note' in p.name.lower() or p.parent.name.lower() in {'notes', 'note'})]
    if not media_dirs:
        media_dirs = [root]
    media_total = 0
    media_items = []
    for media_dir in media_dirs:
        result = import_media_folder_internal(str(media_dir), source_note=source_note)
        media_total += result['imported_count']
        media_items.extend(result['items'])
    conversations = []
    seen = set()
    for chat_file in chat_files:
        if str(chat_file) in seen:
            continue
        seen.add(str(chat_file))
        conversations.append(import_conversation_json(str(chat_file)))
    notes_preview = []
    for note_file in note_files[:20]:
        try:
            text = read_text_content(note_file)[:240]
        except Exception:
            text = ''
        notes_preview.append({'path': str(note_file), 'preview': text})
    return {
        'ok': True,
        'root_path': str(root),
        'media_imported_count': media_total,
        'conversation_imported_count': len(conversations),
        'note_count': len(note_files),
        'media_items': media_items[:20],
        'conversations': conversations[:20],
        'notes_preview': notes_preview,
    }


def reconcile_conversation_dedup(conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT id, source_path, source_sha256 FROM conversations").fetchall()
    for row in rows:
        source_path = row["source_path"] or ""
        if row["source_sha256"] or not source_path:
            continue
        src = Path(source_path)
        if src.exists() and src.is_file():
            raw_text = src.read_text(encoding="utf-8")
            sha = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
            conn.execute("UPDATE conversations SET source_sha256=?, updated_at=? WHERE id=?", (sha, utc_now(), row["id"]))
    dup_rows = conn.execute("SELECT source_sha256 FROM conversations WHERE source_sha256 != '' GROUP BY source_sha256 HAVING COUNT(*) > 1").fetchall()
    for dup in dup_rows:
        sha = dup["source_sha256"]
        convs = conn.execute("SELECT * FROM conversations WHERE source_sha256=? ORDER BY imported_at ASC, id ASC", (sha,)).fetchall()
        keep = convs[0]
        for loser in convs[1:]:
            loser_messages = conn.execute("SELECT * FROM conversation_messages WHERE conversation_id=?", (loser["id"],)).fetchall()
            for msg in loser_messages:
                existing = conn.execute(
                    "SELECT id FROM conversation_messages WHERE conversation_id=? AND external_id=? AND sender_name=? AND sent_at=? AND text_content=? LIMIT 1",
                    (keep["id"], msg["external_id"], msg["sender_name"], msg["sent_at"], msg["text_content"]),
                ).fetchone()
                if existing:
                    conn.execute("UPDATE OR IGNORE episode_messages SET message_id=? WHERE message_id=?", (existing["id"], msg["id"]))
                    conn.execute("DELETE FROM episode_messages WHERE message_id=?", (msg["id"],))
                    conn.execute("DELETE FROM conversation_messages WHERE id=?", (msg["id"],))
                else:
                    conn.execute("UPDATE conversation_messages SET conversation_id=? WHERE id=?", (keep["id"], msg["id"]))
            conn.execute("DELETE FROM conversations WHERE id=?", (loser["id"],))


def enrich_media(row: sqlite3.Row) -> dict[str, Any]:
    item = row_to_dict(row)
    thumb_rel = f"derived/thumbnails/{item['id']}.jpg"
    thumb_abs = DATA_DIR / thumb_rel
    item["thumbnail_url"] = f"/media-file/{thumb_rel}" if thumb_abs.exists() else None
    item["file_url"] = f"/media-file/{item['relative_path']}"
    return item


def enrich_conversation(row: sqlite3.Row, conn: sqlite3.Connection) -> dict[str, Any]:
    item = row_to_dict(row)
    item["participants_json"] = json_loads(item.get("participants_json", "[]"))
    stats = conn.execute(
        "SELECT COUNT(*) AS message_count, MIN(sent_at) AS first_sent_at, MAX(sent_at) AS last_sent_at FROM conversation_messages WHERE conversation_id=?",
        (item["id"],),
    ).fetchone()
    item["message_count"] = stats["message_count"] if stats else 0
    item["first_sent_at"] = stats["first_sent_at"] if stats else ""
    item["last_sent_at"] = stats["last_sent_at"] if stats else ""
    return item


def build_episode_card(conn: sqlite3.Connection, episode_row: sqlite3.Row) -> dict[str, Any]:
    episode = row_to_dict(episode_row)
    media_rows = conn.execute(
        "SELECT m.*, em.role FROM media_items m JOIN episode_media em ON em.media_id=m.id WHERE em.episode_id=? ORDER BY m.imported_at DESC",
        (episode['id'],),
    ).fetchall()
    people_rows = conn.execute(
        "SELECT p.* FROM people p JOIN episode_people ep ON ep.person_id=p.id WHERE ep.episode_id=? ORDER BY p.display_name",
        (episode['id'],),
    ).fetchall()
    message_rows = conn.execute(
        "SELECT m.*, c.title AS conversation_title FROM conversation_messages m JOIN episode_messages em ON em.message_id=m.id JOIN conversations c ON c.id=m.conversation_id WHERE em.episode_id=? ORDER BY m.sent_at DESC, m.id DESC",
        (episode['id'],),
    ).fetchall()
    media = [enrich_media(row) for row in media_rows]
    people_names = [row['display_name'] for row in people_rows]
    quotes = [row['text_content'] for row in message_rows if row['text_content']][:2]
    transcript_bits = []
    for item in media:
        text = item.get('transcript_text') or item.get('source_note') or item.get('ai_summary') or ''
        if text:
            transcript_bits.append(text[:140])
    summary_parts = []
    if people_names:
        summary_parts.append('Участвуют: ' + ', '.join(people_names[:4]))
    if transcript_bits:
        summary_parts.append(transcript_bits[0])
    if quotes:
        summary_parts.append('Из переписки: ' + quotes[0][:140])
    preview = ' '.join(summary_parts).strip() or (episode.get('description') or episode.get('title') or 'Эпизод без описания')
    return {
        'episode': episode,
        'media_count': len(media),
        'message_count': len(message_rows),
        'people': people_names,
        'preview': preview,
        'top_media': [{'id': m['id'], 'original_filename': m['original_filename'], 'thumbnail_url': m.get('thumbnail_url')} for m in media[:4]],
        'quotes': quotes,
    }


def build_person_story(conn: sqlite3.Connection, person_id: str) -> dict[str, Any]:
    person = conn.execute("SELECT * FROM people WHERE id=?", (person_id,)).fetchone()
    if not person:
        raise HTTPException(status_code=404, detail="Person not found")
    episode_rows = conn.execute(
        "SELECT e.* FROM episodes e JOIN episode_people ep ON ep.episode_id=e.id WHERE ep.person_id=? ORDER BY e.updated_at DESC",
        (person_id,),
    ).fetchall()
    cards = [build_episode_card(conn, row) for row in episode_rows]
    topic_counter: dict[str, int] = {}
    relationship_quotes = []
    for card in cards:
        text = ' '.join([card['episode'].get('title', ''), card.get('preview', ''), ' '.join(card.get('quotes', []))]).lower()
        for token in ['озер', 'рыбал', 'пикник', 'лето', 'семь', 'море', 'поезд']:
            if token in text:
                topic_counter[token] = topic_counter.get(token, 0) + 1
        for quote in card.get('quotes', []):
            if quote not in relationship_quotes:
                relationship_quotes.append(quote)
    top_topics = [k for k, _ in sorted(topic_counter.items(), key=lambda x: (-x[1], x[0]))[:3]]
    image = []
    if cards:
        image.append(f"{person['display_name']} проявляется через {len(cards)} подтверждённых эпизодов.")
    if top_topics:
        image.append('Чаще всего рядом с ним всплывают темы: ' + ', '.join(top_topics) + '.')
    if relationship_quotes:
        image.append('В обсуждениях чаще всего звучит: ' + relationship_quotes[0][:180])
    highlights = []
    for card in cards[:5]:
        highlights.append(f"{card['episode']['title']}: {card['preview'][:180]}")
    story_text = '\n'.join(f"• {item}" for item in highlights) or 'Пока подтверждённых эпизодов недостаточно.'
    portrait_text = ' '.join(image) if image else 'Пока образ человека не собран: нужно больше подтверждённых эпизодов.'
    return {'person': row_to_dict(person), 'episode_cards': cards, 'story_text': story_text, 'portrait_text': portrait_text, 'top_topics': top_topics, 'quotes': relationship_quotes[:3]}


def build_memory_highlights(conn: sqlite3.Connection, limit: int = 6) -> dict[str, Any]:
    rows = conn.execute(
        "SELECT e.* FROM episodes e LEFT JOIN episode_media em ON em.episode_id=e.id LEFT JOIN episode_messages msg ON msg.episode_id=e.id GROUP BY e.id ORDER BY COUNT(DISTINCT em.media_id) + COUNT(DISTINCT msg.message_id) DESC, e.updated_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    cards = [build_episode_card(conn, row) for row in rows]
    return {'items': cards}


def build_person_npc_reply(conn: sqlite3.Connection, person_id: str, user_message: str) -> dict[str, Any]:
    story = build_person_story(conn, person_id)
    prompt = user_message.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail='Message is empty')
    cards = story['episode_cards']
    lowered = prompt.lower()
    matched = []
    for card in cards:
        hay = ' '.join([
            card['episode'].get('title', ''),
            card.get('preview', ''),
            ' '.join(card.get('quotes', [])),
            ' '.join(card.get('people', [])),
        ]).lower()
        if any(token in hay for token in lowered.split() if len(token) >= 3):
            matched.append(card)
    if not matched:
        matched = cards[:2]
    evidence_media = []
    evidence_quotes = []
    for card in matched[:2]:
        evidence_media.extend(card.get('top_media', []))
        evidence_quotes.extend(card.get('quotes', []))
    person_name = story['person']['display_name']
    voice = []
    voice.append(f'Если держаться только подтверждённых материалов, образ {person_name} сейчас выглядит так.')
    voice.append(story['portrait_text'])
    if matched:
        voice.append('Ближе всего к этому вопросу подходят такие эпизоды:')
        for card in matched[:2]:
            voice.append(f"• {card['episode']['title']} — {card['preview'][:180]}")
    if evidence_quotes:
        voice.append('Из обсуждений это поддерживают такие реплики:')
        for quote in evidence_quotes[:2]:
            voice.append(f'• «{quote[:180]}»')
    voice.append('Я не дорисовываю характер вне архива: это именно память по подтверждённым следам.')
    return {
        'person': story['person'],
        'reply': '\n'.join(voice),
        'mode': 'npc_memory_grounded',
        'matched_episode_cards': matched[:3],
        'evidence': {
            'quotes': evidence_quotes[:3],
            'media': evidence_media[:6],
            'top_topics': story.get('top_topics', []),
        },
    }


def create_job(conn: sqlite3.Connection, job_type: str, payload: dict[str, Any]) -> str:
    job_id = str(uuid.uuid4())
    now = utc_now()
    conn.execute(
        "INSERT INTO jobs(id, job_type, status, payload_json, result_json, error_text, created_at, started_at, finished_at) VALUES (?, ?, 'queued', ?, '', '', ?, NULL, NULL)",
        (job_id, job_type, json_dumps(payload), now),
    )
    return job_id


def update_job(conn: sqlite3.Connection, job_id: str, *, status: str, result: dict[str, Any] | None = None, error_text: str = "") -> None:
    started_at = utc_now() if status == "running" else None
    finished_at = utc_now() if status in {"completed", "failed"} else None
    if status == "running":
        conn.execute("UPDATE jobs SET status=?, started_at=? WHERE id=?", (status, started_at, job_id))
    else:
        conn.execute(
            "UPDATE jobs SET status=?, finished_at=?, result_json=?, error_text=? WHERE id=?",
            (status, finished_at, json_dumps(result or {}), error_text, job_id),
        )


def json_dumps(value: Any) -> str:
    import json
    return json.dumps(value, ensure_ascii=False)


def json_loads(value: str) -> Any:
    import json
    return json.loads(value) if value else {}


def insert_review_candidate(conn: sqlite3.Connection, candidate_type: str, title: str, details: dict[str, Any]) -> str:
    candidate_id = str(uuid.uuid4())
    now = utc_now()
    conn.execute(
        "INSERT INTO review_candidates(id, candidate_type, status, title, details_json, created_at, updated_at) VALUES (?, ?, 'pending', ?, ?, ?, ?)",
        (candidate_id, candidate_type, title, json_dumps(details), now, now),
    )
    return candidate_id


def run_transcription_job(media_id: str) -> dict[str, Any]:
    with db_conn() as conn:
        row = conn.execute("SELECT * FROM media_items WHERE id=?", (media_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Media not found")
        item = row_to_dict(row)
        job_id = create_job(conn, "transcribe", {"media_id": media_id})
        update_job(conn, job_id, status="running")
        src = DATA_DIR / item["relative_path"]
        transcript, transcript_source = transcribe_media_path(item, src)
        summary = item["ai_summary"]
        if transcript and transcript not in summary:
            summary = f"{summary}; transcript: {transcript[:180]}"
        conn.execute(
            "UPDATE media_items SET transcript_text=?, ai_summary=?, processing_status='transcribed', updated_at=? WHERE id=?",
            (transcript, summary, utc_now(), media_id),
        )
        store_fts(conn, media_id, item["original_filename"], item["source_note"], transcript, summary)
        result = {"media_id": media_id, "transcript_text": transcript, "transcript_source": transcript_source}
        update_job(conn, job_id, status="completed", result=result)
        refreshed = conn.execute("SELECT * FROM media_items WHERE id=?", (media_id,)).fetchone()
    return {"job_id": job_id, "media": enrich_media(refreshed), "result": result}


def build_transcript(item: dict[str, Any]) -> str:
    media_type = item["media_type"]
    filename = item["original_filename"]
    note = item["source_note"].strip()
    if media_type == "audio":
        return f"Черновая расшифровка аудио «{filename}». {note}".strip()
    if media_type == "video":
        return f"Черновая расшифровка видео «{filename}». {note}".strip()
    if media_type == "photo":
        return note or f"Фото «{filename}» без отдельной расшифровки."
    return note or f"Материал «{filename}» без расшифровки."


def suggest_episodes() -> list[dict[str, Any]]:
    with db_conn() as conn:
        rows = conn.execute(
            """
            SELECT m.* FROM media_items m
            LEFT JOIN episode_media em ON em.media_id = m.id
            WHERE em.media_id IS NULL
            ORDER BY m.imported_at DESC
            """
        ).fetchall()
        groups: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            item = row_to_dict(row)
            note = (item["source_note"] or item["original_filename"]).strip() or "Без описания"
            date_hint = (item.get("created_at_estimated") or item.get("imported_at") or "")[:10]
            key = f"{date_hint} | {note}" if date_hint else note
            groups.setdefault(key, []).append(item)
        message_rows = conn.execute(
            "SELECT m.*, c.title AS conversation_title FROM conversation_messages m JOIN conversations c ON c.id=m.conversation_id LEFT JOIN episode_messages em ON em.message_id=m.id WHERE em.message_id IS NULL ORDER BY m.sent_at DESC, m.id DESC"
        ).fetchall()
        created: list[dict[str, Any]] = []
        for key, items in groups.items():
            if not items:
                continue
            title = key.split("|", 1)[-1].strip()[:80]
            related_message_ids = []
            for row in message_rows:
                msg = row_to_dict(row)
                hay = " ".join([msg.get("sender_name", ""), msg.get("text_content", ""), msg.get("conversation_title", "")]).lower()
                if title.lower() in hay or any(part.lower() in hay for part in title.split() if len(part) >= 4):
                    related_message_ids.append(msg["id"])
            details = {
                "title": title,
                "description": f"AI suggestion from {len(items)} media items",
                "media_ids": [item["id"] for item in items],
                "message_ids": related_message_ids[:20],
                "source_note": title,
                "date_hint": key.split("|", 1)[0].strip() if "|" in key else "",
            }
            candidate_id = insert_review_candidate(conn, "episode", title, details)
            created.append({"id": candidate_id, "title": title, "media_count": len(items), "details": details})
        return created


def suggest_person_media(person_id: str) -> list[dict[str, Any]]:
    with db_conn() as conn:
        person = conn.execute("SELECT * FROM people WHERE id=?", (person_id,)).fetchone()
        if not person:
            raise HTTPException(status_code=404, detail="Person not found")
        person_name = (person["display_name"] or "").strip().lower()
        rows = conn.execute(
            """
            SELECT m.* FROM media_items m
            LEFT JOIN person_media_matches pmm ON pmm.media_id = m.id AND pmm.person_id = ?
            WHERE pmm.media_id IS NULL
            ORDER BY m.imported_at DESC
            """,
            (person_id,),
        ).fetchall()
        matched = []
        for row in rows:
            item = row_to_dict(row)
            hay = " ".join(
                [
                    item.get("original_filename", ""),
                    item.get("source_note", ""),
                    item.get("transcript_text", ""),
                    item.get("ai_summary", ""),
                ]
            ).lower()
            if person_name and person_name in hay:
                matched.append(item)
        if not matched:
            return []
        title = f"Материалы для {person['display_name']}"
        details = {
            "person_id": person_id,
            "person_name": person["display_name"],
            "media_ids": [item["id"] for item in matched],
            "matched_count": len(matched),
        }
        candidate_id = insert_review_candidate(conn, "person_media", title, details)
        return [{"id": candidate_id, "title": title, "details": details, "media_count": len(matched)}]


def suggest_person_messages(person_id: str) -> list[dict[str, Any]]:
    with db_conn() as conn:
        person = conn.execute("SELECT * FROM people WHERE id=?", (person_id,)).fetchone()
        if not person:
            raise HTTPException(status_code=404, detail="Person not found")
        person_name = (person["display_name"] or "").strip().lower()
        rows = conn.execute(
            """
            SELECT m.*, c.title AS conversation_title
            FROM conversation_messages m
            JOIN conversations c ON c.id = m.conversation_id
            LEFT JOIN episode_messages em ON em.message_id = m.id
            WHERE em.message_id IS NULL
            ORDER BY m.sent_at DESC, m.id DESC
            """
        ).fetchall()
        matched = []
        for row in rows:
            item = row_to_dict(row)
            hay = " ".join([item.get("sender_name", ""), item.get("text_content", ""), item.get("conversation_title", "")]).lower()
            if person_name and person_name in hay:
                matched.append(item)
        if not matched:
            return []
        title = f"Переписка для {person['display_name']}"
        details = {
            "person_id": person_id,
            "person_name": person["display_name"],
            "message_ids": [item["id"] for item in matched[:50]],
            "matched_count": len(matched),
            "conversation_titles": sorted({item.get("conversation_title", "") for item in matched if item.get("conversation_title")}),
        }
        candidate_id = insert_review_candidate(conn, "person_messages", title, details)
        return [{"id": candidate_id, "title": title, "details": details, "message_count": len(details['message_ids'])}]


class PersonCreate(BaseModel):
    display_name: str
    notes: str = ""


class EpisodeCreate(BaseModel):
    title: str
    description: str = ""
    start_at: str | None = None
    end_at: str | None = None
    location_text: str = ""


class EpisodeAttach(BaseModel):
    media_id: str
    role: str = "supporting"


class EpisodePersonAttach(BaseModel):
    person_id: str
    role_in_episode: str = "participant"


class EpisodeAsk(BaseModel):
    question: str


class ReviewAction(BaseModel):
    action: str
    person_id: str | None = None


class EpisodeMessageAttach(BaseModel):
    message_id: str


class BundleImportRequest(BaseModel):
    root_path: str
    source_note: str = ""


class PersonChatRequest(BaseModel):
    message: str


app = FastAPI(title="Memory Archive MVP Light")
app.mount("/static", StaticFiles(directory=UI_DIR), name="static")


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (UI_DIR / "index.html").read_text(encoding="utf-8")


@app.get("/api/health")
def health() -> dict[str, Any]:
    with db_conn() as conn:
        media_count = conn.execute("SELECT COUNT(*) FROM media_items").fetchone()[0]
        episode_count = conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
        people_count = conn.execute("SELECT COUNT(*) FROM people").fetchone()[0]
        conversation_count = conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
        message_count = conn.execute("SELECT COUNT(*) FROM conversation_messages").fetchone()[0]
        pending_reviews = conn.execute("SELECT COUNT(*) FROM review_candidates WHERE status='pending'").fetchone()[0]
        jobs_count = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    return {
        "ok": True,
        "time": utc_now(),
        "db_path": str(DB_PATH),
        "runtime": {
            "ffmpeg_available": bool(ffmpeg_executable()),
            "whisper_available": WhisperModel is not None,
        },
        "counts": {
            "media": media_count,
            "episodes": episode_count,
            "people": people_count,
            "conversations": conversation_count,
            "messages": message_count,
            "pending_reviews": pending_reviews,
            "jobs": jobs_count,
        },
    }


@app.post("/api/media/upload")
async def upload_media(file: UploadFile = File(...), source_note: str = Form("")) -> dict[str, Any]:
    media_id = str(uuid.uuid4())
    suffix = Path(file.filename or "upload.bin").suffix.lower()
    stored_name = f"{media_id}{suffix}"
    dest = ORIGINALS_DIR / stored_name
    with dest.open("wb") as fh:
        shutil.copyfileobj(file.file, fh)
    sha256 = file_sha256(dest)
    mime_type = file.content_type or mimetypes.guess_type(file.filename or "")[0] or "application/octet-stream"
    media_type = detect_media_type(file.filename or stored_name, mime_type)
    summary = build_ai_summary(file.filename or stored_name, media_type, source_note)
    if media_type == "photo":
        generate_thumbnail(dest, media_id)
    now = utc_now()
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO media_items(id, original_filename, stored_filename, relative_path, media_type, mime_type, sha256, size_bytes, source_note, transcript_text, ai_summary, processing_status, created_at_estimated, imported_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?, 'stored', NULL, ?, ?)",
            (media_id, file.filename or stored_name, stored_name, str(Path("originals") / stored_name), media_type, mime_type, sha256, dest.stat().st_size, source_note, summary, now, now),
        )
        store_fts(conn, media_id, file.filename or stored_name, source_note, "", summary)
        row = conn.execute("SELECT * FROM media_items WHERE id=?", (media_id,)).fetchone()
    return {"ok": True, "media": enrich_media(row)}


@app.post("/api/media/import-folder")
def import_folder(folder_path: str = Form(...), source_note: str = Form("")) -> dict[str, Any]:
    return import_media_folder_internal(folder_path, source_note)


@app.post("/api/archive/import-bundle")
def api_import_bundle(payload: BundleImportRequest) -> dict[str, Any]:
    return import_archive_bundle(payload.root_path, payload.source_note)


@app.post("/api/conversations/import-json")
def import_conversation(json_path: str = Form(...)) -> dict[str, Any]:
    return import_conversation_json(json_path)


@app.get("/api/conversations")
def list_conversations() -> dict[str, Any]:
    with db_conn() as conn:
        rows = conn.execute("SELECT * FROM conversations ORDER BY imported_at DESC LIMIT 100").fetchall()
        items = [enrich_conversation(row, conn) for row in rows]
    return {"items": items}


@app.get("/api/conversations/{conversation_id}")
def get_conversation(conversation_id: str) -> dict[str, Any]:
    with db_conn() as conn:
        row = conn.execute("SELECT * FROM conversations WHERE id=?", (conversation_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Conversation not found")
        messages = conn.execute(
            "SELECT * FROM conversation_messages WHERE conversation_id=? ORDER BY sent_at ASC, id ASC LIMIT 500",
            (conversation_id,),
        ).fetchall()
        item = enrich_conversation(row, conn)
    return {"conversation": item, "messages": [row_to_dict(msg) for msg in messages]}


@app.get("/api/messages")
def list_messages(q: str = "") -> dict[str, Any]:
    with db_conn() as conn:
        if q:
            like = f"%{q}%"
            rows = conn.execute(
                "SELECT m.*, c.title AS conversation_title FROM conversation_messages m JOIN conversations c ON c.id=m.conversation_id WHERE m.sender_name LIKE ? OR m.text_content LIKE ? OR c.title LIKE ? ORDER BY m.sent_at DESC, m.id DESC LIMIT 200",
                (like, like, like),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT m.*, c.title AS conversation_title FROM conversation_messages m JOIN conversations c ON c.id=m.conversation_id ORDER BY m.sent_at DESC, m.id DESC LIMIT 200"
            ).fetchall()
    return {"items": [row_to_dict(row) for row in rows]}


@app.get("/api/media")
def list_media(q: str = "", media_type: str = "") -> dict[str, Any]:
    with db_conn() as conn:
        if q:
            like = f"%{q}%"
            rows = conn.execute(
                "SELECT * FROM media_items WHERE original_filename LIKE ? OR source_note LIKE ? OR transcript_text LIKE ? OR ai_summary LIKE ? ORDER BY imported_at DESC LIMIT 100",
                (like, like, like, like),
            ).fetchall()
        elif media_type:
            rows = conn.execute("SELECT * FROM media_items WHERE media_type=? ORDER BY imported_at DESC LIMIT 100", (media_type,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM media_items ORDER BY imported_at DESC LIMIT 100").fetchall()
    return {"items": [enrich_media(row) for row in rows]}


@app.post("/api/media/{media_id}/transcribe")
def transcribe_media(media_id: str) -> dict[str, Any]:
    return {"ok": True, **run_transcription_job(media_id)}


@app.get("/api/jobs")
def list_jobs() -> dict[str, Any]:
    with db_conn() as conn:
        rows = conn.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT 100").fetchall()
    items = [row_to_dict(row) for row in rows]
    for item in items:
        item["payload_json"] = json_loads(item["payload_json"])
        item["result_json"] = json_loads(item["result_json"])
    return {"items": items}


@app.get("/api/highlights")
def list_highlights(limit: int = 6) -> dict[str, Any]:
    with db_conn() as conn:
        return build_memory_highlights(conn, limit=max(1, min(limit, 12)))


@app.post("/api/people")
def create_person(payload: PersonCreate) -> dict[str, Any]:
    person_id = str(uuid.uuid4())
    now = utc_now()
    with db_conn() as conn:
        conn.execute("INSERT INTO people(id, display_name, notes, is_confirmed, created_at, updated_at) VALUES (?, ?, ?, 1, ?, ?)", (person_id, payload.display_name.strip(), payload.notes.strip(), now, now))
        row = conn.execute("SELECT * FROM people WHERE id=?", (person_id,)).fetchone()
    return {"ok": True, "person": row_to_dict(row)}


@app.get("/api/people")
def list_people() -> dict[str, Any]:
    with db_conn() as conn:
        rows = conn.execute("SELECT * FROM people ORDER BY updated_at DESC").fetchall()
    return {"items": [row_to_dict(row) for row in rows]}


@app.get("/api/people/{person_id}/story")
def person_story(person_id: str) -> dict[str, Any]:
    with db_conn() as conn:
        return build_person_story(conn, person_id)


@app.post("/api/people/{person_id}/chat")
def person_chat(person_id: str, payload: PersonChatRequest) -> dict[str, Any]:
    with db_conn() as conn:
        return build_person_npc_reply(conn, person_id, payload.message)


@app.post("/api/episodes")
def create_episode(payload: EpisodeCreate) -> dict[str, Any]:
    episode_id = str(uuid.uuid4())
    now = utc_now()
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO episodes(id, title, description, start_at, end_at, location_text, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 'draft', ?, ?)",
            (episode_id, payload.title.strip(), payload.description.strip(), payload.start_at, payload.end_at, payload.location_text.strip(), now, now),
        )
        row = conn.execute("SELECT * FROM episodes WHERE id=?", (episode_id,)).fetchone()
    return {"ok": True, "episode": row_to_dict(row)}


@app.get("/api/episodes")
def list_episodes() -> dict[str, Any]:
    with db_conn() as conn:
        rows = conn.execute("SELECT e.*, COUNT(em.media_id) AS media_count FROM episodes e LEFT JOIN episode_media em ON em.episode_id=e.id GROUP BY e.id ORDER BY e.updated_at DESC").fetchall()
    return {"items": [row_to_dict(row) for row in rows]}


@app.get("/api/episodes/{episode_id}")
def get_episode(episode_id: str) -> dict[str, Any]:
    with db_conn() as conn:
        episode = conn.execute("SELECT * FROM episodes WHERE id=?", (episode_id,)).fetchone()
        if not episode:
            raise HTTPException(status_code=404, detail="Episode not found")
        media_rows = conn.execute("SELECT m.*, em.role FROM media_items m JOIN episode_media em ON em.media_id=m.id WHERE em.episode_id=? ORDER BY m.imported_at DESC", (episode_id,)).fetchall()
        people_rows = conn.execute("SELECT p.*, ep.role_in_episode, ep.confirmed FROM people p JOIN episode_people ep ON ep.person_id=p.id WHERE ep.episode_id=? ORDER BY p.display_name", (episode_id,)).fetchall()
        message_rows = conn.execute(
            "SELECT m.*, c.title AS conversation_title FROM conversation_messages m JOIN episode_messages em ON em.message_id=m.id JOIN conversations c ON c.id=m.conversation_id WHERE em.episode_id=? ORDER BY m.sent_at DESC, m.id DESC",
            (episode_id,),
        ).fetchall()
    return {"episode": row_to_dict(episode), "media": [enrich_media(row) for row in media_rows], "people": [row_to_dict(row) for row in people_rows], "messages": [row_to_dict(row) for row in message_rows]}


@app.post("/api/episodes/{episode_id}/attach-media")
def attach_media(episode_id: str, payload: EpisodeAttach) -> dict[str, Any]:
    with db_conn() as conn:
        if not conn.execute("SELECT 1 FROM episodes WHERE id=?", (episode_id,)).fetchone():
            raise HTTPException(status_code=404, detail="Episode not found")
        if not conn.execute("SELECT 1 FROM media_items WHERE id=?", (payload.media_id,)).fetchone():
            raise HTTPException(status_code=404, detail="Media not found")
        conn.execute("INSERT OR REPLACE INTO episode_media(episode_id, media_id, role) VALUES (?, ?, ?)", (episode_id, payload.media_id, payload.role))
        conn.execute("UPDATE episodes SET updated_at=? WHERE id=?", (utc_now(), episode_id))
    return {"ok": True}


@app.post("/api/episodes/{episode_id}/attach-person")
def attach_person(episode_id: str, payload: EpisodePersonAttach) -> dict[str, Any]:
    with db_conn() as conn:
        if not conn.execute("SELECT 1 FROM episodes WHERE id=?", (episode_id,)).fetchone():
            raise HTTPException(status_code=404, detail="Episode not found")
        if not conn.execute("SELECT 1 FROM people WHERE id=?", (payload.person_id,)).fetchone():
            raise HTTPException(status_code=404, detail="Person not found")
        conn.execute(
            "INSERT OR REPLACE INTO episode_people(episode_id, person_id, role_in_episode, confirmed) VALUES (?, ?, ?, 1)",
            (episode_id, payload.person_id, payload.role_in_episode),
        )
        conn.execute("UPDATE episodes SET updated_at=? WHERE id=?", (utc_now(), episode_id))
    return {"ok": True}


@app.post("/api/episodes/{episode_id}/attach-message")
def attach_message(episode_id: str, payload: EpisodeMessageAttach) -> dict[str, Any]:
    with db_conn() as conn:
        if not conn.execute("SELECT 1 FROM episodes WHERE id=?", (episode_id,)).fetchone():
            raise HTTPException(status_code=404, detail="Episode not found")
        if not conn.execute("SELECT 1 FROM conversation_messages WHERE id=?", (payload.message_id,)).fetchone():
            raise HTTPException(status_code=404, detail="Message not found")
        conn.execute("INSERT OR REPLACE INTO episode_messages(episode_id, message_id) VALUES (?, ?)", (episode_id, payload.message_id))
        conn.execute("UPDATE episodes SET updated_at=? WHERE id=?", (utc_now(), episode_id))
    return {"ok": True}


@app.post("/api/episodes/{episode_id}/ask")
def ask_episode(episode_id: str, payload: EpisodeAsk) -> dict[str, Any]:
    question = payload.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question is empty")
    normalized = question.lower()
    for ch in ",.!?:;()[]{}\n\t":
        normalized = normalized.replace(ch, " ")
    tokens = [t for t in normalized.split() if len(t) >= 3][:8]
    token_roots = {t[:4] for t in tokens if len(t) >= 4}
    with db_conn() as conn:
        episode = conn.execute("SELECT * FROM episodes WHERE id=?", (episode_id,)).fetchone()
        if not episode:
            raise HTTPException(status_code=404, detail="Episode not found")
        rows = conn.execute("SELECT m.*, em.role FROM media_items m JOIN episode_media em ON em.media_id=m.id WHERE em.episode_id=? ORDER BY m.imported_at DESC", (episode_id,)).fetchall()
        people_rows = conn.execute("SELECT p.* FROM people p JOIN episode_people ep ON ep.person_id=p.id WHERE ep.episode_id=? ORDER BY p.display_name", (episode_id,)).fetchall()
        message_rows = conn.execute(
            "SELECT m.*, c.title AS conversation_title FROM conversation_messages m JOIN episode_messages em ON em.message_id=m.id JOIN conversations c ON c.id=m.conversation_id WHERE em.episode_id=? ORDER BY m.sent_at DESC, m.id DESC",
            (episode_id,),
        ).fetchall()
    evidence = []
    people_names = [row["display_name"] for row in people_rows]
    people_roots = {name.lower()[:4] for name in people_names if name}
    for row in rows:
        item = enrich_media(row)
        hay = " ".join([item.get("original_filename", ""), item.get("source_note", ""), item.get("transcript_text", ""), item.get("ai_summary", ""), " ".join(people_names)]).lower()
        hay_roots = {word[:4] for word in hay.split() if len(word) >= 4}
        if not tokens or any(t in hay for t in tokens) or (token_roots & hay_roots):
            evidence.append(item)
    if not evidence and rows and (token_roots & people_roots):
        evidence = [enrich_media(row) for row in rows[:5]]
    message_evidence = []
    for row in message_rows:
        item = row_to_dict(row)
        hay = " ".join([item.get("sender_name", ""), item.get("text_content", ""), item.get("conversation_title", "")]).lower()
        hay_roots = {word[:4] for word in hay.split() if len(word) >= 4}
        if not tokens or any(t in hay for t in tokens) or (token_roots & hay_roots):
            message_evidence.append(item)
    if not evidence and not message_evidence:
        return {"ok": True, "answer": "По этому эпизоду у меня пока нет достаточного подтверждённого материала для ответа на такой вопрос.", "mode": "insufficient_data", "evidence": [], "episode": row_to_dict(episode)}
    total_evidence = len(evidence) + len(message_evidence)
    lines = [f"Нашла {total_evidence} связанных источников по этому эпизоду."]
    for item in evidence[:5]:
        note = item.get("transcript_text") or item.get("source_note") or item.get("ai_summary") or item.get("original_filename")
        lines.append(f"• {item['original_filename']}: {note[:180]}")
    for item in message_evidence[:5]:
        lines.append(f"• переписка / {item['sender_name']}: {item.get('text_content', '')[:180]}")
    return {"ok": True, "answer": "\n".join(lines), "mode": "evidence_backed", "evidence": {"media": evidence[:10], "messages": message_evidence[:10]}, "episode": row_to_dict(episode)}


@app.post("/api/review/suggest-episodes")
def api_suggest_episodes() -> dict[str, Any]:
    created = suggest_episodes()
    return {"ok": True, "created_count": len(created), "items": created}


@app.post("/api/review/suggest-person-media/{person_id}")
def api_suggest_person_media(person_id: str) -> dict[str, Any]:
    created = suggest_person_media(person_id)
    return {"ok": True, "created_count": len(created), "items": created}


@app.post("/api/review/suggest-person-messages/{person_id}")
def api_suggest_person_messages(person_id: str) -> dict[str, Any]:
    created = suggest_person_messages(person_id)
    return {"ok": True, "created_count": len(created), "items": created}


@app.get("/api/review/candidates")
def list_review_candidates(status: str = "pending") -> dict[str, Any]:
    with db_conn() as conn:
        if status == "all":
            rows = conn.execute("SELECT * FROM review_candidates ORDER BY created_at DESC").fetchall()
        else:
            rows = conn.execute("SELECT * FROM review_candidates WHERE status=? ORDER BY created_at DESC", (status,)).fetchall()
    items = [row_to_dict(row) for row in rows]
    for item in items:
        item["details_json"] = json_loads(item["details_json"])
    return {"items": items}


@app.post("/api/review/candidates/{candidate_id}/apply")
def apply_review_candidate(candidate_id: str, payload: ReviewAction) -> dict[str, Any]:
    action = payload.action.strip().lower()
    with db_conn() as conn:
        row = conn.execute("SELECT * FROM review_candidates WHERE id=?", (candidate_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Candidate not found")
        candidate = row_to_dict(row)
        details = json_loads(candidate["details_json"])
        now = utc_now()
        if action == "reject":
            conn.execute("UPDATE review_candidates SET status='rejected', updated_at=? WHERE id=?", (now, candidate_id))
            return {"ok": True, "status": "rejected"}
        if candidate["candidate_type"] == "episode" and action == "accept":
            episode_id = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO episodes(id, title, description, start_at, end_at, location_text, status, created_at, updated_at) VALUES (?, ?, ?, NULL, NULL, ?, 'confirmed', ?, ?)",
                (episode_id, details.get("title", candidate["title"]), details.get("description", ""), details.get("source_note", ""), now, now),
            )
            for media_id in details.get("media_ids", []):
                conn.execute("INSERT OR IGNORE INTO episode_media(episode_id, media_id, role) VALUES (?, ?, 'supporting')", (episode_id, media_id))
            for message_id in details.get("message_ids", []):
                conn.execute("INSERT OR IGNORE INTO episode_messages(episode_id, message_id) VALUES (?, ?)", (episode_id, message_id))
            conn.execute("UPDATE review_candidates SET status='accepted', updated_at=? WHERE id=?", (now, candidate_id))
            return {"ok": True, "status": "accepted", "episode_id": episode_id}
        if candidate["candidate_type"] == "person_messages" and action == "accept":
            if not payload.person_id:
                raise HTTPException(status_code=400, detail="person_id is required")
            conn.execute("UPDATE review_candidates SET status='accepted', updated_at=? WHERE id=?", (now, candidate_id))
            return {"ok": True, "status": "accepted", "person_id": payload.person_id, "linked_messages": len(details.get("message_ids", []))}
        if candidate["candidate_type"] == "person_media" and action == "accept":
            if not payload.person_id:
                raise HTTPException(status_code=400, detail="person_id is required")
            for media_id in details.get("media_ids", []):
                conn.execute(
                    "INSERT INTO person_media_matches(id, person_id, media_id, confidence, source, confirmed, created_at) VALUES (?, ?, ?, ?, 'ai', 1, ?)",
                    (str(uuid.uuid4()), payload.person_id, media_id, 0.8, now),
                )
            conn.execute("UPDATE review_candidates SET status='accepted', updated_at=? WHERE id=?", (now, candidate_id))
            return {"ok": True, "status": "accepted", "person_id": payload.person_id}
        raise HTTPException(status_code=400, detail="Unsupported action")


@app.get("/api/search")
def search_memory(q: str) -> dict[str, Any]:
    query = q.strip()
    if not query:
        return {"episodes": [], "media": [], "messages": []}
    like = f"%{query}%"
    with db_conn() as conn:
        episode_rows = conn.execute("SELECT * FROM episodes WHERE title LIKE ? OR description LIKE ? OR location_text LIKE ? ORDER BY updated_at DESC LIMIT 20", (like, like, like)).fetchall()
        media_rows = conn.execute("SELECT * FROM media_items WHERE original_filename LIKE ? OR source_note LIKE ? OR transcript_text LIKE ? OR ai_summary LIKE ? ORDER BY imported_at DESC LIMIT 20", (like, like, like, like)).fetchall()
        message_rows = conn.execute("SELECT m.*, c.title AS conversation_title FROM conversation_messages m JOIN conversations c ON c.id=m.conversation_id WHERE m.sender_name LIKE ? OR m.text_content LIKE ? OR c.title LIKE ? ORDER BY m.sent_at DESC, m.id DESC LIMIT 20", (like, like, like)).fetchall()
    return {"episodes": [row_to_dict(row) for row in episode_rows], "media": [enrich_media(row) for row in media_rows], "messages": [row_to_dict(row) for row in message_rows]}


@app.get("/media-file/{relative_path:path}")
def media_file(relative_path: str):
    target = (DATA_DIR / relative_path).resolve()
    if DATA_DIR.resolve() not in target.parents and target != DATA_DIR.resolve():
        raise HTTPException(status_code=400, detail="Bad path")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(target)


@app.exception_handler(Exception)
def on_error(_: Request, exc: Exception):
    if isinstance(exc, HTTPException):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    return JSONResponse(status_code=500, content={"detail": str(exc)})
