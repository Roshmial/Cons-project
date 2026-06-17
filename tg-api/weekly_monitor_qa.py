import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from telegram_monitor_pipeline import (
    build_digest_payload,
    list_recent_collection_reports,
    list_recent_summary_inputs,
    msk_now,
)
from tg_monitor_settings import DEFAULT_CONFIG_NAME, DEFAULT_PROFILE_NAME

OUT_DIR = Path('/home/hermes/.hermes/cache/documents')
OUT_DIR.mkdir(parents=True, exist_ok=True)


def main() -> int:
    reports = list_recent_collection_reports(days=7)
    summaries = list_recent_summary_inputs(days=7)

    runs_total = len(reports)
    no_new_runs = sum(1 for report in reports if report.get('status') == 'no_new_messages')
    failed_runs = sum(1 for report in reports if report.get('status') not in {'ok', 'no_new_messages'})

    non_empty_counts = []
    requires_review_total = 0
    channel_scores = defaultdict(float)
    channel_counts = Counter()
    type_counts = Counter()

    for summary_path in summaries:
        digest_payload = build_digest_payload(
            summary_path,
            config_name=DEFAULT_CONFIG_NAME,
            profile_name=DEFAULT_PROFILE_NAME,
        )
        non_empty_counts.append(digest_payload['non_empty_messages'])
        requires_review_total += digest_payload['requires_review_count']
        for row in digest_payload['rows']:
            channel = row['канал']
            channel_counts[channel] += 1
            channel_scores[channel] += row.get('_score', 0.0)
            type_counts[row['тип поста']] += 1

    average_non_empty = round(sum(non_empty_counts) / len(non_empty_counts), 2) if non_empty_counts else 0.0
    avg_channel_score = {
        channel: round(channel_scores[channel] / channel_counts[channel], 2)
        for channel in channel_counts
    }
    top_useful = sorted(avg_channel_score.items(), key=lambda item: item[1], reverse=True)[:5]
    noisy = sorted(channel_counts.items(), key=lambda item: item[1], reverse=True)[:5]

    qa_data = {
        'generated_at': msk_now().isoformat(),
        'runs_total': runs_total,
        'no_new_runs': no_new_runs,
        'failed_runs': failed_runs,
        'summary_files': len(summaries),
        'average_non_empty_messages': average_non_empty,
        'requires_review_total': requires_review_total,
        'top_useful_channels': top_useful,
        'highest_volume_channels': noisy,
        'type_counts': type_counts,
    }

    stamp = msk_now().strftime('%Y-%m-%d_%H-%M-%S')
    qa_path = OUT_DIR / f'telegram_it_consulting_weekly_qa_{stamp}.json'
    qa_path.write_text(json.dumps(qa_data, ensure_ascii=False, indent=2), encoding='utf-8')

    lines = [
        f"QA-отчет Telegram monitor за 7 дней на {msk_now().strftime('%d.%m.%Y %H:%M МСК')}",
        f"Запусков: {runs_total}; без новых сообщений: {no_new_runs}; с ошибками: {failed_runs}.",
        f"Summary-файлов с непустыми сообщениями: {len(summaries)}; среднее число непустых сообщений: {average_non_empty}.",
        f"Сообщений с типом 'требует уточнения': {requires_review_total}.",
    ]

    if top_useful:
        formatted = '; '.join(f"{channel} ({score})" for channel, score in top_useful)
        lines.append(f"Каналы с наибольшим средним score: {formatted}.")
    if noisy:
        formatted = '; '.join(f"{channel} ({count})" for channel, count in noisy)
        lines.append(f"Каналы с наибольшим объемом непустых сообщений: {formatted}.")
    if type_counts:
        formatted = '; '.join(f"{post_type}: {count}" for post_type, count in type_counts.most_common())
        lines.append(f"Распределение типов: {formatted}.")

    lines.append(f"JSON: {qa_path}")
    print('\n'.join(lines))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
