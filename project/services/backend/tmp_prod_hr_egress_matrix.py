import json, urllib.request
urls = [
    'https://news.google.com/',
    'https://www.rbc.ru/',
    'https://www.kommersant.ru/',
    'https://hr-portal.ru/news',
    'https://www.hrdive.com/',
]
out = []
for url in urls:
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            out.append({'url': url, 'status': r.status, 'final_url': r.geturl()})
    except Exception as e:
        out.append({'url': url, 'error': f'{type(e).__name__}: {e}'})
print(json.dumps(out, ensure_ascii=False))
