import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

from telegram_monitor_pipeline import (
    build_digest_payload,
    derive_rows,
    list_recent_collection_reports,
    list_recent_summary_inputs,
    msk_now,
)
from tg_instance_paths import CACHE_DOCS_DIR, INSTANCE_ID
from tg_monitor_settings import DEFAULT_CONFIG_NAME, DEFAULT_PROFILE_NAME

OUT_DIR = CACHE_DOCS_DIR
OUT_DIR.mkdir(parents=True, exist_ok=True)


def build_reclassification_rows(summary_path: Path, config_name: str, profile_name: str) -> list[dict]:
    payload = json.loads(summary_path.read_text(encoding='utf-8'))
    derived_rows = derive_rows(payload, config_name=config_name, profile_name=profile_name)
    rows = []
    for row in derived_rows:
        if row.get('тип поста') != 'требует уточнения':
            continue
        rows.append({
            'instance_id': INSTANCE_ID,
            'summary_input_path': str(summary_path),
            'канал': row.get('канал'),
            'дата-время': row.get('дата-время'),
            'ссылка': row.get('ссылка'),
            'краткое содержание': row.get('краткое содержание'),
            'саммари': row.get('саммари'),
            'альтернативный тип': row.get('_classification_alternative') or '',
            'confidence': row.get('_classification_confidence'),
            'исходный текст': row.get('_raw_text') or '',
        })
    return rows


def write_reclassification_artifacts(rows: list[dict], stamp: str) -> tuple[Path | None, Path | None]:
    if not rows:
        return None, None
    json_path = OUT_DIR / f'telegram_it_consulting_requires_review_reclassification_{stamp}.json'
    csv_path = OUT_DIR / f'telegram_it_consulting_requires_review_reclassification_{stamp}.csv'
    json_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
    with csv_path.open('w', encoding='utf-8-sig', newline='') as file_obj:
        writer = csv.DictWriter(
            file_obj,
            fieldnames=[
                'instance_id',
                'summary_input_path',
                'канал',
                'дата-время',
                'ссылка',
                'краткое содержание',
                'саммари',
                'альтернативный тип',
                'confidence',
                'исходный текст',
            ],
        )
        writer.writeheader()
        writer.writerows(rows)
    return json_path, csv_path


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
    reclassification_rows = []

    for summary_path in summaries:
        digest_payload = build_digest_payload(
            summary_path,
            config_name=DEFAULT_CONFIG_NAME,
            profile_name=DEFAULT_PROFILE_NAME,
        )
        non_empty_counts.append(digest_payload['non_empty_messages'])
        requires_review_total += digest_payload['requires_review_count']
        reclassification_rows.extend(
            build_reclassification_rows(
                summary_path,
                config_name=DEFAULT_CONFIG_NAME,
                profile_name=DEFAULT_PROFILE_NAME,
            )
        )
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

    stamp = msk_now().strftime('%Y-%m-%d_%H-%M-%S')
    qa_path = OUT_DIR / f'telegram_it_consulting_weekly_qa_{stamp}.json'
    reclass_json_path, reclass_csv_path = write_reclassification_artifacts(reclassification_rows, stamp)
    qa_data = {
        'generated_at': msk_now().isoformat(),
        'instance_id': INSTANCE_ID,
        'runs_total': runs_total,
        'no_new_runs': no_new_runs,
        'failed_runs': failed_runs,
        'summary_files': len(summaries),
        'average_non_empty_messages': average_non_empty,
        'requires_review_total': requires_review_total,
        'requires_review_reclassification_json': str(reclass_json_path) if reclass_json_path else None,
        'requires_review_reclassification_csv': str(reclass_csv_path) if reclass_csv_path else None,
        'top_useful_channels': top_useful,
        'highest_volume_channels': noisy,
        'type_counts': type_counts,
    }

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
    if reclass_csv_path:
        lines.append(
            "Переклассификация 'требует уточнения' собрана в отдельную задачу: "
            f"CSV: {reclass_csv_path}; JSON: {reclass_json_path}."
        )
    else:
        lines.append("Переклассификация 'требует уточнения' не требуется: спорных сообщений в окне нет.")

    lines.append(f"JSON: {qa_path}")
    print('\n'.join(lines))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
