from __future__ import annotations

import json
import os
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb
from urllib.request import urlopen

SERVICE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("HERMES_WEB_BACKEND_DATA_DIR", str(SERVICE_DIR / "data")))
DB_PATH = Path(os.getenv("HERMES_WEB_BACKEND_DB_PATH", DATA_DIR / "hermes_web_app.duckdb"))
RUNTIME_AUDIT_LOG_PATH = Path(os.getenv("HERMES_WEB_RUNTIME_AUDIT_LOG_PATH", str(DATA_DIR / "runtime_audit.jsonl")))
WINDOW_HOURS = int(os.getenv("HERMES_WEB_RUNTIME_AUDIT_WINDOW_HOURS", "24"))
TOP_EXAMPLES = int(os.getenv("HERMES_WEB_RUNTIME_AUDIT_TOP_EXAMPLES", "5"))

HIGH_SEVERITY_ERROR_CLASSES = {
    "timed out",
    "timeout",
    "connection error",
    "connection refused",
    "service unavailable",
    "internal server error",
}
MEDIUM_SEVERITY_ERROR_CLASSES = {
    "bad gateway",
    "gateway timeout",
    "rate limit",
    "rate limited",
    "json decode error",
    "invalid response",
}
HIGH_SEVERITY_DEGRADED_KINDS = {
    "empty_result",
    "no_sources_found",
    "sources_unavailable",
}
MEDIUM_SEVERITY_DEGRADED_KINDS = {
    "hybrid_content_plus_shortlist",
    "sources_partially_unavailable",
    "partial_result",
    "degraded_result",
}
SEVERITY_WEIGHT = {"high": 3, "medium": 2, "low": 1}


def parse_iso(value: str) -> datetime | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def safe_text(value: object) -> str:
    return "" if value is None else str(value)


