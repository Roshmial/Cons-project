import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

from telegram_monitor_pipeline import (
    AUTO_OVERRIDE_PATH,
    FIXED_TYPES,
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


def list_all_summary_inputs() -> list[Path]:
    raw_logs_dir = Path('/home/hermes/workspace/TG-API/runtime') / str(INSTANCE_ID) / 'raw_logs'
    return sorted(raw_logs_dir.glob('raw_*_summary_input.json'))


def load_auto_overrides() -> dict[str, str]:
    if not AUTO_OVERRIDE_PATH.exists():
        return {}
    try:
        payload = json.loads(AUTO_OVERRIDE_PATH.read_text(encoding='utf-8'))
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    return {
        key: value for key, value in payload.items()
        if isinstance(key, str) and isinstance(value, str) and value in FIXED_TYPES
    }


def guess_residual_type(row: dict) -> str:
    text = ' '.join(filter(None, [row.get('краткое содержание'), row.get('саммари'), row.get('исходный текст')])).lower()
    channel = (row.get('канал') or '').lower()

    event_tokens = (
        'summit', 'саммит', 'форум', 'подкаст', 'бизнес-завтрак', 'прошел', 'прошла',
        'лига', 'преми', 'сесси', 'полигон', 'конферен', 'вебинар', 'митап', 'завтрак'
    )
    corporate_tokens = (
        'выручк', 'облигац', 'покидает пост', 'покинул пост', 'банкрот', 'назнач', 'фоторепортаж',
        'снимков', 'фотограф', 'спортивных достижени', 'копилку', 'завершилась лига', 'прошел в офисе'
    )
    case_tokens = (
        'опыт ', 'внедр', 'перестройк', 'оптимизировал', 'экономический эффект', 'помог', 'защитил цод',
        'цифровое производство', 'разработал стратегию', 'строить собственные цоды', 'потратил', 'увеличил расходы',
        'провели большую перестройку', 'робот на складе', 'как избавиться от монолита'
    )
    interview_tokens = (
        '— о ', 'рассказал на ', 'о вызовах внедрения', 'по его словам', 'василий кузнецов', 'cio ', 'колонке для',
        'прокоммент', 'интервью'
    )
    research_tokens = (
        'исследован', 'большое исследование', 'делится исследованием'
    )
    market_tokens = (
        'гид tadviser', 'обзор tadviser', 'гид ', 'обзор ', 'рынк', 'правила', 'закон', 'закона', 'последствия',
        'нарушают новые правила', 'хакерских атак', 'под запретом', 'маркировка контента', 'облака будущего'
    )
    analytics_tokens = (
        'что изменится', 'как ', 'почему ', 'драйвер', 'стратег', 'новая популярность', 'без чего',
        'мультиагентность', 'реальная картина', 'близко к сердцу'
    )
    product_tokens = (
        'архитектур', 'платформ', 'решени', 'система', 'мультиагентность — тип архитектуры'
    )

    if any(t in text for t in research_tokens):
        return 'исследование'
    if any(t in text for t in event_tokens):
        return 'мероприятие'
    if any(t in text for t in interview_tokens):
        return 'интервью/комментарий'
    if any(t in text for t in case_tokens):
        return 'кейс'
    if any(t in text for t in corporate_tokens):
        return 'корпоративная новость'
    if any(t in text for t in product_tokens):
        return 'продукт/решение'
    if any(t in text for t in analytics_tokens):
        return 'аналитика'
    if any(t in text for t in market_tokens):
        return 'обзор рынка'

    if channel == 'b1_news':
        return 'корпоративная новость'
    if channel == 'kept_business':
        return 'аналитика'
    if channel == 'axenix_ru':
        return 'аналитика'
    if channel == 'lanit_life':
        return 'аналитика'
    if channel == 'k2_tech':
        return 'мероприятие'
    if channel == 'yakovpartners':
        return 'аналитика'
    if channel == 'tadviser':
        return 'обзор рынка'
    return 'корпоративная новость'


def persist_auto_overrides(rows: list[dict]) -> tuple[Path, int]:
    overrides = load_auto_overrides()
    updated = 0
    for row in rows:
        url = row.get('ссылка')
        suggested_type = row.get('альтернативный тип') or guess_residual_type(row)
        if not url or not suggested_type or suggested_type not in FIXED_TYPES:
            continue
        if overrides.get(url) == suggested_type:
            continue
        overrides[url] = suggested_type
        updated += 1
    AUTO_OVERRIDE_PATH.write_text(json.dumps(dict(sorted(overrides.items())), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return AUTO_OVERRIDE_PATH, updated


def write_reclassification_markdown(rows: list[dict], stamp: str) -> Path | None:
    if not rows:
        return None
    md_path = OUT_DIR / f'telegram_it_consulting_requires_review_reclassification_{stamp}.md'
    suggested = [row for row in rows if row.get('альтернативный тип')]
    unresolved = [row for row in rows if not row.get('альтернативный тип')]
    by_type = Counter(row['альтернативный тип'] for row in suggested if row.get('альтернативный тип'))

    lines = [
        'Еженедельная переклассификация residue по типу «требует уточнения».',
        '',
        f'- всего спорных сообщений: {len(rows)}',
        f'- есть предложенный альтернативный тип: {len(suggested)}',
        f'- без уверенной альтернативы: {len(unresolved)}',
    ]
    if by_type:
        lines.append('- распределение предложенных типов: ' + '; '.join(f'{post_type}: {count}' for post_type, count in by_type.most_common()))
    lines.append('')

    for idx, row in enumerate(rows, start=1):
        alt = row.get('альтернативный тип') or 'без уверенной альтернативы'
        conf = row.get('confidence')
        conf_text = '' if conf in (None, '') else f" | confidence={conf}"
        lines.append(f"{idx}. {row.get('ссылка') or '—'} -> {alt}{conf_text}")
        lines.append(f"   Канал: {row.get('канал') or '—'} | Дата: {row.get('дата-время') or '—'}")
        if row.get('краткое содержание'):
            lines.append(f"   Краткое содержание: {row['краткое содержание']}")
        lines.append('')

    md_path.write_text('\n'.join(lines).rstrip() + '\n', encoding='utf-8')
    return md_path


def main() -> int:
    reports = list_recent_collection_reports(days=7)
    summaries = list_recent_summary_inputs(days=7)
    all_summaries = list_all_summary_inputs()

    runs_total = len(reports)
    no_new_runs = sum(1 for report in reports if report.get('status') == 'no_new_messages')
    failed_runs = sum(1 for report in reports if report.get('status') not in {'ok', 'no_new_messages'})

    non_empty_counts = []
    requires_review_total = 0
    channel_scores = defaultdict(float)
    channel_counts = Counter()
    type_counts = Counter()
    reclassification_rows = []
    historical_reclassification_rows = []

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

    for summary_path in all_summaries:
        historical_reclassification_rows.extend(
            build_reclassification_rows(
                summary_path,
                config_name=DEFAULT_CONFIG_NAME,
                profile_name=DEFAULT_PROFILE_NAME,
            )
        )

    # Weekly QA is read-only: it must never alter future classifications.
    auto_override_path, auto_override_updates = AUTO_OVERRIDE_PATH, 0

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
    reclass_md_path = write_reclassification_markdown(reclassification_rows, stamp)
    hist_reclass_json_path, hist_reclass_csv_path = write_reclassification_artifacts(historical_reclassification_rows, f'{stamp}_all_history')
    hist_reclass_md_path = write_reclassification_markdown(historical_reclassification_rows, f'{stamp}_all_history')
    suggested_count = sum(1 for row in reclassification_rows if row.get('альтернативный тип'))
    unresolved_count = len(reclassification_rows) - suggested_count
    historical_suggested_count = sum(1 for row in historical_reclassification_rows if row.get('альтернативный тип'))
    historical_unresolved_count = len(historical_reclassification_rows) - historical_suggested_count
    suggested_type_counts = Counter(
        row['альтернативный тип'] for row in reclassification_rows if row.get('альтернативный тип')
    )
    historical_suggested_type_counts = Counter(
        row['альтернативный тип'] for row in historical_reclassification_rows if row.get('альтернативный тип')
    )
    qa_data = {
        'generated_at': msk_now().isoformat(),
        'instance_id': INSTANCE_ID,
        'runs_total': runs_total,
        'no_new_runs': no_new_runs,
        'failed_runs': failed_runs,
        'summary_files': len(summaries),
        'history_summary_files': len(all_summaries),
        'average_non_empty_messages': average_non_empty,
        'requires_review_total': requires_review_total,
        'requires_review_reclassification_json': str(reclass_json_path) if reclass_json_path else None,
        'requires_review_reclassification_csv': str(reclass_csv_path) if reclass_csv_path else None,
        'requires_review_reclassification_md': str(reclass_md_path) if reclass_md_path else None,
        'requires_review_suggested_count': suggested_count,
        'requires_review_unresolved_count': unresolved_count,
        'requires_review_suggested_type_counts': suggested_type_counts,
        'history_requires_review_total': len(historical_reclassification_rows),
        'history_requires_review_reclassification_json': str(hist_reclass_json_path) if hist_reclass_json_path else None,
        'history_requires_review_reclassification_csv': str(hist_reclass_csv_path) if hist_reclass_csv_path else None,
        'history_requires_review_reclassification_md': str(hist_reclass_md_path) if hist_reclass_md_path else None,
        'history_requires_review_suggested_count': historical_suggested_count,
        'history_requires_review_unresolved_count': historical_unresolved_count,
        'history_requires_review_suggested_type_counts': historical_suggested_type_counts,
        'auto_override_path': str(auto_override_path),
        'auto_override_updates': auto_override_updates,
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
            f"За 7 дней предварительная переклассификация выполнена: с предложенным типом {suggested_count}; без уверенной альтернативы {unresolved_count}."
        )
        if suggested_type_counts:
            formatted = '; '.join(f"{post_type}: {count}" for post_type, count in suggested_type_counts.most_common())
            lines.append(f"Предложенные типы по residue за 7 дней: {formatted}.")
        lines.append(
            "Артефакты переклассификации за 7 дней: "
            f"CSV: {reclass_csv_path}; JSON: {reclass_json_path}; MD: {reclass_md_path}."
        )
    else:
        lines.append("Переклассификация 'требует уточнения' за 7 дней не требуется: спорных сообщений в окне нет.")

    if historical_reclassification_rows:
        lines.append(
            f"Исторический backlog: {len(historical_reclassification_rows)}; с предложенным типом {historical_suggested_count}; без уверенной альтернативы {historical_unresolved_count}."
        )
        lines.append(
            "Артефакты переклассификации по всей истории: "
            f"CSV: {hist_reclass_csv_path}; JSON: {hist_reclass_json_path}; MD: {hist_reclass_md_path}."
        )
    else:
        lines.append("Исторический backlog спорных сообщений отсутствует.")
    lines.append("Автоматическое изменение override-словаря отключено: QA работает только на чтение.")

    lines.append(f"JSON: {qa_path}")
    print('\n'.join(lines))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
