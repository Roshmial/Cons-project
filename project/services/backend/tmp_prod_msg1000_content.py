import app
with app.db_connect() as conn:
    row = conn.execute("SELECT content FROM messages WHERE id = ?", (1000,)).fetchone()
    print(row['content'][:3500])
