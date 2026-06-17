import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from html import escape
from pathlib import Path
from typing import Any, Dict, List

from telegram_monitor_pipeline import (
    MSK,
    build_digest_payload,
    fmt_msk,
    list_recent_summary_inputs,
    msk_now,
    parse_dt,
)

BASE_DIR = Path(__file__).resolve().parent
ANALYTICS_DIR = BASE_DIR / "analytics"
CURRENT_HTML = ANALYTICS_DIR / "local_analytics_dashboard_current.html"
CURRENT_JSON = ANALYTICS_DIR / "local_analytics_dashboard_current.json"


def load_reports(days: int) -> List[Dict[str, Any]]:
    reports: List[Dict[str, Any]] = []
    for summary_path in list_recent_summary_inputs(days=days):
        report = build_digest_payload(summary_path, config_name="daily", profile_name="profile_1")
        report["summary_path"] = str(summary_path)
        reports.append(report)
    return reports


def iso_day_msk(value: str) -> str:
    return parse_dt(value).astimezone(MSK).strftime("%Y-%m-%d")


def compact_top_row(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "канал": row.get("канал"),
        "дата-время": row.get("дата-время"),
        "тип поста": row.get("тип поста"),
        "score": row.get("score", row.get("_score")),
        "ссылка": row.get("ссылка"),
        "краткое содержание": row.get("краткое содержание"),
        "саммари": row.get("саммари"),
    }


def build_dataset(days: int = 7) -> Dict[str, Any]:
    reports = load_reports(days)
    rows: List[Dict[str, Any]] = []
    summary_files: List[str] = []
    raw_dates: List[str] = []

    for report in reports:
        summary_files.append(report["summary_path"])
        for row in report.get("rows", []):
            rows.append(row)
            raw_dates.append(row["дата-время"])

    if not rows:
        return {
            "generated_at": msk_now().strftime("%d.%m.%Y %H:%M МСК"),
            "period": {"days": days, "summary_files": 0},
            "totals": {"digest_rows": 0, "channels": 0, "types": 0, "requires_review_count": 0},
            "daily": [],
            "channel_counts": [],
            "type_counts": [],
            "top_posts": [],
            "summary_files": summary_files,
        }

    day_stats: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
        "date": "",
        "rows_total": 0,
        "requires_review_count": 0,
        "top_score": 0.0,
        "non_empty_messages": 0,
    })
    channel_counter: Counter[str] = Counter()
    type_counter: Counter[str] = Counter()

    for row in rows:
        dt = datetime.strptime(row["дата-время"], "%d.%m.%Y %H:%M МСК")
        day = dt.strftime("%Y-%m-%d")
        bucket = day_stats[day]
        bucket["date"] = day
        bucket["rows_total"] += 1
        bucket["non_empty_messages"] += 1
        if row.get("тип поста") == "требует уточнения":
            bucket["requires_review_count"] += 1
        bucket["top_score"] = max(bucket["top_score"], float(row.get("_score", row.get("score", 0)) or 0))
        channel_counter[row.get("канал") or "—"] += 1
        type_counter[row.get("тип поста") or "—"] += 1

    daily = sorted(day_stats.values(), key=lambda item: item["date"])
    top_posts_source = sorted(rows, key=lambda row: float(row.get("_score", row.get("score", 0)) or 0), reverse=True)
    top_posts = [compact_top_row(row) for row in top_posts_source[:15]]

    from_day = daily[0]["date"]
    to_day = daily[-1]["date"]
    total_rows = len(rows)
    requires_review_count = sum(1 for row in rows if row.get("тип поста") == "требует уточнения")
    totals = {
        "digest_rows": total_rows,
        "channels": len(channel_counter),
        "types": len(type_counter),
        "requires_review_count": requires_review_count,
        "review_share": round(requires_review_count / total_rows, 3) if total_rows else 0,
        "avg_rows_per_day": round(total_rows / len(daily), 2) if daily else 0,
        "max_rows_day": max(daily, key=lambda item: item["rows_total"]),
        "min_rows_day": min(daily, key=lambda item: item["rows_total"]),
    }

    return {
        "generated_at": msk_now().strftime("%d.%m.%Y %H:%M МСК"),
        "period": {
            "days": days,
            "from": from_day,
            "to": to_day,
            "summary_files": len(summary_files),
        },
        "totals": totals,
        "daily": daily,
        "channel_counts": channel_counter.most_common(12),
        "type_counts": type_counter.most_common(),
        "top_posts": top_posts,
        "summary_files": summary_files,
    }


def render_kpi(title: str, value: str, note: str = "") -> str:
    note_html = f"<div class='note'>{escape(note)}</div>" if note else ""
    return f"<div class='card'><div class='label'>{escape(title)}</div><div class='value'>{escape(value)}</div>{note_html}</div>"


def render_table(rows: List[List[str]], headers: List[str]) -> str:
    thead = "".join(f"<th>{escape(h)}</th>" for h in headers)
    body_rows = []
    for row in rows:
        body_rows.append("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>")
    return f"<table><thead><tr>{thead}</tr></thead><tbody>{''.join(body_rows)}</tbody></table>"


