import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from telegram_monitor_pipeline import build_digest_payload, load_latest_collection_report, parse_dt
from tg_instance_paths import POINTER_PATH
from tg_monitor_settings import DEFAULT_CONFIG_NAME, DEFAULT_PROFILE_NAME

MAX_COLLECTION_AGE_HOURS = 18


def main() -> int:
    report = load_latest_collection_report()
    if not report:
        raise SystemExit("Не найден отчёт сборщика. Сначала нужно выполнить collect_daily_pipeline.py")

    started_at_raw = report.get("started_at")
    if not started_at_raw:
        raise SystemExit("В отчёте сборщика отсутствует started_at")

    started_at = parse_dt(started_at_raw)
    age = datetime.now(timezone.utc) - started_at.astimezone(timezone.utc)
    if age > timedelta(hours=MAX_COLLECTION_AGE_HOURS):
        raise SystemExit(f"Последний отчёт сборщика устарел: age_hours={age.total_seconds() / 3600:.2f}")

    if report.get("status") not in {"ok", "no_new_messages"}:
        raise SystemExit(f"Последний отчёт сборщика в некорректном статусе: {report.get('status')}")

    if report.get("status") == "no_new_messages":
        print(json.dumps({
            "collector_status": "no_new_messages",
            "report_path": report.get("_path") or str(POINTER_PATH),
            "non_empty_messages": 0,
        }, ensure_ascii=False))
        return 0

    payload = report.get("collector_payload") or {}
    summary_input = payload.get("summary_input")
    if not summary_input:
        raise SystemExit("В отчёте сборщика отсутствует путь к summary_input")

    digest_payload = build_digest_payload(
        Path(summary_input),
        config_name=DEFAULT_CONFIG_NAME,
        profile_name=DEFAULT_PROFILE_NAME,
    )
    output = {
        "collector_status": report.get("status"),
        "collection_report_path": report.get("_path") or str(POINTER_PATH),
        "summary_input": summary_input,
        "digest_payload_path": digest_payload["payload_path"],
        "csv_path": digest_payload["csv_path"],
        "non_empty_messages": digest_payload["non_empty_messages"],
        "requires_review_count": digest_payload["requires_review_count"],
        "top_candidates_preview": [
            {
                "канал": item["канал"],
                "тип поста": item["тип поста"],
                "score": item["score"],
                "краткое содержание": item["краткое содержание"],
            }
            for item in digest_payload["top_candidates"][:5]
        ],
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
