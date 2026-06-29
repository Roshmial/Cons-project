import app
with app.db_connect() as conn:
    row = conn.execute("SELECT * FROM messages WHERE thread_id = ? ORDER BY id ASC LIMIT 1", (242,)).fetchone()
    print(list(row.keys()))
    print(dict(row))
