from pathlib import Path
import csv, json, re, math
from collections import Counter, defaultdict
from datetime import datetime

base = Path('/home/hermes/workspace/TG-API')
csv_path = base / 'exports' / 'telegram_it_consulting_full_export_2026-06-10.csv'
out_html = base / 'analytics' / 'telegram_export_dashboard_2026-06-11.html'
out_json = base / 'analytics' / 'telegram_export_dashboard_2026-06-11.json'

rows = []
with csv_path.open('r', encoding='utf-8-sig', newline='') as f:
    reader = csv.DictReader(f)
    for r in reader:
        rows.append(r)

for r in rows:
    r['dt'] = datetime.strptime(r['дата-время'], '%d.%m.%Y %H:%M МСК')
    r['date'] = r['dt'].strftime('%Y-%m-%d')
    try:
        r['score_num'] = float((r.get('score') or '').replace(',', '.'))
    except Exception:
        r['score_num'] = None

rows.sort(key=lambda x: x['dt'])

dates = sorted({r['date'] for r in rows})
type_counts_all = Counter(r['тип поста'] for r in rows)
main_types = [t for t, _ in type_counts_all.most_common(8)]
if len(type_counts_all) > 8:
    main_types.append('прочее')

by_day_type = defaultdict(Counter)
by_day_total = Counter()
by_day_channel = defaultdict(Counter)
by_channel = Counter()
by_type = Counter()

for r in rows:
    t = r['тип поста']
    key_t = t if t in main_types else 'прочее'
    by_day_type[r['date']][key_t] += 1
    by_day_total[r['date']] += 1
    by_day_channel[r['date']][r['канал']] += 1
    by_channel[r['канал']] += 1
    by_type[t] += 1

patterns = {
    'ИИ и внедрение': ['ии', 'ai', 'искусствен', 'генератив', 'внедрен', 'платформ'],
    'Импортозамещение и российские решения': ['импортозамещ', 'российск', 'отечествен', 'решени', 'продукт'],
    'Отраслевые кейсы и цифровизация': ['фармацев', 'медицин', 'здравоохран', 'логист', 'производ', 'документ'],
    'HR и опыт сотрудников': ['hr', 'сотрудник', 'кадров', 'опыт сотрудников', 'персонал'],
    'Финансы, отчетность и регулирование': ['отчет', 'pillar', 'ifrs', 'налог', 'аудит', 'мсфо'],
    'События и партнерства': ['пмэф', 'партнер', 'вебинар', 'конференц', 'форум', 'сесси'],
}

def count_theme(words):
    n = 0
    ch = Counter()
    for r in rows:
        text = (' '.join([r.get('краткое содержание',''), r.get('саммари','')])).lower()
        if any(w in text for w in words):
            n += 1
            ch[r['канал']] += 1
    return n, ch.most_common(3)

themes = []
for name, words in patterns.items():
    n, topch = count_theme(words)
    themes.append({'theme': name, 'posts': n, 'top_channels': topch})
themes.sort(key=lambda x: x['posts'], reverse=True)

avg = len(rows) / len(dates)
factor_rows = []
for d in dates:
    total = by_day_total[d]
    factor_rows.append({
        'date': d,
        'total': total,
        'top_channels': by_day_channel[d].most_common(3),
        'top_types': by_day_type[d].most_common(3),
        'review_share': round(by_day_type[d].get('требует уточнения', 0) / total, 3) if total else 0,
    })

colors = {
    'требует уточнения':'#94a3b8',
    'обзор рынка':'#2563eb',
    'мероприятие':'#14b8a6',
    'корпоративная новость':'#f59e0b',
    'продукт/решение':'#8b5cf6',
    'кейс':'#ef4444',
    'исследование':'#10b981',
    'аналитика':'#06b6d4',
    'партнерство':'#e11d48',
    'интервью/комментарий':'#84cc16',
    'прочее':'#64748b'
}

W, H = 1320, 520
ml, mr, mt, mb = 70, 80, 30, 70
cw, ch = W - ml - mr, H - mt - mb
max_total = max(by_day_total.values()) if dates else 1
bar_w = cw / max(len(dates), 1) * 0.62
step = cw / max(len(dates), 1)

def y(v):
    return mt + ch - (v / max_total) * ch

