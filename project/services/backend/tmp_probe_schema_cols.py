import app, json
with app.db_connect() as conn:
    info = {}
    for table in ['chat_tasks','jobs','job_runs','threads','users']:
        cols = conn.execute(f"SELECT column_name FROM information_schema.columns WHERE table_name = ? ORDER BY ordinal_position", (table,)).fetchall()
        info[table] = [r['column_name'] for r in cols]
    print(json.dumps(info, ensure_ascii=False))
