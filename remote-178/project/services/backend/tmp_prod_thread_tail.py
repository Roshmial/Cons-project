import app
with app.db_connect() as conn:
    rows = conn.execute("SELECT id, role, substr(content,1,120) as content FROM messages WHERE thread_id = ? ORDER BY id DESC LIMIT 6", (242,)).fetchall()
    for row in rows:
        print(dict(row))