parts = [f"<svg width='{W}' height='{H}' viewBox='0 0 {W} {H}' xmlns='http://www.w3.org/2000/svg'>", "<rect width='100%' height='100%' fill='white'/>"]
step_grid = max(1, math.ceil(max_total / 6))
for i in range(0, max_total + 1, step_grid):
    yy = y(i)
    parts.append(f"<line x1='{ml}' y1='{yy:.1f}' x2='{W-mr}' y2='{yy:.1f}' stroke='#e5e7eb' stroke-width='1'/>")
    parts.append(f"<text x='{ml-10}' y='{yy+4:.1f}' text-anchor='end' font-size='12' fill='#64748b'>{i}</text>")
line_pts = []
for idx, d in enumerate(dates):
    x = ml + idx * step + (step - bar_w) / 2
    accum = 0
    for s in main_types:
        v = by_day_type[d].get(s, 0)
        if not v:
            continue
        y2 = y(accum)
        accum += v
        y1 = y(accum)
        parts.append(
            f"<rect x='{x:.1f}' y='{y1:.1f}' width='{bar_w:.1f}' height='{max(0.8, y2-y1):.1f}' fill='{colors.get(s, '#999')}' rx='2'><title>{d} | {s}: {v}</title></rect>"
        )
    cx = x + bar_w / 2
    cy = y(by_day_total[d])
    line_pts.append(f"{cx:.1f},{cy:.1f}")
    parts.append(f"<text x='{cx:.1f}' y='{H-mb+20}' text-anchor='middle' font-size='12' fill='#334155'>{d[5:]}</text>")
    parts.append(f"<text x='{cx:.1f}' y='{cy-8:.1f}' text-anchor='middle' font-size='12' fill='#0f172a'>{by_day_total[d]}</text>")
parts.append(f"<polyline fill='none' stroke='#0f172a' stroke-width='3' points='{' '.join(line_pts)}'/>")
for pt in line_pts:
    cx, cy = pt.split(',')
    parts.append(f"<circle cx='{cx}' cy='{cy}' r='4' fill='#0f172a'/>")
parts.append(f"<text x='{W/2}' y='{H-18}' text-anchor='middle' font-size='13' fill='#475569'>Дни</text>")
parts.append(f"<text x='18' y='{H/2}' transform='rotate(-90 18,{H/2})' text-anchor='middle' font-size='13' fill='#475569'>Количество сообщений</text>")
parts.append('</svg>')
svg = ''.join(parts)

legend = ''.join([f"<span class='legend-item'><span class='sw' style='background:{colors.get(s)}'></span>{s}</span>" for s in main_types]) + "<span class='legend-item'><span class='sw line'></span>всего сообщений</span>"

peak_day = max(dates, key=lambda d: by_day_total[d])
peak_channels = ', '.join(f"{c} ({n})" for c, n in by_day_channel[peak_day].most_common(3))
peak_types = ', '.join(f"{t} ({n})" for t, n in by_day_type[peak_day].most_common(3))

