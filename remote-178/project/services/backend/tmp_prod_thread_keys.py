import app
with app.db_connect() as conn:
    row = conn.execute("SELECT * FROM threads WHERE id = ?", (242,)).fetchone()
    print(list(row.keys()))
    print(dict(row))
