import argparse
import json
from pathlib import Path

from telegram_monitor_pipeline import build_digest_payload, latest_file


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary-input", help="Путь к *_summary_input.json. По умолчанию берется самый свежий.")
    parser.add_argument("--config", default="daily")
    parser.add_argument("--profile", default="profile_1")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary_path = Path(args.summary_input) if args.summary_input else latest_file("raw_*_summary_input.json")
    if not summary_path or not summary_path.exists():
        raise SystemExit("Не найден summary_input для генерации CSV.")

    report = build_digest_payload(summary_path, config_name=args.config, profile_name=args.profile)
    print(json.dumps({
        "summary_input": str(summary_path),
        "csv_path": report["csv_path"],
        "payload_path": report["payload_path"],
        "non_empty_messages": report["non_empty_messages"],
        "requires_review_count": report["requires_review_count"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