html = f"""<!doctype html>
<html lang='ru'>
<head>
<meta charset='utf-8'>
<title>Дашборд по выгрузке Telegram</title>
<style>
body{{font-family:Inter,Segoe UI,Arial,sans-serif;background:#f8fafc;color:#0f172a;margin:0;padding:24px}}
.wrap{{max-width:1460px;margin:0 auto}}
h1{{margin:0 0 8px;font-size:30px}} .sub{{color:#475569;margin-bottom:18px}}
.grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:18px 0}}
.card,section{{background:#fff;border:1px solid #e2e8f0;border-radius:16px;padding:16px;box-shadow:0 10px 25px rgba(15,23,42,.04)}}
.label{{font-size:12px;text-transform:uppercase;color:#64748b;margin-bottom:8px}} .value{{font-size:30px;font-weight:700}}
.note{{font-size:13px;color:#64748b;margin-top:6px}}
.legend{{display:flex;gap:12px;flex-wrap:wrap;margin:8px 0 14px}} .legend-item{{display:inline-flex;align-items:center;gap:6px;font-size:13px;color:#334155}}
.sw{{display:inline-block;width:12px;height:12px;border-radius:3px}} .sw.line{{background:#0f172a;border-radius:999px;height:4px;width:18px}}
.two{{display:grid;grid-template-columns:1.1fr .9fr;gap:16px;margin-top:16px}} .three{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px;margin-top:16px}}
table{{width:100%;border-collapse:collapse;font-size:14px}} th,td{{padding:9px 10px;border-bottom:1px solid #e2e8f0;vertical-align:top;text-align:left}} th{{font-size:12px;color:#64748b;text-transform:uppercase}}
ul{{margin:0;padding-left:18px}} li{{margin:0 0 8px}}
.small{{font-size:13px;color:#475569;line-height:1.45}}
@media (max-width:1100px){{.grid,.two,.three{{grid-template-columns:1fr}} svg{{width:100%;height:auto}}}}
</style>
</head>
<body><div class='wrap'>
<h1>Дашборд по выгрузке Telegram-каналов</h1>
<div class='sub'>Источник: {csv_path.name}. Период: {dates[0]} — {dates[-1]}. Постов: {len(rows)}. Каналов: {len(by_channel)}.</div>
<div class='grid'>
<div class='card'><div class='label'>Постов</div><div class='value'>{len(rows)}</div><div class='note'>Среднее в день: {avg:.1f}</div></div>
<div class='card'><div class='label'>Каналов</div><div class='value'>{len(by_channel)}</div><div class='note'>Активнее всего: {by_channel.most_common(1)[0][0]} — {by_channel.most_common(1)[0][1]}</div></div>
<div class='card'><div class='label'>Типов сообщений</div><div class='value'>{len(by_type)}</div><div class='note'>Лидер: {by_type.most_common(1)[0][0]} — {by_type.most_common(1)[0][1]}</div></div>
<div class='card'><div class='label'>Пиковый день</div><div class='value'>{peak_day}</div><div class='note'>{by_day_total[peak_day]} сообщений</div></div>
</div>
<section>
<h2>Комбинированная диаграмма по типам сообщений по дням</h2>
<div class='small'>Столбцы — состав сообщений по типам, линия — общий дневной объём.</div>
<div class='legend'>{legend}</div>
{svg}
</section>
<div class='two'>
<section>
<h2>Ключевые темы сообщений</h2>
<ul>{''.join(f"<li><b>{t['theme']}</b> — {t['posts']} постов; ведущие каналы: {', '.join(f'{c} ({n})' for c, n in t['top_channels']) or '—'}.</li>" for t in themes[:6])}</ul>
</section>
<section>
<h2>Факторный анализ динамики</h2>
<ul>
<li><b>Эффект календаря.</b> Основной объём пришёлся на рабочие дни 02.06–06.06. Это указывает, что динамику формирует не равномерный поток, а деловой календарь публикаций.</li>
<li><b>Эффект источников.</b> Пик {peak_day} сформировали прежде всего {peak_channels}. Значит, всплеск объясняется вкладом нескольких активных каналов, а не общим ростом по всей выборке.</li>
<li><b>Эффект повестки.</b> В пиковый день доминировали {peak_types}. То есть рост идёт через сочетание обзорных, событийных и продуктовых публикаций.</li>
<li><b>Эффект разметки.</b> Тип «требует уточнения» даёт {by_type.get('требует уточнения', 0)} сообщений из {len(rows)}. Это искажает чистую интерпретацию динамики: часть роста связана с пограничной классификацией, а не с отдельной рыночной темой.</li>
</ul>
</section>
</div>
<div class='three'>
<section><h2>Топ типов</h2><table><thead><tr><th>Тип</th><th>Постов</th></tr></thead><tbody>{''.join(f'<tr><td>{t}</td><td>{n}</td></tr>' for t, n in by_type.most_common())}</tbody></table></section>
<section><h2>Топ каналов</h2><table><thead><tr><th>Канал</th><th>Постов</th></tr></thead><tbody>{''.join(f'<tr><td>{c}</td><td>{n}</td></tr>' for c, n in by_channel.most_common(12))}</tbody></table></section>
<section><h2>Дни и драйверы</h2><table><thead><tr><th>Дата</th><th>Всего</th><th>Топ каналы</th><th>Топ типы</th></tr></thead><tbody>{''.join(f"<tr><td>{r['date']}</td><td>{r['total']}</td><td>{', '.join(f'{c} ({n})' for c, n in r['top_channels'])}</td><td>{', '.join(f'{t} ({n})' for t, n in r['top_types'])}</td></tr>" for r in factor_rows)}</tbody></table></section>
</div>
</div></body></html>"""

out_html.write_text(html, encoding='utf-8')
summary = {
    'source_csv': str(csv_path),
    'output_html': str(out_html),
    'period': {'from': dates[0], 'to': dates[-1]},
    'rows': len(rows),
    'channels': len(by_channel),
    'types': dict(by_type),
    'by_day_total': dict(by_day_total),
    'themes': themes,
    'factor_rows': factor_rows,
}
out_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'html': str(out_html), 'json': str(out_json), 'rows': len(rows), 'top_types': by_type.most_common(5), 'top_channels': by_channel.most_common(5)}, ensure_ascii=False, indent=2))
