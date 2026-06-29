import app, json
with app.db_connect() as conn:
    threads = conn.execute("SELECT id, user_id, title, preview, thread_kind, updated_at FROM threads WHERE lower(coalesce(title,'')) LIKE ? OR lower(coalesce(preview,'')) LIKE ? ORDER BY updated_at DESC LIMIT 40", ('%hr%','%hr%')).fetchall()
    out={'threads':[dict(r) for r in threads]}
    trend_threads = conn.execute("SELECT id, user_id, title, preview, thread_kind, updated_at FROM threads WHERE lower(coalesce(title,'')) LIKE ? OR lower(coalesce(preview,'')) LIKE ? ORDER BY updated_at DESC LIMIT 40", ('%тренд%','%тренд%')).fetchall()
    out['trend_threads']=[dict(r) for r in trend_threads]
    msg_hits = conn.execute("SELECT thread_id, id, role, substr(content,1,240) as content, created_at FROM messages WHERE lower(coalesce(content,'')) LIKE ? OR lower(coalesce(content,'')) LIKE ? ORDER BY id DESC LIMIT 40", ('%hr%','%тренд%')).fetchall()
    out['message_hits']=[dict(r) for r in msg_hits]
    print(json.dumps(out, ensure_ascii=False, default=str))