def compact(text: str, limit: int = 140) -> str:
    cleaned = " ".join(safe_text(text).split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,;:-") + "…"


def classify_event(event: dict) -> str:
    if safe_text(event.get("event_type")) == "chat_task_error":
        return safe_text(event.get("error_class")) or "unknown_error"
    return safe_text(event.get("fallback_result_kind") or event.get("status_note") or event.get("message_kind") or "degraded_result")


def classify_severity(event: dict) -> str:
    event_type = safe_text(event.get("event_type"))
    class_key = classify_event(event).strip().lower()
    if event_type == "chat_task_error":
        if class_key in HIGH_SEVERITY_ERROR_CLASSES:
            return "high"
        if class_key in MEDIUM_SEVERITY_ERROR_CLASSES:
            return "medium"
        return "medium" if "error" in class_key else "low"
    if class_key in HIGH_SEVERITY_DEGRADED_KINDS:
        return "high"
    if class_key in MEDIUM_SEVERITY_DEGRADED_KINDS:
        return "medium"
    if event.get("partial_result"):
        return "medium"
    return "low"


def compute_priority(severity: str, count: int, user_total: int) -> int:
    return SEVERITY_WEIGHT.get(severity, 1) * 100 + count * 10 + user_total * 15


def verify_backend_health() -> None:
    try:
        with urlopen("http://127.0.0.1:8791/api/health", timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise RuntimeError(f'Аудит не выполнен: backend health недоступен: {exc}') from exc
    if payload.get("status") != "ok":
        raise RuntimeError(f'Аудит не выполнен: backend health вернул {payload.get("status")!r}')


def load_events(window_start: datetime) -> list[dict]:
    if not RUNTIME_AUDIT_LOG_PATH.exists():
        verify_backend_health()
        return []
    age = datetime.now(UTC) - datetime.fromtimestamp(RUNTIME_AUDIT_LOG_PATH.stat().st_mtime, tz=UTC)
    if age > timedelta(hours=WINDOW_HOURS * 2):
        # Лог событий обновляется только при ошибках/деградациях. Его старая
        # дата допустима, если живой backend подтверждает отсутствие аварии.
        verify_backend_health()
    events: list[dict] = []
    for line in RUNTIME_AUDIT_LOG_PATH.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw:
            continue
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        logged_at = parse_iso(safe_text(event.get("logged_at")))
        if logged_at is None or logged_at < window_start:
            continue
        events.append(event)
    return events


def load_users() -> dict[int, str]:
    if not DB_PATH.exists():
        return {}
    conn = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        rows = conn.execute("SELECT id, COALESCE(NULLIF(name, ''), email, CONCAT('user#', id)) AS label FROM app.users").fetchall()
    finally:
        conn.close()
    return {int(row[0]): safe_text(row[1]) for row in rows}


def format_report(events: list[dict], users: dict[int, str], window_start: datetime, now: datetime) -> str:
    header = f"Ежедневный аудит Hermes Web за последние {WINDOW_HOURS} ч."
    period = f"Период: {window_start.strftime('%Y-%m-%d %H:%M')} UTC → {now.strftime('%Y-%m-%d %H:%M')} UTC"
    if not events:
        return "\n".join([
            header,
            period,
            "",
            "Сигналов по ошибкам и некорректной отработке не найдено.",
        ])

    type_counts = Counter(safe_text(event.get("event_type")) or "unknown" for event in events)
    class_counts = Counter()
    severity_counts = Counter()
    user_counts = Counter()
    first_seen_by_class: dict[str, datetime] = {}
    users_by_class: dict[str, set[int]] = {}
    severity_by_class: dict[str, str] = {}
    examples: list[str] = []

    for event in events:
        user_id = int(event.get("user_id") or 0)
        severity = classify_severity(event)
        severity_counts[severity] += 1
        if user_id:
            user_counts[user_id] += 1
        class_key = classify_event(event)
        class_counts[class_key] += 1
        severity_by_class.setdefault(class_key, severity)
        if user_id:
            users_by_class.setdefault(class_key, set()).add(user_id)
        logged_at = parse_iso(safe_text(event.get("logged_at")))
        if logged_at is not None and class_key not in first_seen_by_class:
            first_seen_by_class[class_key] = logged_at

    for event in events[:TOP_EXAMPLES]:
        label = users.get(int(event.get("user_id") or 0), f"user#{int(event.get('user_id') or 0)}")
        if safe_text(event.get("event_type")) == "chat_task_error":
            problem = safe_text(event.get("public_error_text") or event.get("error_text") or event.get("error_class"))
        else:
            problem = safe_text(event.get("fallback_result_kind") or event.get("status_note") or event.get("message_kind"))
        request_preview = compact(safe_text(event.get("request_preview")))
        examples.append(f"- {label}: [{classify_severity(event)}] {problem} — {request_preview}")

    repeated_multi_user = []
    newest_classes = []
    ranked_classes = []
    for class_key, count in class_counts.items():
        user_total = len(users_by_class.get(class_key, set()))
        severity = severity_by_class.get(class_key, "low")
        priority = compute_priority(severity, count, user_total)
        if user_total >= 2:
            repeated_multi_user.append((class_key, severity, user_total, count, priority))
        newest_classes.append((class_key, severity, first_seen_by_class.get(class_key), count, priority))
        ranked_classes.append((class_key, severity, count, user_total, priority))

    repeated_multi_user.sort(key=lambda item: (-item[4], -item[2], -item[3], item[0]))
    newest_classes.sort(key=lambda item: ((item[2] or datetime.min.replace(tzinfo=UTC)), item[4]), reverse=True)
    ranked_classes.sort(key=lambda item: (-item[4], -item[2], -item[3], item[0]))

    lines = [header, period, "", "Итоги:"]
    lines.append(f"- Всего сигналов: {len(events)}")
    for event_type, count in sorted(type_counts.items(), key=lambda item: (-item[1], item[0])):
        label = {
            "chat_task_error": "ошибки",
            "chat_task_degraded_result": "деградированные/частичные результаты",
        }.get(event_type, event_type)
        lines.append(f"- {label}: {count}")
    if severity_counts:
        severity_parts = [f"{label}={severity_counts[label]}" for label in ("high", "medium", "low") if severity_counts[label]]
        lines.append(f"- severity: {', '.join(severity_parts)}")

    if ranked_classes:
        lines.append("")
        lines.append("Приоритет на разбор:")
        for class_key, severity, count, user_total, priority in ranked_classes[:7]:
            lines.append(f"- {class_key}: severity={severity}, signals={count}, users={user_total}, priority={priority}")

    if newest_classes:
        lines.append("")
        lines.append("Новые классы за сутки:")
        for class_key, severity, first_seen_at, count, priority in newest_classes[:7]:
            first_seen_text = first_seen_at.strftime('%Y-%m-%d %H:%M UTC') if first_seen_at else 'время не определено'
            lines.append(f"- {class_key}: severity={severity}, signals={count}, priority={priority}, первый сигнал {first_seen_text}")

    if repeated_multi_user:
        lines.append("")
        lines.append("Повторяются у нескольких пользователей:")
        for class_key, severity, user_total, count, priority in repeated_multi_user[:7]:
            lines.append(f"- {class_key}: severity={severity}, signals={count}, users={user_total}, priority={priority}")

    if user_counts:
        lines.append("")
        lines.append("Пользователи с наибольшим числом сигналов:")
        for user_id, count in user_counts.most_common(7):
            lines.append(f"- {users.get(user_id, f'user#{user_id}')}: {count}")

    if examples:
        lines.append("")
        lines.append("Примеры:")
        lines.extend(examples)

    return "\n".join(lines)


def main() -> None:
    now = datetime.now(UTC)
    window_start = now - timedelta(hours=WINDOW_HOURS)
    events = load_events(window_start)
    users = load_users()
    print(format_report(events, users, window_start, now))


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as exc:
        print(str(exc))
        raise SystemExit(1)
