import os
import re
import socket
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
INSTANCE_FILE = BASE_DIR / ".tg-monitor-instance-id"


def _sanitize_instance_id(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z._-]+", "-", (value or "").strip())
    cleaned = cleaned.strip("-._")
    return cleaned or "default"


def resolve_instance_id() -> str:
    explicit = os.getenv("TG_MONITOR_INSTANCE_ID", "").strip()
    if explicit:
        return _sanitize_instance_id(explicit)
    if INSTANCE_FILE.exists():
        file_value = INSTANCE_FILE.read_text(encoding="utf-8").strip()
        if file_value:
            return _sanitize_instance_id(file_value)
    return _sanitize_instance_id(socket.gethostname())


INSTANCE_ID = resolve_instance_id()
RUNTIME_ROOT = BASE_DIR / "runtime" / INSTANCE_ID
RAW_LOGS_DIR = RUNTIME_ROOT / "raw_logs"
ARCHIVE_DIR = RUNTIME_ROOT / "archive"
REPORTS_DIR = RAW_LOGS_DIR / "reports"
POINTER_PATH = RAW_LOGS_DIR / "latest_collection_report.json"
LATEST_NON_EMPTY_PATH = RAW_LOGS_DIR / "latest_non_empty_for_summary.json"
LATEST_SUMMARY_POINTER = RAW_LOGS_DIR / "latest_summary_input_path.txt"
SINCE_PATH = RUNTIME_ROOT / "tg-since-id-it_consulting.json"
ARCHIVE_JSONL = ARCHIVE_DIR / "telegram_messages.jsonl"
CACHE_DOCS_DIR = Path("/home/hermes/.hermes/cache/documents") / "tg-it-consulting" / INSTANCE_ID


def ensure_runtime_dirs() -> None:
    RAW_LOGS_DIR.mkdir(parents=True, exist_ok=True)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DOCS_DIR.mkdir(parents=True, exist_ok=True)
