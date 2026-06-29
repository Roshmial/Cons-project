import json, urllib.request
urls = ['https://www.google.com','https://www.wikipedia.org','https://httpbin.org/get']
out=[]
for url in urls:
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            out.append({'url':url,'status':r.status,'server':r.headers.get('server')})
    except Exception as e:
        out.append({'url':url,'error':type(e).__name__ + ': ' + str(e)})
print(json.dumps(out, ensure_ascii=False))
