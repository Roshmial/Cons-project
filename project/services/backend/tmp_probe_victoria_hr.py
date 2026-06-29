import app, json
with app.db_connect() as conn:
    users = conn.execute("SELECT id, email, name, role, created_at FROM users WHERE lower(coalesce(name,'')) LIKE ? OR lower(coalesce(email,'')) LIKE ? ORDER BY id", ('%victoria%','%victoria%')).fetchall()
    out = {'users':[dict(r) for r in users]}
    if users:
        ids = tuple(int(r['id']) for r in users)
        q = ','.join('?' for _ in ids)
        threads = conn.execute(f"SELECT id, user_id, title, preview, thread_kind, updated_at FROM threads WHERE user_id IN ({q}) ORDER BY updated_at DESC LIMIT 30", ids).fetchall()
        out['threads'] = [dict(r) for r in threads]
        hr_threads = [r for r in threads if 'hr' in (r['title'] or '').lower() or 'тренд' in (r['title'] or '').lower()]
        out['hr_threads'] = [dict(r) for r in hr_threads]
        if hr_threads:
            t = hr_threads[0]
            msgs = conn.execute("SELECT id, role, content, created_at, meta_json FROM messages WHERE thread_id = ? ORDER BY id DESC LIMIT 12", (t['id'],)).fetchall()
            out['messages'] = [dict(r) for r in msgs]
            tasks = conn.execute("SELECT id, status, title, created_at, started_at, finished_at, last_error FROM chat_tasks WHERE thread_id = ? ORDER BY id DESC LIMIT 12", (t['id'],)).fetchall()
            out['chat_tasks'] = [dict(r) for r in tasks]
    print(json.dumps(out, ensure_ascii=False, default=str))
