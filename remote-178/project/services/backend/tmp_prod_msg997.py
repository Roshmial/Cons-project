import app
with app.db_connect() as conn:
    row = conn.execute("SELECT * FROM messages WHERE id = ?", (997,)).fetchone()
    print(dict(row))