def render_html(data: Dict[str, Any]) -> str:
    totals = data["totals"]
    period = data["period"]

    kpis = "".join([
        render_kpi("Постов в выборке", str(totals.get("digest_rows", 0)), f"Файлов сводки: {period.get('summary_files', 0)}"),
        render_kpi("Каналов", str(totals.get("channels", 0))),
        render_kpi("Типов постов", str(totals.get("types", 0))),
        render_kpi("Требует уточнения", str(totals.get("requires_review_count", 0)), f"Доля: {round(float(totals.get('review_share', 0)) * 100, 1)}%"),
        render_kpi("Средний объём в день", str(totals.get("avg_rows_per_day", 0))),
        render_kpi("Пиковый день", str(totals.get("max_rows_day", {}).get("rows_total", 0)), totals.get("max_rows_day", {}).get("date", "")),
    ])

    daily_rows = []
    for item in data.get("daily", []):
        daily_rows.append([
            escape(item["date"]),
            escape(str(item["rows_total"])),
            escape(str(item["requires_review_count"])),
            escape(str(item["top_score"])),
        ])

    channel_rows = [[escape(name), escape(str(count))] for name, count in data.get("channel_counts", [])]
    type_rows = [[escape(name), escape(str(count))] for name, count in data.get("type_counts", [])]

    top_post_rows = []
    for item in data.get("top_posts", []):
        link = item.get("ссылка") or ""
        title = escape(item.get("краткое содержание") or "")
        summary = escape(item.get("саммари") or "")
        top_post_rows.append([
            escape(item.get("канал") or ""),
            escape(item.get("тип поста") or ""),
            escape(str(item.get("score") or "")),
            f"<a href='{escape(link)}' target='_blank' rel='noreferrer'>{title}</a><div class='summary'>{summary}</div>",
        ])

    summary_file_items = "".join(f"<li>{escape(path)}</li>" for path in data.get("summary_files", []))

    return f"""<!doctype html>
<html lang='ru'>
<head>
<meta charset='utf-8'>
<title>Локальная аналитика Telegram</title>
<style>
body{{font-family:Inter,Segoe UI,Arial,sans-serif;background:#f3f6fb;color:#1f2937;margin:0;padding:24px;}}
.wrap{{max-width:1480px;margin:0 auto;}}
h1{{margin:0 0 8px 0;font-size:32px;}} h2{{margin:0 0 14px 0;font-size:22px;}}
.sub{{color:#6b7280;margin-bottom:20px;}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:14px;margin:18px 0 26px;}}
.card,section{{background:#fff;border:1px solid #e5e7eb;border-radius:16px;padding:16px;box-shadow:0 8px 24px rgba(15,23,42,.05);}}
.label{{font-size:13px;color:#6b7280;margin-bottom:8px;text-transform:uppercase;letter-spacing:.04em;}}
.value{{font-size:30px;font-weight:700;line-height:1.1;}}
.note{{margin-top:8px;color:#6b7280;font-size:13px;}}
.sections{{display:grid;grid-template-columns:1.2fr .8fr;gap:16px;align-items:start;}}
.sections-bottom{{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:16px;align-items:start;}}
section{{margin-bottom:16px;}}
table{{width:100%;border-collapse:collapse;font-size:14px;}}
th,td{{padding:10px 12px;border-bottom:1px solid #e5e7eb;vertical-align:top;text-align:left;}}
th{{font-size:12px;color:#6b7280;text-transform:uppercase;letter-spacing:.04em;}}
.summary{{margin-top:6px;color:#4b5563;line-height:1.4;}}
a{{color:#2563eb;text-decoration:none;}}
a:hover{{text-decoration:underline;}}
ul{{margin:0;padding-left:18px;}}
@media (max-width: 1080px){{.sections,.sections-bottom{{grid-template-columns:1fr;}}}}
</style>
</head>
<body>
<div class='wrap'>
<h1>Дашборд по локальной аналитике</h1>
<div class='sub'>Период сообщений: {escape(period.get('from', '—'))} — {escape(period.get('to', '—'))}. Сформировано: {escape(data.get('generated_at', ''))}. Источник — локальные summary_input из TG-API, агрегированы последние {escape(str(period.get('summary_files', 0)))} файлов сводки.</div>
<div class='grid'>{kpis}</div>
<div class='sections'>
  <section>
    <h2>Динамика по дням</h2>
    {render_table(daily_rows, ['Дата', 'Постов', 'Требует уточнения', 'Топ score'])}
  </section>
  <section>
    <h2>Топ каналов</h2>
    {render_table(channel_rows, ['Канал', 'Постов'])}
  </section>
</div>
<div class='sections-bottom'>
  <section>
    <h2>Типы постов</h2>
    {render_table(type_rows, ['Тип', 'Количество'])}
  </section>
  <section>
    <h2>Исходные файлы</h2>
    <ul>{summary_file_items}</ul>
  </section>
</div>
<section>
  <h2>Топ постов по внутреннему score</h2>
  {render_table(top_post_rows, ['Канал', 'Тип', 'Score', 'Пост'])}
</section>
</div>
</body>
</html>"""


def main() -> int:
    ANALYTICS_DIR.mkdir(parents=True, exist_ok=True)
    data = build_dataset(days=7)
    stamp = datetime.now(MSK).strftime("%Y-%m-%d_%H-%M-%S")
    html_path = ANALYTICS_DIR / f"local_analytics_dashboard_{stamp}.html"
    json_path = ANALYTICS_DIR / f"local_analytics_dashboard_{stamp}.json"
    html = render_html(data)
    html_path.write_text(html, encoding="utf-8")
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    CURRENT_HTML.write_text(html, encoding="utf-8")
    CURRENT_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "html": str(html_path),
        "json": str(json_path),
        "current_html": str(CURRENT_HTML),
        "current_json": str(CURRENT_JSON),
        "totals": data.get("totals", {}),
        "period": data.get("period", {}),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
